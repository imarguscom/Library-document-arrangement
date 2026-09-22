import pandas as pd
import sys
import re
import urllib.parse
import xml.etree.ElementTree as ET
from time import sleep

import requests

from metadata_completion import (
    EVIDENCE_COLUMN,
    complete_ei_record,
    complete_scopus_record,
    complete_wos_record,
    unique_author,
)

from claim_mapping import build_publication_name_to_email, normalize_name
from scope_rules import (
    SCOPE_COLUMNS,
    apply_scope_fields,
    build_scholar_alias_registry,
    document_type_group,
    filter_alias_registry_by_emails,
    filter_publication_name_to_email_by_emails,
    parse_claim_email_filter,
    write_multi_sheet_excel,
)

TARGET_COLUMNS = [
    "题名", "其他题名", "作者", "第一作者单位", "通讯作者单位", "发表日期", "发表期刊",
    "ISSN", "EISSN", "卷号", "期号", "页码", "产权排序", "摘要", "其他摘要",
    "关键词", "学科领域", "学科门类", "DOI", "URL", "收录类别", "语种", "资助项目",
    "WOS研究方向", "WOS类目", "WOS记录号", "CSCD记录号", "出版者", "EI入藏号",
    "EI主题词", "EI分类号", "原始文献类型", "文献类型审核原因", "发表状态", "字数", "CN", "卷/期/页",
    "参考文献", "通讯作者", "通讯作者来源", "通讯作者单位来源", "通讯作者—单位关联冲突原因", "来源库", "SCOPUS_ID", "Scopus学科分类", "SCOPUSEID",
    "页数", "CNKI学科分类", "网络首发", "中图分类号", "作者单位", "第一作者",
    "作者—单位关联来源", "作者—单位关联冲突原因",
    "已认领作者", "Scopus被引次数", "SCI被引次数", "CSCD被引次数", "影响因子",
    "5年平均影响因子", "所属专题", "发文作者类型", EVIDENCE_COLUMN
]

CLAIM_COLUMN = "作品认领"
CLAIM_SOURCE_COLUMNS = [CLAIM_COLUMN, "已认领作者", "注册邮箱", "邮箱", "学者邮箱", "认领邮箱"]
AUTHOR_TYPE_COLUMNS = ["发文作者类型", "作者类型"]
DEFAULT_DATE_SUFFIX = "-01-01"
EXCEL_CELL_CHAR_LIMIT = 32767

# Internal relationship bundles keep the author, affiliation, and
# corresponding-author fields atomic while DOI records are being merged.
AUTHOR_RELATIONS_KEY = "_author_affiliation_relations"
CORRESPONDENCE_RELATIONS_KEY = "_correspondence_relations"
AUTHOR_RELATION_SOURCE_COLUMN = "作者—单位关联来源"
AUTHOR_RELATION_CONFLICT_COLUMN = "作者—单位关联冲突原因"
CORRESPONDENCE_NAME_SOURCE_COLUMN = "通讯作者来源"
CORRESPONDENCE_AFFILIATION_SOURCE_COLUMN = "通讯作者单位来源"
CORRESPONDENCE_CONFLICT_COLUMN = "通讯作者—单位关联冲突原因"

AUTHOR_RELATION_OUTPUT_FIELDS = {
    "作者", "作者单位", "第一作者", "第一作者单位",
    AUTHOR_RELATION_SOURCE_COLUMN, AUTHOR_RELATION_CONFLICT_COLUMN,
}
CORRESPONDENCE_OUTPUT_FIELDS = {
    "通讯作者", "通讯作者单位", CORRESPONDENCE_NAME_SOURCE_COLUMN,
    CORRESPONDENCE_AFFILIATION_SOURCE_COLUMN, CORRESPONDENCE_CONFLICT_COLUMN,
}


LANG_MAP = {
    "english": "英语",
    "chinese": "中文",
    "german": "德语",
    "french": "法语",
    "spanish": "西班牙语",
    "japanese": "日语",
    "russian": "俄语",
    "korean": "韩语",
    "italian": "意大利语",
    "portuguese": "葡萄牙语",
    "polish": "波兰语",
    "dutch": "荷兰语",
    "arabic": "阿拉伯语"
}

# ================= 工具函数 =================

def normalize_doi(doi):
    if pd.isna(doi):
        return None
    d = str(doi)
    d = d.replace("\u00a0", " ")
    d = re.sub(r"\s+", "", d)
    d = d.strip().lower()
    d = d.replace("doi:", "")
    d = d.replace("http://dx.doi.org/", "").replace("https://doi.org/", "")
    d = d.strip()
    return d if d else None

def clean_name_keep_full(name_str):
    if pd.isna(name_str):
        return ""
    return normalize_author_display_name(name_str)

def normalize_author_display_name(name_str):
    if pd.isna(name_str):
        return ""
    text = str(name_str).replace("\u00a0", " ")
    text = text.replace("，", ",")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\([\d,\s]+\)\s*$", "", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text.strip(" ;；")

def author_match_parts(name_str):
    text = normalize_author_display_name(name_str)
    if not text:
        return "", ""
    if "," in text:
        last, given = text.split(",", 1)
    else:
        tokens = text.split()
        last = tokens[-1] if tokens else text
        given = " ".join(tokens[:-1])
    last_key = re.sub(r"[^a-z0-9]", "", last.lower())
    given_tokens = re.findall(r"[A-Za-z0-9]+", given)
    initials = []
    for token in given_tokens:
        if token.isupper() and len(token) <= 4:
            initials.append(token.lower())
        else:
            initials.append(token[:1].lower())
    return last_key, "".join(initials)

def normalize_author_match_key(name_str):
    last_key, initials = author_match_parts(name_str)
    if not last_key:
        return ""
    return f"{last_key}|{initials}"

def normalize_author_last_key(name_str):
    return author_match_parts(name_str)[0]

def normalize_date(d1, d2=""):
    """将各种日期统一为 YYYY-MM-DD"""
    s = f"{d1} {d2}".strip()
    if not s or s.lower() in ['nan', 'none', '']:
        return ""
    try:
        dt = pd.to_datetime(s, errors='coerce')
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    
    m = re.search(r'(19\d{2}|20\d{2})', s)
    if m:
        return f"{m.group(1)}-01-01"
    return ""

def translate_language(lang_str):
    """标准化语种为中文"""
    if not lang_str or pd.isna(lang_str):
        return ""
    s = str(lang_str).strip().lower()
    for eng, chn in LANG_MAP.items():
        if eng in s:
            return chn
    return str(lang_str).strip()

def normalize_keywords(keyword_text):
    if pd.isna(keyword_text):
        return ""
    text = str(keyword_text).strip()
    if not text or text.lower() == "nan":
        return ""
    parts = [part.strip() for part in re.split(r"\s*(?:\||;|；|\n|\r)\s*", text) if part.strip()]
    return "; ".join(parts)

def normalize_wos_index(index_text):
    text = str(index_text or "").strip()
    if not text or text.lower() == "nan":
        return ""
    mappings = [
        ("SCI-EXPANDED", "SCIE"),
        ("SCIENCE CITATION INDEX EXPANDED", "SCIE"),
        ("CONFERENCE PROCEEDINGS CITATION INDEX - SCIENCE", "CPCI-S"),
        ("CONFERENCE PROCEEDINGS CITATION INDEX-SCIENCE", "CPCI-S"),
        ("CPCI-S", "CPCI-S"),
        ("SOCIAL SCIENCES CITATION INDEX", "SSCI"),
        ("SSCI", "SSCI"),
        ("ARTS & HUMANITIES CITATION INDEX", "AHCI"),
        ("ARTS AND HUMANITIES CITATION INDEX", "AHCI"),
        ("A&HCI", "AHCI"),
        ("AHCI", "AHCI"),
        ("EMERGING SOURCES CITATION INDEX", "ESCI"),
        ("ESCI", "ESCI"),
        ("BOOK CITATION INDEX", "BKCI"),
        ("BKCI", "BKCI"),
    ]
    upper = text.upper()
    values = []
    for marker, normalized in mappings:
        if marker in upper and normalized not in values:
            values.append(normalized)
    return "; ".join(values) if values else text

def normalize_publication_status(status_text):
    text = str(status_text or "").strip()
    if not text or text.lower() == "nan":
        return "已发表"
    lower = text.lower()
    online_markers = ["article in press", "in press", "online", "early access", "网络首发", "在线"]
    if any(marker in lower for marker in online_markers):
        return "在线发表"
    return "已发表"

def parse_scopus_affiliations(aff_str):
    if pd.isna(aff_str) or not str(aff_str).strip():
        return {}, []
    aff_list = [a.strip() for a in str(aff_str).split(";") if a.strip()]
    aff_dict = {}
    master_list = []
    for aff in aff_list:
        if aff in aff_dict:
            continue
        aff_dict[aff] = len(master_list) + 1
        master_list.append(aff)
    return aff_dict, master_list

def match_author_affiliations(auth_entry, aff_dict, master_aff_list):
    indices = []
    for aff_name in master_aff_list:
        if aff_name in auth_entry:
            indices.append(aff_dict[aff_name])
    return sorted(list(set(indices)))

def split_scopus_author_affiliation_entries(auth_with_aff_str):
    if pd.isna(auth_with_aff_str):
        return []
    text = str(auth_with_aff_str).strip()
    if not text or text.lower() == "nan":
        return []
    entries = []
    current = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char in ";；" and depth == 0:
            entry = "".join(current).strip()
            if entry:
                entries.append(entry)
            current = []
            continue
        current.append(char)
    entry = "".join(current).strip()
    if entry:
        entries.append(entry)
    return entries

def affiliations_from_scopus_author_entry(entry):
    entry = str(entry or "").strip()
    if not entry:
        return []
    match = re.match(r"^.+?\((.*)\)\s*$", entry)
    if match:
        return split_semicolon_values(match.group(1))
    parts = entry.split(",", 1)
    return [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []


def scopus_author_entry_name(entry):
    """Extract the abbreviated author name from one Scopus affiliation entry."""
    text = str(entry or "").strip()
    if not text:
        return ""
    if "(" in text:
        return text.split("(", 1)[0].strip(" ,;")
    return text.split(",", 1)[0].strip()


def scopus_author_name_parts(name):
    """Return a conservative (surname, initials) key for Scopus name variants."""
    text = normalize_author_display_name(name)
    if not text:
        return "", ""
    if "," in text:
        surname, given = text.split(",", 1)
        surname_tokens = re.findall(r"[A-Za-z0-9]+", surname.lower())
        given_tokens = re.findall(r"[A-Za-z0-9]+", given)
    else:
        tokens = re.findall(r"[A-Za-z0-9]+", text)
        if len(tokens) < 2:
            return (tokens[0].lower(), "") if tokens else ("", "")
        # Scopus affiliation entries are normally "Surname I.".  The
        # correspondence-address variant can instead be "I. Surname".
        if len(tokens[0]) == 1:
            surname_tokens = [tokens[-1].lower()]
            given_tokens = tokens[:-1]
        else:
            surname_tokens = [tokens[0].lower()]
            given_tokens = tokens[1:]
    surname_key = "".join(surname_tokens)
    initials = "".join(
        token.lower() if token.isupper() and len(token) <= 4 else token[0].lower()
        for token in given_tokens if token
    )
    return surname_key, initials


def scopus_author_names_match(left, right):
    """Match only same-record Scopus names with the same surname and initials."""
    left_surname, left_initials = scopus_author_name_parts(left)
    right_surname, right_initials = scopus_author_name_parts(right)
    return bool(
        left_surname
        and right_surname
        and left_initials
        and right_initials
        and left_surname == right_surname
        and left_initials == right_initials
    )


def scopus_corresponding_author_affiliations(corresponding_authors, auth_entries, aff_dict, master_aff_list):
    """Resolve a corresponding author's units only when every match is unique.

    Scopus front-end exports can give Corresponding Author without
    Correspondence Address, while Authors with affiliations still contains
    author-level affiliations.  We reuse that same-record evidence and never
    choose between duplicate surname/initial candidates.
    """
    author_names = split_semicolon_values(corresponding_authors)
    if not author_names or not auth_entries:
        return ""

    resolved_affiliations = []
    for author_name in author_names:
        candidates = [
            entry for entry in auth_entries
            if scopus_author_names_match(author_name, scopus_author_entry_name(entry))
        ]
        if len(candidates) != 1:
            return ""

        entry = candidates[0]
        indices = match_author_affiliations(entry, aff_dict, master_aff_list)
        affiliations = [aff for aff, idx in aff_dict.items() if idx in indices]
        if not affiliations:
            affiliations = affiliations_from_scopus_author_entry(entry)
        if not affiliations:
            return ""
        for affiliation in affiliations:
            if affiliation not in resolved_affiliations:
                resolved_affiliations.append(affiliation)

    return "; ".join(resolved_affiliations)


def extract_scopus_affiliations_from_authors(auth_with_aff_str):
    affiliations = []
    for entry in split_scopus_author_affiliation_entries(auth_with_aff_str):
        for aff in affiliations_from_scopus_author_entry(entry):
            if aff and aff not in affiliations:
                affiliations.append(aff)
    return affiliations

def format_indexed_affiliations(affiliations):
    clean_affiliations = []
    for aff in affiliations:
        aff = re.sub(r"^(?:\(\d+\)|\d+[\).])\s*", "", str(aff)).strip(" ;；")
        if aff and aff not in clean_affiliations:
            clean_affiliations.append(aff)
    return "; ".join([f"({idx}) {aff}" for idx, aff in enumerate(clean_affiliations, start=1)])

def match_full_author_name(short_name, full_names):
    matched_name, _ = resolve_full_author_name(short_name, full_names)
    return matched_name


def build_scopus_author_bundle(full_names, auth_entries, master_affiliations):
    """Build relations by author identity, never by the two export positions."""
    entry_rows = [
        {
            "name": scopus_author_entry_name(entry),
            "affiliations": affiliations_from_scopus_author_entry(entry),
        }
        for entry in auth_entries
    ]
    relations = []
    conflicts = []
    for name in full_names:
        candidates = [
            entry for entry in entry_rows
            if scopus_author_names_match(name, entry["name"])
        ]
        if len(candidates) == 1:
            relations.append({"name": name, "affiliations": candidates[0]["affiliations"]})
        else:
            relations.append({"name": name, "affiliations": []})
            if auth_entries:
                kind = "不唯一" if len(candidates) > 1 else "无法匹配"
                conflicts.append(f"Scopus 作者—单位条目{kind}：{name}")
    return _make_author_bundle(
        relations,
        master_affiliations,
        "SCOPUS",
        "Authors with affiliations",
        conflicts,
        marker_space=False,
    )


def parse_scopus_correspondence_relations(corr_str, full_names):
    """Parse a correspondence address into verified author--affiliation pairs."""
    if not corr_str:
        return [], []
    segments = [part.strip() for part in str(corr_str).split(";") if part.strip()]
    relations = []
    conflicts = []
    current_author = ""
    current_affiliations = []

    def flush_current():
        if not current_author:
            return
        author, reason = resolve_full_author_name(current_author, full_names)
        if author:
            relations.append({"name": author, "affiliations": current_affiliations})
        elif reason:
            conflicts.append(reason)

    for segment in segments:
        if "email:" in segment.lower() or "@" in segment:
            flush_current()
            current_author = ""
            current_affiliations = []
        elif not current_author:
            current_author = segment
        else:
            current_affiliations.append(segment)
    flush_current()
    return relations, _unique_values(conflicts)


def parse_scopus_correspondence(corr_str, full_names):
    relations, _ = parse_scopus_correspondence_relations(corr_str, full_names)
    return (
        "; ".join(_unique_values(relation["name"] for relation in relations)),
        "; ".join(_unique_values(
            affiliation for relation in relations for affiliation in relation.get("affiliations", [])
        )),
    )

def safe_get(row, keys):
    """尝试从 row 中获取 keys 列表中第一个存在且非空的值，支持列名大小写不敏感匹配"""
    for k in keys:
        if k in row.index:
            val = row[k]
            if pd.notna(val) and str(val).strip().lower() not in ['nan', '']:
                return str(val).strip()
        for col in row.index:
            if str(col).strip().lower() == str(k).lower():
                val = row[col]
                if pd.notna(val) and str(val).strip().lower() not in ['nan', '']:
                    return str(val).strip()
    return ""

def split_semicolon_values(value):
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [x.strip() for x in re.split(r"[;；]", text) if x.strip()]


def _unique_values(values):
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _clean_affiliation(affiliation):
    return re.sub(r"^(?:\(\d+\)|\d+[\).])\s*", "", str(affiliation or "")).strip(" ;；")


def _affiliation_key(affiliation):
    return re.sub(r"[^a-z0-9]", "", _clean_affiliation(affiliation).lower())


def _author_identity_key(name):
    surname, initials = scopus_author_name_parts(name)
    return f"{surname}|{initials}" if surname and initials else ""


def resolve_full_author_name(candidate, full_names):
    """Resolve a source name only when it identifies one listed author.

    A surname-only fallback silently turns ``Li, M.`` into the first ``Li`` in
    an export.  Exact display names are accepted; every abbreviation must have
    a unique surname-and-initials match instead.
    """
    candidate = normalize_author_display_name(candidate)
    if not candidate:
        return "", ""
    normalized = candidate.casefold()
    exact_matches = [
        name for name in full_names
        if normalize_author_display_name(name).casefold() == normalized
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], ""
    if len(exact_matches) > 1:
        return "", f"通讯作者姓名精确匹配不唯一：{candidate}"

    key = _author_identity_key(candidate)
    matches = [name for name in full_names if key and _author_identity_key(name) == key]
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return "", f"通讯作者姓名缩写匹配不唯一：{candidate}"
    return "", f"通讯作者姓名无法匹配作者列表：{candidate}"


def _make_author_bundle(
    relations,
    affiliations,
    source,
    evidence="",
    conflicts=None,
    marker_space=False,
    unlinked_affiliations=None,
    index_affiliations=True,
):
    clean_relations = []
    for relation in relations or []:
        name = normalize_author_display_name(relation.get("name", ""))
        if not name:
            continue
        clean_relations.append({
            "name": name,
            "affiliations": _unique_values(
                _clean_affiliation(affiliation)
                for affiliation in relation.get("affiliations", [])
                if _clean_affiliation(affiliation)
            ),
        })
    clean_affiliations = _unique_values(
        _clean_affiliation(affiliation) for affiliation in affiliations or [] if _clean_affiliation(affiliation)
    )
    for relation in clean_relations:
        clean_affiliations = _unique_values([*clean_affiliations, *relation["affiliations"]])
    return {
        "relations": clean_relations,
        "affiliations": clean_affiliations,
        "unlinked_affiliations": _unique_values(
            _clean_affiliation(affiliation)
            for affiliation in unlinked_affiliations or []
            if _clean_affiliation(affiliation)
        ),
        "source": str(source or ""),
        "evidence": str(evidence or ""),
        "conflicts": _unique_values(conflicts or []),
        "marker_space": bool(marker_space),
        "index_affiliations": bool(index_affiliations),
    }


def _render_author_bundle(bundle):
    affiliations = _unique_values(bundle.get("affiliations", []))
    index_by_affiliation = {
        _affiliation_key(affiliation): index
        for index, affiliation in enumerate(affiliations, start=1)
        if _affiliation_key(affiliation)
    }
    rendered_authors = []
    first_author = ""
    first_author_affiliations = ""
    for position, relation in enumerate(bundle.get("relations", [])):
        name = relation["name"]
        indices = _unique_values(
            str(index_by_affiliation.get(_affiliation_key(affiliation), ""))
            for affiliation in relation.get("affiliations", [])
            if index_by_affiliation.get(_affiliation_key(affiliation))
        )
        if indices:
            separator = " " if bundle.get("marker_space") else ""
            rendered_authors.append(f"{name}{separator}({','.join(indices)})")
        else:
            rendered_authors.append(name)
        if position == 0:
            first_author = name
            first_author_affiliations = "; ".join(
                _unique_values(relation.get("affiliations", []))
            )
    return {
        "作者": "; ".join(rendered_authors),
        "作者单位": "; ".join(
            [
                format_indexed_affiliations(affiliations)
                if bundle.get("index_affiliations", True)
                else "; ".join(affiliations),
                *bundle.get("unlinked_affiliations", []),
            ]
        ).strip(" ;"),
        "第一作者": first_author,
        "第一作者单位": first_author_affiliations,
        AUTHOR_RELATION_SOURCE_COLUMN: bundle.get("source", ""),
        AUTHOR_RELATION_CONFLICT_COLUMN: "；".join(bundle.get("conflicts", [])),
    }


def apply_author_bundle(record, bundle):
    record.update(_render_author_bundle(bundle))
    record[AUTHOR_RELATIONS_KEY] = bundle
    return record


def _author_bundle_from_record(record):
    stored = record.get(AUTHOR_RELATIONS_KEY)
    if isinstance(stored, dict):
        return stored

    affiliation_by_index = {}
    all_affiliations = []
    unlinked_affiliations = []
    index_affiliations = False
    for affiliation in split_semicolon_values(record.get("作者单位", "")):
        match = re.match(r"^\((\d+)\)\s*(.*)$", affiliation)
        if match:
            index_affiliations = True
            affiliation_by_index[match.group(1)] = _clean_affiliation(match.group(2))
            all_affiliations.append(_clean_affiliation(match.group(2)))
        else:
            unlinked_affiliations.append(_clean_affiliation(affiliation))

    relations = []
    marker_space = False
    for raw_author in split_semicolon_values(record.get("作者", "")):
        match = re.match(r"^(.*?)\s*(\((?:\d+(?:,\d+)*)\))\s*$", raw_author)
        if match:
            marker_space = marker_space or bool(re.search(r"\s\(", raw_author))
            indices = re.findall(r"\d+", match.group(2))
            relations.append({
                "name": match.group(1).strip(),
                "affiliations": [affiliation_by_index[index] for index in indices if index in affiliation_by_index],
            })
        else:
            relations.append({"name": raw_author, "affiliations": []})
    return _make_author_bundle(
        relations,
        all_affiliations,
        record.get(AUTHOR_RELATION_SOURCE_COLUMN) or record.get("来源库", ""),
        conflicts=split_semicolon_values(record.get(AUTHOR_RELATION_CONFLICT_COLUMN, "")),
        marker_space=marker_space,
        unlinked_affiliations=unlinked_affiliations,
        index_affiliations=index_affiliations,
    )


def _source_priority(source):
    sources = str(source or "").upper()
    if "SCOPUS" in sources:
        return 3
    if "WOS" in sources:
        return 2
    if "EI" in sources:
        return 1
    return 0


def _author_bundle_score(bundle):
    relations = bundle.get("relations", [])
    linked = [relation for relation in relations if relation.get("affiliations")]
    coverage = len(linked) / len(relations) if relations else 0
    return (
        coverage,
        len(linked),
        sum(len(relation.get("affiliations", [])) for relation in linked),
        len(relations),
        _source_priority(bundle.get("source")),
    )


def _author_bundle_signature(bundle):
    return {
        _author_identity_key(relation["name"]): tuple(sorted(_affiliation_key(affiliation) for affiliation in relation.get("affiliations", []) if _affiliation_key(affiliation)))
        for relation in bundle.get("relations", [])
        if _author_identity_key(relation["name"]) and relation.get("affiliations")
    }


def merge_author_bundles(existing_bundle, new_bundle):
    existing_signature = _author_bundle_signature(existing_bundle)
    new_signature = _author_bundle_signature(new_bundle)
    conflict_messages = _unique_values([
        *existing_bundle.get("conflicts", []), *new_bundle.get("conflicts", []),
    ])
    if (
        existing_signature
        and new_signature
        and existing_bundle.get("source") != new_bundle.get("source")
        and existing_signature != new_signature
    ):
        conflict_messages.append(
            f"跨来源作者—单位关系不一致或单位文本无法确认等价：{existing_bundle.get('source')} vs {new_bundle.get('source')}"
        )
    selected = new_bundle if _author_bundle_score(new_bundle) > _author_bundle_score(existing_bundle) else existing_bundle
    selected = dict(selected)
    selected["conflicts"] = _unique_values(conflict_messages)
    return selected


def _make_correspondence_bundle(relations, source, name_source="", affiliation_source="", conflicts=None, raw_name="", raw_affiliations=""):
    clean_relations = []
    for relation in relations or []:
        name = normalize_author_display_name(relation.get("name", ""))
        if not name:
            continue
        clean_relations.append({
            "name": name,
            "affiliations": _unique_values(
                _clean_affiliation(affiliation)
                for affiliation in relation.get("affiliations", [])
                if _clean_affiliation(affiliation)
            ),
        })
    return {
        "relations": clean_relations,
        "source": str(source or ""),
        "name_source": str(name_source or source or ""),
        "affiliation_source": str(affiliation_source or source or ""),
        "conflicts": _unique_values(conflicts or []),
        "raw_name": str(raw_name or "").strip(),
        "raw_affiliations": str(raw_affiliations or "").strip(),
    }


def _render_correspondence_bundle(bundle):
    relations = bundle.get("relations", [])
    names = _unique_values(relation["name"] for relation in relations)
    affiliations = _unique_values(
        affiliation for relation in relations for affiliation in relation.get("affiliations", [])
    )
    return {
        "通讯作者": "; ".join(names) or bundle.get("raw_name", ""),
        "通讯作者单位": "; ".join(affiliations) or bundle.get("raw_affiliations", ""),
        CORRESPONDENCE_NAME_SOURCE_COLUMN: bundle.get("name_source", ""),
        CORRESPONDENCE_AFFILIATION_SOURCE_COLUMN: bundle.get("affiliation_source", ""),
        CORRESPONDENCE_CONFLICT_COLUMN: "；".join(bundle.get("conflicts", [])),
    }


def apply_correspondence_bundle(record, bundle):
    record.update(_render_correspondence_bundle(bundle))
    record[CORRESPONDENCE_RELATIONS_KEY] = bundle
    return record


def _correspondence_bundle_from_record(record):
    stored = record.get(CORRESPONDENCE_RELATIONS_KEY)
    if isinstance(stored, dict):
        return stored
    name = str(record.get("通讯作者", "") or "").strip()
    affiliations = split_semicolon_values(record.get("通讯作者单位", ""))
    relations = [{"name": name, "affiliations": affiliations}] if name else []
    source = record.get("来源库", "")
    return _make_correspondence_bundle(
        relations,
        source,
        record.get(CORRESPONDENCE_NAME_SOURCE_COLUMN) or source,
        record.get(CORRESPONDENCE_AFFILIATION_SOURCE_COLUMN) or source,
        split_semicolon_values(record.get(CORRESPONDENCE_CONFLICT_COLUMN, "")),
        raw_name=name,
        raw_affiliations=record.get("通讯作者单位", ""),
    )


def _correspondence_bundle_score(bundle):
    complete = [relation for relation in bundle.get("relations", []) if relation.get("affiliations")]
    return len(complete), len(bundle.get("relations", [])), _source_priority(bundle.get("source"))


def _correspondence_signature(bundle):
    return {
        _author_identity_key(relation["name"]): tuple(sorted(_affiliation_key(affiliation) for affiliation in relation.get("affiliations", []) if _affiliation_key(affiliation)))
        for relation in bundle.get("relations", [])
        if _author_identity_key(relation["name"]) and relation.get("affiliations")
    }


def merge_correspondence_bundles(existing_bundle, new_bundle):
    existing_signature = _correspondence_signature(existing_bundle)
    new_signature = _correspondence_signature(new_bundle)
    conflict_messages = _unique_values([
        *existing_bundle.get("conflicts", []), *new_bundle.get("conflicts", []),
    ])
    if (
        existing_signature
        and new_signature
        and existing_bundle.get("source") != new_bundle.get("source")
        and existing_signature != new_signature
    ):
        conflict_messages.append(
            f"跨来源通讯作者—单位关系不一致或单位文本无法确认等价：{existing_bundle.get('source')} vs {new_bundle.get('source')}"
        )
    selected = new_bundle if _correspondence_bundle_score(new_bundle) > _correspondence_bundle_score(existing_bundle) else existing_bundle
    selected = dict(selected)
    selected["conflicts"] = _unique_values(conflict_messages)
    return selected

def count_authors(author_text):
    authors = split_semicolon_values(author_text)
    return len(authors)

def author_names(author_text):
    names = []
    if pd.isna(author_text):
        return names
    author_text = str(author_text)[:EXCEL_CELL_CHAR_LIMIT]
    for author in split_semicolon_values(author_text):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", author).strip()
        if name:
            names.append(name)
    return names

def is_local_author_type(value):
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    non_local_words = ["非本校", "外单位", "校外", "外校", "unknown"]
    if any(word in text for word in non_local_words):
        return False
    local_words = ["本校", "校内", "本单位", "本院", "本机构"]
    if any(word in text for word in local_words):
        return True
    return None

def first_nonempty(row_or_record, keys):
    for key in keys:
        if isinstance(row_or_record, dict):
            val = row_or_record.get(key, "")
        else:
            val = safe_get(row_or_record, [key])
        if pd.notna(val) and str(val).strip().lower() not in ["", "nan"]:
            return str(val).strip()
    return ""

def copy_claim_inputs(record, row):
    for col in [CLAIM_COLUMN, "已认领作者", "发文作者类型", "注册邮箱", "邮箱", "学者邮箱", "认领邮箱", "作者类型"]:
        val = safe_get(row, [col])
        if val and not record.get(col):
            record[col] = val
    return record

def build_claim_value(record, publication_name_to_email=None):
    existing_claim = first_nonempty(record, [CLAIM_COLUMN])
    if existing_claim:
        return existing_claim

    names = author_names(record.get("作者", ""))
    author_count = len(names)
    if author_count == 0:
        return ""

    if publication_name_to_email:
        result = []
        for name in names:
            email = publication_name_to_email.get(normalize_name(name), "")
            result.append(email if email else "unknown")
        return ";".join(result)

    claim_values = split_semicolon_values(first_nonempty(record, CLAIM_SOURCE_COLUMNS[1:]))
    author_types = split_semicolon_values(first_nonempty(record, AUTHOR_TYPE_COLUMNS))

    if len(claim_values) == author_count and all("@" in value or value.lower() == "unknown" for value in claim_values):
        return ";".join(claim_values)

    if len(author_types) == author_count:
        result = []
        next_email_idx = 0
        for idx, author_type in enumerate(author_types):
            is_local = is_local_author_type(author_type)
            if is_local:
                email = ""
                if idx < len(claim_values) and "@" in claim_values[idx]:
                    email = claim_values[idx]
                else:
                    while next_email_idx < len(claim_values):
                        candidate = claim_values[next_email_idx]
                        next_email_idx += 1
                        if "@" in candidate:
                            email = candidate
                            break
                result.append(email if email else "unknown")
            else:
                result.append("unknown")
        return ";".join(result)

    if len(claim_values) == 1 and author_count == 1 and "@" in claim_values[0]:
        return claim_values[0]

    return ";".join(["unknown"] * author_count)

def get_output_columns(is_external_achievement=False):
    columns = TARGET_COLUMNS.copy()
    for col in SCOPE_COLUMNS:
        if col not in columns:
            try:
                insert_at = columns.index("题名") + 1 + SCOPE_COLUMNS.index(col)
            except ValueError:
                insert_at = len(columns)
            columns.insert(insert_at, col)
    if not is_external_achievement and CLAIM_COLUMN not in columns:
        columns.append(CLAIM_COLUMN)
    if not is_external_achievement:
        return columns
    if CLAIM_COLUMN in columns:
        return columns
    try:
        insert_at = columns.index("已认领作者") + 1
    except ValueError:
        insert_at = len(columns)
    columns.insert(insert_at, CLAIM_COLUMN)
    return columns



def process_scopus_row(row):
    aff_str = safe_get(row, ["Affiliations", "Affiliation", "机构", "单位", "作者单位", "归属机构"])
    aff_dict, master_aff_list = parse_scopus_affiliations(aff_str)

    full_names_str = safe_get(row, ["Author full names", "作者(全名)", "作者全名"])
    if not full_names_str:
        full_names_str = safe_get(row, ["Authors", "作者"])

    full_names = []
    if full_names_str:
        full_names = [clean_name_keep_full(x) for x in str(full_names_str).split(";")]

    auth_with_aff_str = safe_get(row, ["Authors with affiliations", "作者(包含单位)", "作者(包含机构)", "Authors with Affiliations", "带归属机构的作者"])
    auth_entries = split_scopus_author_affiliation_entries(auth_with_aff_str)
    if not master_aff_list and auth_with_aff_str:
        master_aff_list = extract_scopus_affiliations_from_authors(auth_with_aff_str)
        aff_dict = {aff: idx + 1 for idx, aff in enumerate(master_aff_list)}
    author_bundle = build_scopus_author_bundle(full_names, auth_entries, master_aff_list)
    corr_str = safe_get(row, ["Correspondence Address", "通讯地址", "通信地址", "通讯作者地址", "联系地址"])
    declared_corresponding_author = safe_get(row, ["Corresponding Author", "通讯作者"])
    corr_relations, corr_conflicts = parse_scopus_correspondence_relations(corr_str, full_names)
    corr_name_source = "SCOPUS: Correspondence Address" if corr_relations else ""
    corr_affiliation_source = "SCOPUS: Correspondence Address" if corr_relations else ""
    raw_corr_name = ""
    if not corr_relations and declared_corresponding_author:
        resolved_name, reason = resolve_full_author_name(declared_corresponding_author, full_names)
        if resolved_name:
            linked_affiliations = []
            # This fallback uses only the same Scopus row, and only when the
            # dedicated correspondence address itself is blank.
            if not corr_str:
                for relation in author_bundle["relations"]:
                    if relation["name"] == resolved_name:
                        linked_affiliations = relation["affiliations"]
                        break
            corr_relations = [{"name": resolved_name, "affiliations": linked_affiliations}]
            corr_name_source = "SCOPUS: Corresponding Author"
            corr_affiliation_source = (
                "SCOPUS: Authors with affiliations" if linked_affiliations else ""
            )
        else:
            raw_corr_name = declared_corresponding_author
            if full_names and reason:
                corr_conflicts.append(reason)
    corr_bundle = _make_correspondence_bundle(
        corr_relations,
        "SCOPUS",
        corr_name_source or ("SCOPUS: Corresponding Author" if raw_corr_name else ""),
        corr_affiliation_source,
        corr_conflicts,
        raw_name=raw_corr_name,
    )

    date_val = normalize_date(safe_get(row, ["Year", "年份", "日期"]))
    lang_raw = safe_get(row, ["Language of Original Document", "文献原始语言", "语种", "原始文献语言"])
    lang = translate_language(lang_raw)

    pg_start = safe_get(row, ['Page start', '起始页', '起始页码'])
    pg_end = safe_get(row, ['Page end', '结束页', '结束页码'])
    if pg_start:
        page_val = f"{pg_start}-{pg_end}" if pg_end else pg_start
    else:
        page_val = safe_get(row, ["Art. No.", "文章编号", "论文编号"])

    record = {
        "DOI": normalize_doi(safe_get(row, ["DOI", "数字对象唯一标识符"])),
        "题名": safe_get(row, ["Title", "Document title", "标题", "文献标题", "Article Title"]),
        "发表日期": date_val,
        "发表期刊": safe_get(row, ["Source title", "来源出版物名称", "期刊"]),
        "ISSN": safe_get(row, ["ISSN"]),
        "卷号": safe_get(row, ["Volume", "卷"]),
        "期号": safe_get(row, ["Issue", "期"]),
        "页码": page_val,
        "摘要": safe_get(row, ["Abstract", "摘要"]),
        "关键词": normalize_keywords(safe_get(row, ["Author Keywords", "作者关键词", "作者关键字", "关键词"])),
        "URL": safe_get(row, ["Link", "链接"]),
        "收录类别": "SCOPUS",
        "语种": lang,
        "资助项目": safe_get(row, ["Funding Details", "资助详细信息", "出资详情", "资金资助文本"]),
        "出版者": safe_get(row, ["Publisher", "出版商"]),
        "原始文献类型": safe_get(row, ["Document Type", "文献类型"]),
        "发表状态": normalize_publication_status(safe_get(row, ["Publication Stage", "出版阶段"])),
        "参考文献": safe_get(row, ["References", "参考文献"]),
        "SCOPUS_ID": safe_get(row, ["EID"]),
        "SCOPUSEID": safe_get(row, ["EID"]),
        "页数": safe_get(row, ["Page count", "页数"]),
        "Scopus被引次数": safe_get(row, ["Cited by", "被引次数", "施引文献"]),
        "Scopus学科分类": safe_get(row, ["Subject Areas", "Scopus Subject Areas", "Scopus学科分类"]),
        "来源库": "SCOPUS",
    }
    apply_author_bundle(record, author_bundle)
    apply_correspondence_bundle(record, corr_bundle)
    return apply_source_completion(record, row, complete_scopus_record)


def wos_name_resolver(short_names, full_names):
    """Use the same WOS row's parallel AU/AF lists, never a global name guess."""
    short_names = [normalize_author_display_name(n) for n in split_semicolon_values(short_names)]
    paired = len(short_names) == len(full_names) and bool(short_names)
    if paired:
        for short, full in zip(short_names, full_names):
            surname, initials = scopus_author_name_parts(short)
            full_surname, full_initials = scopus_author_name_parts(full)
            if surname != full_surname or not initials or not full_initials or initials[0] != full_initials[0]:
                paired = False
                break

    def resolve(candidate):
        candidate = normalize_author_display_name(candidate)
        exact = [n for n in full_names if n.casefold() == candidate.casefold()]
        if len(exact) == 1:
            return exact[0], ""
        matches = [i for i, n in enumerate(short_names) if n.casefold() == candidate.casefold()]
        if len(matches) > 1 or len(exact) > 1:
            return "", f"通讯作者姓名匹配不唯一：{candidate}"
        if paired and len(matches) == 1:
            return full_names[matches[0]], ""
        index = unique_author(candidate, full_names)
        if index is not None:
            return full_names[index], ""
        return "", f"通讯作者姓名无法唯一匹配作者列表：{candidate}"
    return resolve


def parse_wos_correspondence(raw, resolve):
    """Partition marked RP groups before resolving names or collecting units."""
    markers = list(re.finditer(r"\((?:corresponding|reprint)\s+author\)", raw, re.I))
    if not markers:
        return [], [], [], raw
    starts = [0]
    for previous, marker in zip(markers, markers[1:]):
        between = raw[previous.end():marker.start()]
        boundaries = [0, *[m.end() for m in re.finditer(r"[;；]", between)]]
        if len(boundaries) < 2:
            return [], [], ["WOS 通讯地址组之间缺少明确分隔符：" + raw], raw
        index = len(boundaries) - 1
        while index > 1:
            token = between[boundaries[index - 1]:boundaries[index] - 1].strip()
            known, _ = resolve(token)
            if not known:
                # An unrecognised "Surname, Given" before a shared marker may
                # be another person, not the preceding author's institution.
                # Preserve the raw group for review rather than invent a link.
                if re.fullmatch(r"[^,;()\d]+,\s*[^,;()\d]+", token):
                    return [], [], ["WOS 通讯地址姓名/单位边界不明确：" + raw], raw
                break
            index -= 1
        starts.append(previous.end() + boundaries[index])

    relations = {}
    resolved_relations = {}
    conflicts = []
    for i, marker in enumerate(markers):
        candidates = split_semicolon_values(raw[starts[i]:marker.start()])
        address = raw[marker.end():starts[i + 1] if i + 1 < len(starts) else len(raw)].strip(" ,;；")
        if not candidates or not address:
            conflicts.append("WOS 通讯作者或通讯地址缺失：" + raw[starts[i]:marker.end()])
        for candidate in candidates:
            name, reason = resolve(candidate)
            if reason:
                conflicts.append(reason)
            # Preserve unidentified people as explicit unresolved evidence.
            key = name or candidate
            units = split_semicolon_values(address)
            relations.setdefault(key, []).extend(units)
            if name and address:
                resolved_relations.setdefault(name, []).extend(units)
    pack = lambda mapping: [{"name": name, "affiliations": _unique_values(units)} for name, units in mapping.items()]
    return pack(relations), pack(resolved_relations), conflicts, ""


def wos_record_url(row, doi):
    # Legacy XLS hyperlink formulas can expose a cached "0", not a URL.
    for field in ["DOI Link", "URL", "Web of Science Record"]:
        value = safe_get(row, [field])
        try:
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not re.search(r"\s", value):
                return value
        except ValueError:
            pass
    if re.fullmatch(r"10\.\d{4,9}/\S+", str(doi or ""), re.I):
        return "https://doi.org/" + doi
    return ""


# WOS 处理逻
def process_wos_row(row):
    doi = normalize_doi(safe_get(row, ["DOI", "DI"]))
    pub_date = safe_get(row, ["Publication Date", "PD"])
    pub_year = safe_get(row, ["Publication Year", "PY", "Year"])
    final_date = normalize_date(pub_date, pub_year)

    wos_cat = safe_get(row, ["WoS Categories", "Web of Science Categories", "WC", "Subject Category"])
    wos_index = normalize_wos_index(safe_get(row, ["Web of Science Index", "WOS Index", "WoS Index", "Index"]))

    authors_full = safe_get(row, ["Author Full Names", "AF", "作者(全名)", "作者全名"])
    authors_short = safe_get(row, ["Authors", "AU", "作者"])
    authors_af = authors_full or authors_short

    af_list = [normalize_author_display_name(x) for x in str(authors_af).split(';')] if authors_af else []
    af_list = [author for author in af_list if author]
    first_author = af_list[0] if af_list else ""
    resolve_wos_name = wos_name_resolver(authors_short, af_list)

    addresses = safe_get(row, ["Addresses", "C1", "作者单位"])
    
    author_relations = [{"name": author, "affiliations": []} for author in af_list]
    linked_affiliations = []
    unlinked_affiliations = []
    author_conflicts = []
    if addresses and '[' in addresses:
        pattern = re.compile(r'\[(.*?)\]\s*([^\[]+)')
        matches = pattern.findall(addresses)
        if matches:
            for authors_in_bracket, affil_text in matches:
                # A bracketed author list only proves the association with the
                # immediately following address. Some legacy WOS records mix
                # one bracketed address with later bare addresses; assigning
                # those later addresses to the preceding authors would invent
                # an author--affiliation relationship.
                affil_parts = [part.strip() for part in affil_text.split(';') if part.strip()]
                if not affil_parts:
                    continue
                affil = affil_parts[0]
                linked_affiliations.append(affil)
                unlinked_affiliations.extend(affil_parts[1:])
                for au in authors_in_bracket.split(';'):
                    resolved_name, reason = resolve_wos_name(au)
                    if not resolved_name:
                        if reason:
                            author_conflicts.append(
                                reason.replace("通讯作者姓名", "WOS 作者—单位姓名")
                            )
                        continue
                    for relation in author_relations:
                        if relation["name"] == resolved_name:
                            relation["affiliations"].append(affil)
                            break
    elif addresses:
        # Bare WOS addresses are retained for reference but are not promoted
        # into an author relation or artificial numbered affiliation list.
        unlinked_affiliations = split_semicolon_values(addresses)
    author_bundle = _make_author_bundle(
        author_relations,
        linked_affiliations,
        "WOS",
        "Addresses/C1",
        author_conflicts,
        marker_space=True,
        unlinked_affiliations=unlinked_affiliations,
        index_affiliations=bool(linked_affiliations),
    )
    # A legacy WOS Addresses field may list institutions without author tags.
    # Its first address is not evidence that it belongs to the first author.

    # 提取通讯作者全名及单位
    rp_address = safe_get(row, ["Reprint Addresses", "RP", "通讯地址"])
    corr_relations, resolved_corr, corr_conflicts, raw_corr_affiliations = parse_wos_correspondence(rp_address, resolve_wos_name)
    corr_bundle = _make_correspondence_bundle(
        corr_relations,
        "WOS",
        "WOS: Reprint Addresses" if corr_relations else "",
        "WOS: Reprint Addresses" if corr_relations or raw_corr_affiliations else "",
        corr_conflicts,
        raw_affiliations=raw_corr_affiliations,
    )

    lang_raw = safe_get(row, ["Language", "LA", "语种"])
    lang = translate_language(lang_raw)

    page_value = safe_get(row, ["Pages", "PG", "Page"])
    if not page_value:
        start_page = safe_get(row, ["Start Page", "BP"])
        end_page = safe_get(row, ["End Page", "EP"])
        if start_page and end_page:
            page_value = f"{start_page}-{end_page}"
        else:
            page_value = start_page or end_page

    record = {
        "DOI": doi,
        "WOS记录号": safe_get(row, ["UT (Unique WOS ID)", "UT", "Accession Number"]),
        "WOS研究方向": safe_get(row, ["Research Areas", "SC"]),
        "WOS类目": wos_cat,
        "SCI被引次数": safe_get(row, ["Times Cited, All Databases", "TC"]),
        "影响因子": safe_get(row, ["Impact Factor", "IF", "Journal Impact Factor"]),
        "收录类别": wos_index or "SCIE",
        "来源库": "WOS",
        "URL": wos_record_url(row, doi),
        "语种": lang,
        "发表日期": final_date,
    }

    record["题名"] = safe_get(row, ["Article Title", "Title", "TI"])
    record["发表期刊"] = safe_get(row, ["Source Title", "Journal", "SO"])
    record["ISSN"] = safe_get(row, ["ISSN", "SN"])
    record["EISSN"] = safe_get(row, ["eISSN", "EISSN", "EI"])
    record["卷号"] = safe_get(row, ["Volume", "VL"])
    record["期号"] = safe_get(row, ["Issue", "IS"])
    record["页码"] = page_value
    record["摘要"] = safe_get(row, ["Abstract", "AB"])
    record["关键词"] = normalize_keywords(safe_get(row, ["Author Keywords", "DE", "Keywords Plus", "ID"]))
    record["页数"] = safe_get(row, ["Number of Pages", "Page Count", "PG"])
    record["参考文献"] = safe_get(row, ["Cited References", "CR"])
    record["资助项目"] = safe_get(row, ["Funding Orgs", "FU"])
    record["出版者"] = safe_get(row, ["Publisher", "PU"])
    record["原始文献类型"] = safe_get(row, ["Document Type", "DT"])
    record["发表状态"] = "在线发表" if safe_get(row, ["Early Access Date"]) else normalize_publication_status(
        safe_get(row, ["Publication Status", "Publication Stage"])
    )

    apply_author_bundle(record, author_bundle)
    apply_correspondence_bundle(record, corr_bundle)
    record["_wos_resolved_correspondence"] = resolved_corr
    return apply_source_completion(record, row, complete_wos_record)


#  EI 
def process_ei_row(row):
    doi = normalize_doi(safe_get(row, ["DOI"]))

    ei_terms = safe_get(row, ["Controlled/Subject terms"])
    if not ei_terms:
        ei_terms = safe_get(row, ["Main Heading"])
    if not ei_terms:
        ei_terms = safe_get(row, ["Uncontrolled terms"])

    lang_raw = safe_get(row, ["Language"])
    lang = translate_language(lang_raw)
    authors = safe_get(row, ["Author", "Author(s)", "Authors", "作者"])
    first_author = authors.split(";")[0].strip() if authors else ""
    affiliations = safe_get(row, ["Author affiliation", "Author Affiliation", "Affiliation", "作者单位", "机构"])
    first_author_aff = affiliations.split(";")[0].strip() if affiliations else ""

    record = {
        "DOI": doi,
        "题名": safe_get(row, ["Title"]),
        "作者": authors,
        "第一作者": first_author,
        "作者单位": affiliations,
        "第一作者单位": first_author_aff,
        "发表期刊": safe_get(row, ["Source"]),
        "ISSN": safe_get(row, ["ISSN"]),
        "EISSN": safe_get(row, ["E-ISSN"]),
        "卷号": safe_get(row, ["Volume"]),
        "页码": safe_get(row, ["Pages"]),
        "发表日期": normalize_date(safe_get(row, ["Issue date", "Publication year"])),
        "出版者": safe_get(row, ["Publisher/Repository"]),
        "摘要": safe_get(row, ["Abstract"]),
        "语种": lang,
        "原始文献类型": safe_get(row, ["Document type"]),
        "发表状态": normalize_publication_status(safe_get(row, ["Publication stage", "Publication Stage", "Publication status", "Publication Status"])),
        "EI入藏号": safe_get(row, ["Accession number"]),
        "EI主题词": ei_terms,
        "EI分类号": safe_get(row, ["Classification code"]),
        "收录类别": "EI",
        "来源库": "EI",
    }
    return apply_source_completion(record, row, complete_ei_record)


def apply_source_completion(record, row, completion):
    """Keep derived display values and merge-time evidence bundles synchronized."""
    before = (record.get("作者", ""), record.get("作者单位", ""))
    completion(record, row)
    if before != (record.get("作者", ""), record.get("作者单位", "")):
        record.pop(AUTHOR_RELATIONS_KEY, None)
        bundle = _author_bundle_from_record(record)
        bundle["evidence"] = record.get(EVIDENCE_COLUMN, "")
        record[AUTHOR_RELATIONS_KEY] = bundle
        record[AUTHOR_RELATION_SOURCE_COLUMN] = bundle["source"]
    elif completion is complete_ei_record:
        # Carry unresolved original indices even when no display normalization
        # was possible, so a later DOI merge cannot silently erase the issue.
        record[AUTHOR_RELATIONS_KEY] = _author_bundle_from_record(record)
    if completion is complete_ei_record and record.get("通讯作者"):
        relations = record.pop("_ei_completed_correspondence", [])
        has_units = any(relation["affiliations"] for relation in relations)
        record[CORRESPONDENCE_RELATIONS_KEY] = _make_correspondence_bundle(
            relations, "EI", "EI: Corresponding author(s)",
            "EI: Author / Author affiliation" if has_units else "",
            conflicts=split_semicolon_values(record.get(CORRESPONDENCE_CONFLICT_COLUMN, "")),
            raw_name=record["通讯作者"],
        )
        record[CORRESPONDENCE_NAME_SOURCE_COLUMN] = "EI: Corresponding author(s)"
        record[CORRESPONDENCE_AFFILIATION_SOURCE_COLUMN] = "EI: Author / Author affiliation" if has_units else ""
    return record


def count_author_affiliation_markers(author_text):
    text = str(author_text or "")
    if not text or text.lower() == "nan":
        return 0
    return len(re.findall(r"\(\d+(?:,\d+)*\)", text))


# 合并
def merge_document_types(existing_value, new_value) -> str:
    """Combine source document types so classification survives DOI merging."""
    values = []
    seen = set()
    for raw_value in (existing_value, new_value):
        for value in re.split(r"[;；,/]+", str(raw_value or "")):
            value = value.strip()
            if not value or value.lower() in {"nan", "none"}:
                continue
            normalized = value.lower()
            if normalized not in seen:
                seen.add(normalized)
                values.append(value)
    return "; ".join(values)


def merge_records(existing, new_data):
    # Author markers are only meaningful with the exact affiliation list that
    # produced them.  Select one complete relationship bundle, then regenerate
    # both columns from that bundle so source-local numbers can never leak into
    # another source's unit list.
    merged_author_bundle = merge_author_bundles(
        _author_bundle_from_record(existing),
        _author_bundle_from_record(new_data),
    )
    apply_author_bundle(existing, merged_author_bundle)

    # Treat a corresponding author and its affiliation as one evidence unit as
    # well; never let the historical Scopus name preference overwrite only half
    # of a WOS correspondence pair.
    merged_correspondence_bundle = merge_correspondence_bundles(
        _correspondence_bundle_from_record(existing),
        _correspondence_bundle_from_record(new_data),
    )
    apply_correspondence_bundle(existing, merged_correspondence_bundle)

    for key, val in new_data.items():
        if key == "DOI" or key in {AUTHOR_RELATIONS_KEY, CORRESPONDENCE_RELATIONS_KEY}:
            continue
        if val is None:
            continue
        sval = str(val)
        if not sval or sval == "nan":
            continue

        if key == "原始文献类型":
            existing[key] = merge_document_types(existing.get(key, ""), sval)
            continue

        if key == EVIDENCE_COLUMN:
            existing[key] = "；".join(dict.fromkeys(
                note for value in (existing.get(key, ""), sval)
                for note in str(value).split("；") if note
            ))
            continue

        if key in ["收录类别", "来源库", "WOS记录号", "WOS研究方向", "WOS类目"]:
            if key in existing and existing[key]:
                if sval not in existing[key]:
                    existing[key] += "; " + sval
            else:
                existing[key] = sval
            continue

        if key == "关键词":
            val = normalize_keywords(sval)
            if not val:
                continue

        if key in AUTHOR_RELATION_OUTPUT_FIELDS or key in CORRESPONDENCE_OUTPUT_FIELDS:
            continue

        if key not in existing or not existing[key] or str(existing[key]) in ["nan", "nan-nan", "-"]:
            existing[key] = val
            continue

        if key == "发表日期":
            if len(str(val)) > len(str(existing[key])):
                existing[key] = val

    return existing


def merge_doi_group(records, merge_fn=None):
    """Merge a DOI group without mixing journal and conference records.

    Inspect all original records first: an untyped record must not bridge the
    two types, nor may input order determine which side receives its fields.
    Unchanged DOI groups retain the historical merging behavior.
    """
    merge_fn = merge_fn or merge_records
    groups = [document_type_group(record) for record in records]
    split_types = {"journal", "conference"}.issubset(groups)
    merged = {}
    for record, group in zip(records, groups):
        key = group if split_types else "all"
        if key in merged:
            merged[key] = merge_fn(merged[key], record)
        else:
            merged[key] = record.copy()
    return list(merged.values())


# 文件读取
def read_ei_csv_robust(file_path):
    try:
        return pd.read_csv(file_path, sep=",", engine="python", dtype=str, encoding="utf-8-sig", quotechar='"', escapechar="\\", doublequote=True)
    except Exception:
        return pd.read_csv(file_path, sep=",", engine="python", dtype=str, encoding="utf-8-sig", quotechar='"', escapechar="\\", on_bad_lines="skip")

def read_normal_csv_robust(file_path):
    sep = ','
    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            header = f.readline()
            if header.count(';') > header.count(','):
                sep = ';'
    except Exception:
        pass
    
    try:
        return pd.read_csv(file_path, sep=sep, dtype=str, encoding='utf-8-sig')
    except Exception:
        return pd.read_csv(file_path, sep=sep, engine="python", dtype=str, encoding='utf-8-sig', on_bad_lines="skip")


def fetch_scopus_xml(doi: str, eid: str, api_key: str) -> str:
    doi = (doi or "").strip()
    eid = (eid or "").strip()
    if not api_key or (not doi and not eid):
        return ""
    if doi:
        url = f"https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}"
    else:
        url = f"https://api.elsevier.com/content/abstract/eid/{urllib.parse.quote(eid)}"
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/xml"}
    resp = requests.get(url, headers=headers, params={"view": "FULL"}, timeout=20)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.text


def parse_scopus_subjects(xml_text: str):
    if not xml_text:
        return ""
    ns = {"ab": "http://www.elsevier.com/xml/svapi/abstract/dtd"}
    root = ET.fromstring(xml_text)
    names = []
    for subject_area in root.findall(".//ab:subject-areas/ab:subject-area", ns):
        name = (subject_area.text or "").strip()
        if name:
            names.append(name)
    return "; ".join(names)


def supplement_scopus_subjects(df, api_key):
    if not api_key or df.empty:
        return df
    df = df.copy()
    for col in ["DOI", "SCOPUSEID", "Scopus学科分类"]:
        if col not in df.columns:
            df[col] = ""
    tasks = df[["DOI", "SCOPUSEID"]].fillna("").astype(str).drop_duplicates()
    tasks = tasks[(tasks["DOI"].str.strip() != "") | (tasks["SCOPUSEID"].str.strip() != "")]
    records = []
    print(f"发现 {len(tasks)} 条文章记录，开始补充 Scopus 学科信息...")
    for i, (doi, eid) in enumerate(tasks.values, start=1):
        try:
            xml_text = fetch_scopus_xml(doi, eid, api_key)
            subject_names = parse_scopus_subjects(xml_text)
        except Exception as exc:
            print(f"[{i}/{len(tasks)}] Scopus 学科查询失败: {exc}")
            subject_names = ""
        records.append({"DOI": doi, "SCOPUSEID": eid, "Scopus学科分类": subject_names})
        sleep(0.2)
    if not records:
        return df
    subjects = pd.DataFrame(records)
    return df.drop(columns=["Scopus学科分类"], errors="ignore").merge(subjects, how="left", on=["DOI", "SCOPUSEID"])


def run_conversion(
    input_paths,
    output_path,
    mode,
    accounts_path=None,
    article_library_path=None,
    alias_path=None,
    scopus_api_key=None,
    claim_email_filter=None,
):
    input_paths = list(input_paths or [])
    single_source_mode = len(input_paths) == 1
    merged_db = {}
    mapped_records = []
    publication_name_to_email = {}
    is_external_achievement = mode in {"external", "校外", "非本校成果", "校外成果"}

    print(f"准备处理 {len(input_paths)} 个文件...")
    if single_source_mode:
        print("单来源模式：逐条字段映射，不按 DOI 去重。")
    alias_registry = build_scholar_alias_registry(
        accounts_path=accounts_path,
        article_library_path=article_library_path,
        alias_path=alias_path,
    )
    claim_filter_emails = parse_claim_email_filter(claim_email_filter)
    if str(claim_email_filter or "").strip():
        original_alias_count = len(alias_registry.get("aliases", {}))
        alias_registry = filter_alias_registry_by_emails(alias_registry, claim_email_filter)
        print(
            f"限定作品认领匹配邮箱: 有效邮箱 {len(claim_filter_emails)} 个, "
            f"别名 {original_alias_count} -> {len(alias_registry.get('aliases', {}))} 条"
        )
        if alias_registry.get("claim_email_filter_unmatched"):
            print(
                "未在别名表中找到这些邮箱对应的别名: "
                + "; ".join(alias_registry["claim_email_filter_unmatched"])
            )
    print(
        f"学者别名表: 别名 {len(alias_registry.get('aliases', {}))} 条, "
        f"当前使用的别名来源={alias_registry.get('alias_path') or '未找到'}, "
        f"冲突别名 {len(alias_registry.get('conflict_aliases', []))} 条, "
        f"账户表={'已加载' if alias_registry.get('account_path') else '未找到'}, "
        f"文章库={'已加载' if alias_registry.get('article_library_path') else '未找到'}"
    )
    if is_external_achievement:
        publication_name_to_email, mapping_info = build_publication_name_to_email(
            article_library_path=article_library_path,
            account_path=accounts_path,
        )
        if str(claim_email_filter or "").strip():
            original_mapping_count = len(publication_name_to_email)
            publication_name_to_email = filter_publication_name_to_email_by_emails(
                publication_name_to_email,
                claim_email_filter,
            )
            print(
                f"限定发文名-邮箱映射: {original_mapping_count} -> {len(publication_name_to_email)} 条"
            )
        if mapping_info["account_path"]:
            print(f"已加载账户表: {mapping_info['account_path']}")
        else:
            print("未找到账户表，无法把姓名转换为邮箱；未匹配作者将填 unknown。")
        if mapping_info["article_library_path"]:
            print(f"已加载文章库: {mapping_info['article_library_path']}")
        print(
            f"映射统计: 发文名-姓名 {mapping_info['publication_name_count']} 条, "
            f"姓名-邮箱 {mapping_info['email_count']} 条, 发文名-邮箱 {mapping_info['publication_email_count']} 条"
        )

    for file_path in input_paths:
        try:
            file_path = str(file_path)
            print(f"正在读取: {file_path}")

            if file_path.endswith(".csv"):
                is_ei_csv = False
                try:
                    with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        header_line = f.readline().lower()
                        if "accession number" in header_line or "compendex" in header_line:
                            is_ei_csv = True
                except Exception:
                    pass

                if is_ei_csv:
                    df = read_ei_csv_robust(file_path)
                else:
                    df = read_normal_csv_robust(file_path)
            
            elif file_path.endswith(".xls") or file_path.endswith(".xlsx"):
                df = pd.read_excel(file_path, dtype=str)
            elif file_path.endswith(".txt"):
                df = pd.read_csv(file_path, sep="\t", engine="python", dtype=str)
            else:
                print(f"跳过: {file_path}")
                continue

            df.columns = df.columns.str.strip().str.replace("\ufeff", "")

            is_scopus = ("EID" in df.columns) or ("scopus" in str(file_path).lower()) or ("带归属机构的作者" in df.columns)
            is_wos = ("UT (Unique WOS ID)" in df.columns) or ("Web of Science Record" in df.columns) or ("UT" in df.columns)
            is_ei = ("Accession number" in df.columns or "Accession Number" in df.columns) and ("Classification code" in df.columns or "Classification Code" in df.columns)

            if is_wos:
                print("  [识别为 WOS]")
            elif is_scopus:
                print("  [识别为 SCOPUS]")
            elif is_ei:
                print("  [识别为 EI]")

            for _, row in df.iterrows():
                if is_scopus:
                    record = process_scopus_row(row)
                elif is_wos:
                    record = process_wos_row(row)
                elif is_ei:
                    record = process_ei_row(row)
                else:
                    record = process_scopus_row(row)

                record = copy_claim_inputs(record, row)
                if is_external_achievement:
                    record[CLAIM_COLUMN] = build_claim_value(record, publication_name_to_email)

                if single_source_mode:
                    mapped_records.append(record)
                else:
                    doi = record.get("DOI")
                    if doi:
                        merged_db.setdefault(doi, []).append(record)

        except Exception as e:
            print(f"读取错误 {file_path}: {e}")

    output_df = pd.DataFrame(mapped_records if single_source_mode else [
        record for records in merged_db.values() for record in merge_doi_group(records)
    ])

    output_columns = get_output_columns(is_external_achievement)
    for col in output_columns:
        if col not in output_df.columns:
            output_df[col] = ""

    output_df = output_df[output_columns]
    if scopus_api_key:
        output_df = supplement_scopus_subjects(output_df, scopus_api_key)
    output_df = apply_scope_fields(output_df, mode, alias_registry)
    sheet_counts = write_multi_sheet_excel(output_df, output_path)
    print(
        "导出统计: "
        + ", ".join(f"{name} {count} 条" for name, count in sheet_counts.items())
    )
    print(f"完成！已保存到 {output_path}")
    return {
        "output_path": str(output_path),
        "total": sheet_counts.get("全部数据", 0),
        "local": sheet_counts.get("本校成果", 0),
        "external_ready": sheet_counts.get("校外成果", 0),
        "pending": (
            sheet_counts.get("待复核_可尝试原文补全", 0)
            + sheet_counts.get("待复核_其他", 0)
        ),
        "reviewable_from_original": sheet_counts.get("待复核_可尝试原文补全", 0),
        "review_other": sheet_counts.get("待复核_其他", 0),
        "missing_email": sheet_counts.get("需补邮箱", 0),
        "sheet_counts": sheet_counts,
        "alias_path": alias_registry.get("alias_path", ""),
        "alias_count": len(alias_registry.get("aliases", {})),
        "conflict_alias_count": len(alias_registry.get("conflict_aliases", [])),
        "claim_email_filter": claim_filter_emails,
        "claim_email_filter_matched": alias_registry.get("claim_email_filter_matched", []),
        "claim_email_filter_unmatched": alias_registry.get("claim_email_filter_unmatched", []),
    }


def main(
    files,
    output_file,
    is_external_achievement=False,
    article_library_path=None,
    account_path=None,
    alias_path=None,
    claim_email_filter=None,
):
    mode = "external" if is_external_achievement else "local"
    return run_conversion(
        files,
        output_file,
        mode,
        accounts_path=account_path,
        article_library_path=article_library_path,
        alias_path=alias_path,
        claim_email_filter=claim_email_filter,
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 converter.py result.xlsx [--local|--external] input1 input2 ...")
        sys.exit(1)

    args = sys.argv[2:]
    is_external = False
    article_library_path = None
    account_path = None
    alias_path = None
    claim_email_filter = None
    input_files = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ["--external", "--non-local", "--outside"]:
            is_external = True
        elif arg == "--local":
            is_external = False
        elif arg == "--article-library" and i + 1 < len(args):
            article_library_path = args[i + 1]
            i += 1
        elif arg == "--accounts" and i + 1 < len(args):
            account_path = args[i + 1]
            i += 1
        elif arg in ["--aliases", "--alias-file"] and i + 1 < len(args):
            alias_path = args[i + 1]
            i += 1
        elif arg in ["--claim-emails", "--claim-email-filter"] and i + 1 < len(args):
            claim_email_filter = args[i + 1]
            i += 1
        else:
            input_files.append(arg)
        i += 1

    main(
        input_files,
        sys.argv[1],
        is_external_achievement=is_external,
        article_library_path=article_library_path,
        account_path=account_path,
        alias_path=alias_path,
        claim_email_filter=claim_email_filter,
    )
