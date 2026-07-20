import re
from pathlib import Path

import pandas as pd

from claim_mapping import (
    AFFILIATION_COLUMNS,
    EMAIL_COLUMNS,
    ENGLISH_NAME_COLUMNS,
    LOCAL_AFFILIATION_KEYWORDS,
    NAME_COLUMNS,
    discover_account_file,
    discover_article_library,
    find_first_column,
    infer_publication_name_to_real_name,
    is_claimable_email,
    is_local_affiliation,
    load_local_affiliation_keywords,
    load_name_to_email,
    parse_affiliations,
    parse_author_entries,
    read_table,
)


CLAIM_COLUMN = "作品认领"
SCOPE_COLUMNS = ["数据归属", "归属依据", "本校学者匹配", "本校学者邮箱", "学者匹配依据"]
PREFERRED_FRONT_COLUMNS = ["题名", *SCOPE_COLUMNS, CLAIM_COLUMN]
AUTHOR_FIELD_CANDIDATES = ["作者", "第一作者", "通讯作者", "已认领作者", "Author full names", "Authors", "Author"]
AFFILIATION_FIELD_CANDIDATES = ["作者单位", "第一作者单位", "通讯作者单位"]
FORMAL_BOWENGE_ALIAS_PATH = "src/博文阁用户别名表.xlsx"
DEFAULT_ALIAS_PATHS = [
    FORMAL_BOWENGE_ALIAS_PATH,
    "src/scholar_aliases.xlsx",
    "src/scholar_author_name_forms.xlsx",
]
REAL_NAME_COLUMNS = ["真实姓名", "姓名", "中文名", "学者姓名", "作者姓名", "scholar_name", "chinese_name", "Name", "name"]
ALIAS_COLUMNS = [
    "发文名", "作者发文名", "英文名", "英文姓名", "Author Name", "Author", "author",
    "name_form", "scholar_author_name_form", "别名", "其他别名", "姓名变体",
    "english_name", "author_name", "raw_author_name_form", "target_name_variants",
    "真实姓名", "姓名", "中文名", "学者姓名", "作者姓名", "scholar_name", "chinese_name",
    "English Name", "Name", "name",
]
EMAIL_ALIAS_COLUMNS = ["邮箱", "注册邮箱", "学者邮箱", "认领邮箱", "Email", "email", "E-mail", "e-mail"]
ID_COLUMNS = ["Scopus Author ID", "Author ID", "author_id", "scholar_id", "WOS ResearcherID", "ResearcherID", "ORCID"]
FORMAL_ALIAS_COLUMNS = ["别名", "姓名", "邮箱"]


def normalize_name(value: str) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("，", ",").replace("；", ";")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    return text.strip(" ;|、\n\t").lower()


def _split_alias_values(value):
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "unknown"}:
        return []
    parts = re.split(r"[;；|\n、]+", text)
    return [part.strip() for part in parts if _is_valid_alias(part)]


def split_author_names(value: str) -> list[str]:
    names = []
    for raw in _split_alias_values(value):
        cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        if cleaned:
            names.append(cleaned)
    return names


def _row_value(row, col):
    if not col:
        return ""
    value = row.get(col, "")
    if value is None or pd.isna(value):
        return ""
    value = str(value).strip()
    return "" if value.lower() == "nan" else value


def _is_valid_alias(value):
    text = "" if value is None else str(value).strip()
    return bool(text) and text.lower() not in {"nan", "none", "unknown", "null", "-"}


def _claimable_email_or_empty(email):
    email = str(email or "").strip()
    return email if is_claimable_email(email) else ""


def _is_priority_alias_source(source):
    source = str(source or "")
    return source.startswith("正式别名表") or source.startswith("学者别名表")


def _add_alias(registry, alias, real_name="", email="", source="", scholar_id=""):
    key = normalize_name(alias)
    if not key or not _is_valid_alias(key):
        return
    candidate_real = str(real_name or alias).strip()
    candidate_email = _claimable_email_or_empty(email)
    candidate_id = str(scholar_id or "").strip()

    if key not in registry["aliases"]:
        registry["aliases"][key] = {
            "alias": str(alias).strip(),
            "real_name": candidate_real,
            "email": candidate_email if "@" in candidate_email else "",
            "scholar_id": candidate_id,
            "sources": set(),
            "conflicts": [],
        }
    entry = registry["aliases"][key]
    existing_priority = any(_is_priority_alias_source(src) for src in entry.get("sources", set()))
    incoming_priority = _is_priority_alias_source(source)
    existing_identity = normalize_name(entry.get("real_name", "")) or str(entry.get("scholar_id", "")).strip()
    candidate_identity = normalize_name(candidate_real) or candidate_id
    existing_email = str(entry.get("email", "") or "").strip().lower()
    candidate_email_key = str(candidate_email or "").strip().lower() if "@" in candidate_email else ""
    identity_changed = candidate_identity and existing_identity and candidate_identity != existing_identity
    email_changed = candidate_email_key and existing_email and candidate_email_key != existing_email
    conflict_keys = {
        (
            normalize_name(c.get("real_name", "")) or str(c.get("scholar_id", "")).strip(),
            str(c.get("email", "") or "").strip().lower(),
        )
        for c in entry.get("conflicts", [])
    }
    if (
        (identity_changed or email_changed)
        and not (existing_priority and not incoming_priority)
        and (candidate_identity, candidate_email_key) not in conflict_keys
    ):
        entry.setdefault("conflicts", []).append({
            "real_name": candidate_real,
            "email": candidate_email if "@" in candidate_email else "",
            "scholar_id": candidate_id,
            "source": source,
        })
        registry["conflict_aliases"].add(key)
    if candidate_real and not entry["real_name"]:
        entry["real_name"] = candidate_real
    if candidate_email and not entry["email"]:
        entry["email"] = candidate_email
    if candidate_id and not entry.get("scholar_id"):
        entry["scholar_id"] = candidate_id
    if source:
        entry["sources"].add(source)


def _finalize_registry(registry):
    for entry in registry["aliases"].values():
        if isinstance(entry.get("sources"), set):
            entry["sources"] = sorted(entry["sources"])
    if isinstance(registry.get("conflict_aliases"), set):
        registry["conflict_aliases"] = sorted(registry["conflict_aliases"])
    return registry


def _find_first_present_column(columns, candidates):
    normalized = {str(col).strip().lower(): col for col in columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    return None


def _find_present_columns(columns, candidates):
    normalized_candidates = {candidate.strip().lower() for candidate in candidates}
    return [col for col in columns if str(col).strip().lower() in normalized_candidates]


def _resolve_alias_path(alias_path=None):
    if alias_path:
        path = Path(alias_path)
        return path if path.exists() else None
    for candidate in DEFAULT_ALIAS_PATHS:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _load_account_aliases(registry, account_path):
    if not account_path:
        return
    df = read_table(account_path)
    name_col = find_first_column(df.columns, NAME_COLUMNS)
    english_col = find_first_column(df.columns, ENGLISH_NAME_COLUMNS)
    email_col = find_first_column(df.columns, EMAIL_COLUMNS)
    alias_cols = [
        col for col in df.columns
        if any(candidate.lower() in str(col).lower() for candidate in ALIAS_COLUMNS)
    ]
    email_alias_cols = [
        col for col in df.columns
        if any(candidate.lower() == str(col).strip().lower() for candidate in EMAIL_ALIAS_COLUMNS)
    ]

    for _, row in df.iterrows():
        real_name = _row_value(row, name_col)
        email = _row_value(row, email_col)
        aliases = []
        for col in [name_col, english_col, *alias_cols]:
            aliases.extend(_split_alias_values(_row_value(row, col)))
        for alias in aliases:
            _add_alias(registry, alias, real_name=real_name or alias, email=email, source="账户表")
        for col in email_alias_cols:
            for email_alias in _split_alias_values(_row_value(row, col)):
                if "@" in email_alias:
                    _add_alias(registry, email_alias, real_name=real_name, email=email_alias, source="账户表邮箱")


def _load_article_aliases(registry, article_library_path, name_to_email, local_keywords):
    if not article_library_path:
        return
    pub_to_real = infer_publication_name_to_real_name(article_library_path, local_keywords)
    for publication_name, real_name in pub_to_real.items():
        email = name_to_email.get(normalize_name(real_name), "")
        _add_alias(registry, publication_name, real_name=real_name, email=email, source="文章库发文名")

    df = read_table(article_library_path)
    if "已认领作者" in df.columns:
        for _, row in df.iterrows():
            for real_name in _split_alias_values(row.get("已认领作者", "")):
                email = name_to_email.get(normalize_name(real_name), "")
                _add_alias(registry, real_name, real_name=real_name, email=email, source="文章库已认领作者")


def _load_priority_alias_file(registry, alias_path, name_to_email=None):
    if not alias_path:
        return
    alias_path = Path(alias_path)
    if not alias_path.exists():
        return
    name_to_email = name_to_email or {}
    xl = pd.ExcelFile(alias_path)
    registry["alias_path"] = str(alias_path)
    registry["alias_sheets"] = xl.sheet_names

    is_formal_file = alias_path.name == Path(FORMAL_BOWENGE_ALIAS_PATH).name

    for sheet_name in xl.sheet_names:
        df = pd.read_excel(alias_path, sheet_name=sheet_name, dtype=str)
        stripped_columns = {str(col).strip(): col for col in df.columns}
        if all(col in stripped_columns for col in FORMAL_ALIAS_COLUMNS):
            alias_col = stripped_columns["别名"]
            real_col = stripped_columns["姓名"]
            email_col = stripped_columns["邮箱"]
            source_label = "正式别名表" if is_formal_file else "学者别名表"
            for _, row in df[[alias_col, real_col, email_col]].drop_duplicates().iterrows():
                alias = _row_value(row, alias_col)
                real_name = _row_value(row, real_col)
                email = _row_value(row, email_col)
                _add_alias(
                    registry,
                    alias,
                    real_name=real_name or alias,
                    email=email,
                    source=f"{source_label}:{sheet_name}",
                )
            continue

        real_col = _find_first_present_column(df.columns, REAL_NAME_COLUMNS)
        alias_cols = _find_present_columns(df.columns, ALIAS_COLUMNS)
        email_col = _find_first_present_column(df.columns, EMAIL_ALIAS_COLUMNS)
        id_col = _find_first_present_column(df.columns, ID_COLUMNS)

        if not real_col and "english_name" in df.columns:
            real_col = "english_name"
        if not alias_cols:
            continue

        for _, row in df.iterrows():
            real_name = _row_value(row, real_col)
            email = _row_value(row, email_col)
            scholar_id = _row_value(row, id_col)
            if not email and real_name:
                email = name_to_email.get(normalize_name(real_name), "")
            aliases = []
            for col in alias_cols:
                aliases.extend(_split_alias_values(_row_value(row, col)))
            if real_name:
                aliases.append(real_name)
            for alias in aliases:
                _add_alias(
                    registry,
                    alias,
                    real_name=real_name or alias,
                    email=email,
                    source=f"学者别名表:{sheet_name}",
                    scholar_id=scholar_id,
                )


def build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=None) -> dict:
    article_library_path = article_library_path or discover_article_library()
    accounts_path = accounts_path or discover_account_file(article_library_path=article_library_path)
    resolved_alias_path = _resolve_alias_path(alias_path)
    registry = {
        "aliases": {},
        "conflict_aliases": set(),
        "alias_path": str(resolved_alias_path) if resolved_alias_path else "",
        "alias_sheets": [],
        "account_path": str(accounts_path) if accounts_path else "",
        "article_library_path": str(article_library_path) if article_library_path else "",
        "local_keywords": LOCAL_AFFILIATION_KEYWORDS.copy(),
    }

    name_to_email = {}
    if accounts_path:
        name_to_email = load_name_to_email(accounts_path)
        registry["local_keywords"].extend(load_local_affiliation_keywords(accounts_path))
    if resolved_alias_path:
        _load_priority_alias_file(registry, resolved_alias_path, name_to_email)
    if accounts_path:
        _load_account_aliases(registry, accounts_path)
    if article_library_path:
        _load_article_aliases(registry, article_library_path, name_to_email, registry["local_keywords"])
    return _finalize_registry(registry)


def _candidate_names_from_record(record):
    candidates = []
    for field in AUTHOR_FIELD_CANDIDATES:
        value = record.get(field, "")
        for name in split_author_names(value):
            candidates.append((field, name))
    return candidates


def _affiliation_evidence(record, registry):
    evidence = []
    keywords = registry.get("local_keywords") or LOCAL_AFFILIATION_KEYWORDS
    for field in AFFILIATION_FIELD_CANDIDATES:
        value = record.get(field, "")
        if value and is_local_affiliation(value, keywords):
            evidence.append(f"{field}命中本校单位关键词")
    return evidence


def match_local_scholar(record: dict, alias_registry: dict | None = None) -> dict:
    registry = alias_registry or {"aliases": {}, "local_keywords": LOCAL_AFFILIATION_KEYWORDS.copy()}
    aliases = registry.get("aliases", {})
    affiliation_notes = _affiliation_evidence(record, registry)

    for field, raw_name in _candidate_names_from_record(record):
        key = normalize_name(raw_name)
        if not key:
            continue
        entry = aliases.get(key)
        if not entry:
            continue
        if entry.get("conflicts"):
            sources = entry.get("sources") or []
            if any(str(source).startswith("正式别名表") for source in sources):
                basis = "正式别名表中该别名对应多个学者/邮箱，需人工确认"
            else:
                conflict_names = [entry.get("real_name", "")]
                conflict_names.extend(conflict.get("real_name", "") for conflict in entry.get("conflicts", []))
                conflict_names = [name for name in conflict_names if name]
                basis = f"{field}命中别名 `{raw_name}`，但该别名对应多个学者：{'、'.join(conflict_names[:5])}；别名冲突，需人工确认"
            return {
                "matched": False,
                "conflict": True,
                "raw_name": raw_name,
                "alias": key,
                "real_name": "",
                "email": "",
                "basis": basis,
                "affiliation_evidence": "；".join(affiliation_notes),
            }
        sources = "、".join(entry.get("sources") or ["别名表"])
        real_name = entry.get("real_name") or raw_name
        email = entry.get("email", "")
        if any(str(source).startswith("正式别名表") for source in entry.get("sources", [])):
            basis = f"命中正式别名表: {raw_name} -> {real_name}"
        else:
            basis = f"{field}命中别名 `{raw_name}`；来源={sources}"
        if affiliation_notes:
            basis += "；" + "；".join(affiliation_notes)
        return {
            "matched": True,
            "raw_name": raw_name,
            "alias": key,
            "real_name": real_name,
            "email": email,
            "basis": basis,
            "affiliation_evidence": "；".join(affiliation_notes),
        }

    basis = "未匹配到本校学者别名/邮箱"
    if affiliation_notes:
        basis += "；" + "；".join(affiliation_notes)
    return {
        "matched": False,
        "conflict": False,
        "raw_name": "",
        "alias": "",
        "real_name": "",
        "email": "",
        "basis": basis,
        "affiliation_evidence": "；".join(affiliation_notes),
    }


def infer_record_scope(record: dict, mode: str, alias_registry: dict | None = None) -> dict:
    normalized_mode = "external" if mode in {"external", "校外", "非本校成果", "校外成果"} else "local"
    match = match_local_scholar(record, alias_registry)

    if normalized_mode == "local":
        basis = "用户选择本校成果模式；数据通常来自三大数据库前台本校检索下载"
        if match.get("affiliation_evidence"):
            basis += "；" + match["affiliation_evidence"]
        return {
            "数据归属": "本校",
            "归属依据": basis,
            "本校学者匹配": match["real_name"] if match["matched"] else "",
            "本校学者邮箱": match["email"] if match["matched"] else "",
            "学者匹配依据": match["basis"] if match["matched"] else "本校成果模式未强制匹配本校学者邮箱",
        }

    basis = "用户选择校外成果模式；数据通常来自本校学者 Author ID/API 采集"
    if match.get("affiliation_evidence"):
        basis += "；" + match["affiliation_evidence"]
    if match.get("conflict"):
        return {
            "数据归属": "校外",
            "归属依据": basis,
            "本校学者匹配": "待确认",
            "本校学者邮箱": "",
            "学者匹配依据": match["basis"],
        }
    if not match["matched"]:
        return {
            "数据归属": "校外",
            "归属依据": basis,
            "本校学者匹配": "待确认",
            "本校学者邮箱": "",
            "学者匹配依据": "校外成果模式但未匹配到本校学者别名/邮箱，需人工确认",
        }
    if not match["email"]:
        return {
            "数据归属": "校外",
            "归属依据": basis,
            "本校学者匹配": match["real_name"],
            "本校学者邮箱": "",
            "学者匹配依据": match["basis"] + "；未找到邮箱，需补邮箱",
        }
    return {
        "数据归属": "校外",
        "归属依据": basis,
        "本校学者匹配": match["real_name"],
        "本校学者邮箱": match["email"],
        "学者匹配依据": match["basis"],
    }


def apply_scope_fields(df: pd.DataFrame, mode: str, alias_registry: dict | None = None) -> pd.DataFrame:
    df = df.copy()
    for col in [CLAIM_COLUMN, *SCOPE_COLUMNS]:
        if col not in df.columns:
            df[col] = ""

    for idx, row in df.iterrows():
        record = row.to_dict()
        scope = infer_record_scope(record, mode, alias_registry)
        for col, value in scope.items():
            df.at[idx, col] = value
        if mode == "external":
            existing_claim = str(df.at[idx, CLAIM_COLUMN] or "").strip()
            aligned_claim = build_author_claim_value(record, alias_registry, existing_claim)
            if scope.get("本校学者邮箱"):
                aligned_claim = merge_claim_email(aligned_claim, scope["本校学者邮箱"])
            df.at[idx, CLAIM_COLUMN] = aligned_claim
    return order_output_columns(df)


def build_author_claim_value(record: dict, alias_registry: dict | None, existing_claim: str = "") -> str:
    names = split_author_names(record.get("作者", ""))
    if not names:
        return str(existing_claim or "").strip()

    existing_parts = [part.strip() for part in re.split(r"[;；]", str(existing_claim or "")) if part.strip()]
    if len(existing_parts) == len(names):
        claim_parts = [
            part if part.lower() == "unknown" or is_claimable_email(part) else "unknown"
            for part in existing_parts
        ]
    else:
        claim_parts = ["unknown"] * len(names)

    aliases = (alias_registry or {}).get("aliases", {})
    for idx, name in enumerate(names):
        entry = aliases.get(normalize_name(name))
        if not entry or entry.get("conflicts"):
            continue
        email = str(entry.get("email", "") or "").strip()
        if is_claimable_email(email) and (not claim_parts[idx] or claim_parts[idx].lower() == "unknown"):
            claim_parts[idx] = email

    return ";".join(claim_parts)


def merge_claim_email(existing_claim: str, email: str) -> str:
    email = str(email or "").strip()
    existing_claim = str(existing_claim or "").strip()
    if not is_claimable_email(email):
        return existing_claim
    if not existing_claim or existing_claim.lower() in {"nan", "unknown"}:
        return email
    parts = [part.strip() for part in re.split(r"[;；]", existing_claim) if part.strip()]
    if any(part.lower() == email.lower() for part in parts):
        return existing_claim
    for idx, part in enumerate(parts):
        if part.lower() == "unknown":
            parts[idx] = email
            return ";".join(parts)
    return existing_claim



def order_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in [CLAIM_COLUMN, *SCOPE_COLUMNS]:
        if col not in df.columns:
            df[col] = ""
    front = [col for col in PREFERRED_FRONT_COLUMNS if col in df.columns]
    rest = [col for col in df.columns if col not in front]
    return df[front + rest]


def is_conference_record(row) -> bool:
    doc_type = str(row.get("原始文献类型", "") or "").strip().lower()
    journal = str(row.get("发表期刊", "") or "").strip().lower()
    text = f"{doc_type} {journal}"
    conference_markers = [
        "conference",
        "proceeding",
        "proceedings",
        "meeting",
        "symposium",
        "workshop",
        "会议",
        "ca)",
    ]
    return any(marker in text for marker in conference_markers)


def is_review_record(row) -> bool:
    doc_type = str(row.get("原始文献类型", "") or "").strip().lower()
    return "review" in doc_type or "综述" in doc_type


def split_output_frames(df: pd.DataFrame) -> dict:
    for col in [CLAIM_COLUMN, *SCOPE_COLUMNS]:
        if col not in df.columns:
            df[col] = ""
    email = df["本校学者邮箱"].fillna("").astype(str).str.strip()
    matched = df["本校学者匹配"].fillna("").astype(str).str.strip()
    local_df = df[df["数据归属"] == "本校"]
    external_ready_df = df[(df["数据归属"] == "校外") & (email != "")]
    needs_email_df = df[(df["数据归属"] == "校外") & (email == "") & (matched != "") & (matched != "待确认")]
    pending_df = df[(df["数据归属"] == "校外") & ((email == "") | (matched == "待确认"))]
    review_mask = df.apply(is_review_record, axis=1)
    conference_mask = df.apply(is_conference_record, axis=1) & ~review_mask
    conference_df = df[conference_mask]
    review_df = df[review_mask]
    journal_df = df[~conference_mask & ~review_mask]
    return {
        "全部数据": df,
        "期刊论文": journal_df,
        "会议论文": conference_df,
        "综述论文": review_df,
        "本校成果": local_df,
        "校外成果": external_ready_df,
        "待确认": pending_df,
        "需补邮箱": needs_email_df,
    }


def write_multi_sheet_excel(df: pd.DataFrame, output_file: str):
    output_path = Path(output_file)
    if output_path.parent and str(output_path.parent) != ".":
        output_path.parent.mkdir(parents=True, exist_ok=True)
    frames = split_output_frames(df)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return {name: len(frame) for name, frame in frames.items()}
