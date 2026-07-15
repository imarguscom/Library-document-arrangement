import re
import sys
from pathlib import Path

import pandas as pd


LOCAL_AFFILIATION_KEYWORDS = [
    "chinese univ hong kong shenzhen",
    "chinese university of hong kong shenzhen",
    "the chinese university of hong kong, shenzhen",
    "cuhk-shenzhen",
    "cuhk shenzhen",
    "香港中文大学（深圳）",
    "香港中文大学(深圳)",
    "港中深",
]

ARTICLE_LIBRARY_MARKERS = ["期刊论文", "_所有"]
ACCOUNT_FILE_MARKERS = ["账户", "帐号", "账号", "用户", "user", "account", "学者"]

NAME_COLUMNS = ["姓名", "学者姓名", "用户姓名", "真实姓名", "名称", "姓名/名称", "Name", "name"]
ENGLISH_NAME_COLUMNS = ["英文名", "英文姓名", "发文名", "Author Name", "English Name", "english_name"]
EMAIL_COLUMNS = ["注册邮箱", "邮箱", "电子邮箱", "邮件", "Email", "email", "E-mail", "e-mail"]
AFFILIATION_COLUMNS = ["机构", "部门", "学院", "单位", "院系", "Organization", "Department"]
CLAIMABLE_EMAIL_DOMAIN = "cuhk.edu.cn"


def normalize_name(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("，", ",").strip(" ;；")
    return text.lower()


def is_claimable_email(email):
    email = str(email or "").strip().lower()
    if "@" not in email:
        return False
    return email.rsplit("@", 1)[-1] == CLAIMABLE_EMAIL_DOMAIN


def split_values(value):
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [x.strip() for x in re.split(r"[;；]", text) if x.strip()]


def find_first_column(columns, candidates):
    normalized = {str(col).strip().lower(): col for col in columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    for col in columns:
        col_text = str(col).strip().lower()
        if any(candidate.strip().lower() in col_text for candidate in candidates):
            return col
    return None


def read_table(path, **kwargs):
    path = Path(path)
    if path.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path, dtype=str, **kwargs)
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", **kwargs)


def resolve_src_dir(src_dir="src"):
    src = Path(src_dir)
    candidates = []
    if src.is_absolute():
        candidates.append(src)
    else:
        base = Path(getattr(sys, "_MEIPASS", Path.cwd()))
        candidates.append(base / src)
        candidates.append(Path.cwd() / src)
        candidates.append(Path(__file__).resolve().parent / src)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def discover_article_library(src_dir="src"):
    src = resolve_src_dir(src_dir)
    for path in src.glob("*"):
        if path.suffix.lower() not in [".xlsx", ".xls", ".csv"]:
            continue
        name = path.name.lower()
        if all(marker.lower() in name for marker in ARTICLE_LIBRARY_MARKERS):
            return path
    return None


def discover_account_file(src_dir="src", article_library_path=None):
    src = resolve_src_dir(src_dir)
    article_library_path = Path(article_library_path).resolve() if article_library_path else None
    tabular_files = []
    for path in src.glob("*"):
        if path.suffix.lower() not in [".xlsx", ".xls", ".csv"]:
            continue
        if article_library_path and path.resolve() == article_library_path:
            continue
        tabular_files.append(path)
        name = path.name.lower()
        if any(marker.lower() in name for marker in ACCOUNT_FILE_MARKERS):
            return path

    for path in tabular_files:
        try:
            df = read_table(path, nrows=2)
        except Exception:
            continue
        if find_first_column(df.columns, NAME_COLUMNS) and find_first_column(df.columns, EMAIL_COLUMNS):
            return path
    return None


def parse_author_entries(author_text):
    entries = []
    for raw in split_values(author_text):
        match = re.match(r"^(.*?)\s*\(([\d,\s]+)\)\s*$", raw)
        if match:
            name = match.group(1).strip()
            indices = [int(x) for x in re.findall(r"\d+", match.group(2))]
        else:
            name = raw.strip()
            indices = []
        if name:
            entries.append({"name": name, "indices": indices})
    return entries


def parse_affiliations(affiliation_text):
    text = "" if pd.isna(affiliation_text) else str(affiliation_text)
    pattern = re.compile(r"\((\d+)\)\s*(.*?)(?=(?:;;?\s*)?\(\d+\)|$)")
    affiliations = {}
    for idx, aff in pattern.findall(text):
        affiliations[int(idx)] = aff.strip(" ;；")
    return affiliations


def is_local_affiliation(affiliation, local_keywords=None):
    normalized = re.sub(r"\s+", " ", str(affiliation).lower())
    keywords = LOCAL_AFFILIATION_KEYWORDS.copy()
    if local_keywords:
        keywords.extend(local_keywords)
    return any(keyword.lower() in normalized for keyword in keywords if keyword)


def infer_publication_name_to_real_name(article_library_path, local_keywords=None):
    if not article_library_path:
        return {}
    df = read_table(article_library_path)
    mapping = {}
    evidence_count = {}

    required = {"作者", "作者单位", "已认领作者"}
    if not required.issubset(set(df.columns)):
        return {}

    for _, row in df.iterrows():
        claimed_names = split_values(row.get("已认领作者", ""))
        if not claimed_names:
            continue

        authors = parse_author_entries(row.get("作者", ""))
        affiliations = parse_affiliations(row.get("作者单位", ""))
        if not authors or not affiliations:
            continue

        local_authors = []
        for author in authors:
            if any(is_local_affiliation(affiliations.get(idx, ""), local_keywords) for idx in author["indices"]):
                local_authors.append(author["name"])

        if len(local_authors) != len(claimed_names):
            continue

        for publication_name, real_name in zip(local_authors, claimed_names):
            pub_key = normalize_name(publication_name)
            real_name = real_name.strip()
            if not pub_key or not real_name:
                continue
            pair = (pub_key, real_name)
            evidence_count[pair] = evidence_count.get(pair, 0) + 1

    best_by_pub_name = {}
    for (pub_key, real_name), count in evidence_count.items():
        current = best_by_pub_name.get(pub_key)
        if not current or count > current[1]:
            best_by_pub_name[pub_key] = (real_name, count)

    for pub_key, (real_name, _) in best_by_pub_name.items():
        mapping[pub_key] = real_name
    return mapping


def load_name_to_email(account_path):
    if not account_path:
        return {}
    df = read_table(account_path)
    name_col = find_first_column(df.columns, NAME_COLUMNS)
    email_col = find_first_column(df.columns, EMAIL_COLUMNS)
    english_name_col = find_first_column(df.columns, ENGLISH_NAME_COLUMNS)
    if not name_col or not email_col:
        return {}

    mapping = {}
    for _, row in df.iterrows():
        email = row.get(email_col, "")
        if pd.isna(email) or "@" not in str(email):
            continue
        email = str(email).strip()
        if not is_claimable_email(email):
            continue
        for col in [name_col, english_name_col]:
            if not col:
                continue
            key = normalize_name(row.get(col, ""))
            if key:
                mapping[key] = email
    return mapping


def load_local_affiliation_keywords(account_path):
    if not account_path:
        return []
    df = read_table(account_path)
    columns = [col for col in df.columns if any(candidate.lower() in str(col).lower() for candidate in AFFILIATION_COLUMNS)]
    keywords = set()
    for col in columns:
        for value in df[col].dropna().astype(str):
            value = re.sub(r"\s+", " ", value).strip()
            if not value or value.lower() == "nan":
                continue
            if len(value) < 2:
                continue
            keywords.add(value)
    return sorted(keywords, key=len, reverse=True)


def build_publication_name_to_email(article_library_path=None, account_path=None, src_dir="src"):
    article_library_path = article_library_path or discover_article_library(src_dir)
    account_path = account_path or discover_account_file(src_dir, article_library_path)
    local_keywords = load_local_affiliation_keywords(account_path)
    pub_to_real = infer_publication_name_to_real_name(article_library_path, local_keywords)
    name_to_email = load_name_to_email(account_path)

    pub_to_email = {}
    for pub_key, real_name in pub_to_real.items():
        email = name_to_email.get(normalize_name(real_name))
        if email:
            pub_to_email[pub_key] = email

    for name_key, email in name_to_email.items():
        pub_to_email.setdefault(name_key, email)

    return pub_to_email, {
        "article_library_path": str(article_library_path) if article_library_path else "",
        "account_path": str(account_path) if account_path else "",
        "publication_name_count": len(pub_to_real),
        "email_count": len(name_to_email),
        "publication_email_count": len(pub_to_email),
        "local_affiliation_keyword_count": len(local_keywords),
    }
