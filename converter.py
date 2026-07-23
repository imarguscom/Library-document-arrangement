import pandas as pd
import sys
import re
import urllib.parse
import xml.etree.ElementTree as ET
from time import sleep

import requests

from claim_mapping import build_publication_name_to_email, normalize_name
from scope_rules import (
    SCOPE_COLUMNS,
    apply_scope_fields,
    build_scholar_alias_registry,
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
    "EI主题词", "EI分类号", "原始文献类型", "发表状态", "字数", "CN", "卷/期/页",
    "参考文献", "通讯作者", "来源库", "SCOPUS_ID", "Scopus学科分类", "SCOPUSEID",
    "页数", "CNKI学科分类", "网络首发", "中图分类号", "作者单位", "第一作者",
    "已认领作者", "Scopus被引次数", "SCI被引次数", "CSCD被引次数", "影响因子",
    "5年平均影响因子", "所属专题", "发文作者类型"
]

CLAIM_COLUMN = "作品认领"
CLAIM_SOURCE_COLUMNS = [CLAIM_COLUMN, "已认领作者", "注册邮箱", "邮箱", "学者邮箱", "认领邮箱"]
AUTHOR_TYPE_COLUMNS = ["发文作者类型", "作者类型"]
DEFAULT_DATE_SUFFIX = "-01-01"
EXCEL_CELL_CHAR_LIMIT = 32767


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
        ("ARTS & HUMANITIES CITATION INDEX", "A&HCI"),
        ("ARTS AND HUMANITIES CITATION INDEX", "A&HCI"),
        ("A&HCI", "A&HCI"),
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
    short_name = str(short_name or "").strip()
    if not short_name:
        return ""
    short_last = short_name.split(",")[0].strip().lower()
    for full_name in full_names:
        full_last = str(full_name).split(",")[0].strip().lower()
        if short_last == full_last or short_last in full_last or full_last in short_last:
            return full_name
    return short_name

def parse_scopus_correspondence(corr_str, full_names):
    if not corr_str:
        return "", ""
    segments = [part.strip() for part in str(corr_str).split(";") if part.strip()]
    authors = []
    affiliations = []
    current_author = ""
    current_affiliations = []

    def flush_current():
        if current_author:
            author = match_full_author_name(current_author, full_names)
            if author and author not in authors:
                authors.append(author)
            aff = "; ".join(current_affiliations).strip()
            if aff and aff not in affiliations:
                affiliations.append(aff)

    for segment in segments:
        if "email:" in segment.lower() or "@" in segment:
            flush_current()
            current_author = ""
            current_affiliations = []
            continue
        if not current_author:
            current_author = segment
            current_affiliations = []
        else:
            current_affiliations.append(segment)

    flush_current()
    return "; ".join(authors), "; ".join(affiliations)

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
    formatted_affils = format_indexed_affiliations(master_aff_list)

    formatted_authors = []
    for i, name in enumerate(full_names):
        indices = []
        if i < len(auth_entries):
            entry = auth_entries[i]
            indices = match_author_affiliations(entry, aff_dict, master_aff_list)
        if indices:
            formatted_authors.append(f"{name}({','.join(map(str, indices))})")
        else:
            formatted_authors.append(name)

   
    first_author_name = full_names[0] if full_names else ""
    first_author_affs = ""

    if full_names and len(auth_entries) > 0:
        first_entry = auth_entries[0]
        indices = match_author_affiliations(first_entry, aff_dict, master_aff_list)
        if indices:
            first_author_affs = "; ".join([aff for aff, idx in aff_dict.items() if idx in indices])
    
    if not first_author_affs and master_aff_list:
        first_author_affs = master_aff_list[0]
        
    if not first_author_affs and auth_with_aff_str:
        first_entry = auth_entries[0] if auth_entries else ""
        parts = first_entry.split(",", 1)
        if len(parts) > 1:
            first_author_affs = parts[1].strip()

    corr_str = safe_get(row, ["Correspondence Address", "通讯地址", "通信地址", "通讯作者地址", "联系地址"])
    corr_author_name, corr_author_affs = parse_scopus_correspondence(corr_str, full_names)

    date_val = normalize_date(safe_get(row, ["Year", "年份", "日期"]))
    lang_raw = safe_get(row, ["Language of Original Document", "文献原始语言", "语种", "原始文献语言"])
    lang = translate_language(lang_raw)

    pg_start = safe_get(row, ['Page start', '起始页', '起始页码'])
    pg_end = safe_get(row, ['Page end', '结束页', '结束页码'])
    if pg_start:
        page_val = f"{pg_start}-{pg_end}" if pg_end else pg_start
    else:
        page_val = safe_get(row, ["Art. No.", "文章编号", "论文编号"])

    return {
        "DOI": normalize_doi(safe_get(row, ["DOI", "数字对象唯一标识符"])),
        "题名": safe_get(row, ["Title", "Document title", "标题", "文献标题", "Article Title"]),
        "作者": "; ".join(formatted_authors),
        "第一作者单位": first_author_affs,
        "通讯作者单位": corr_author_affs,
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
        "通讯作者": corr_author_name,
        "SCOPUS_ID": safe_get(row, ["EID"]),
        "SCOPUSEID": safe_get(row, ["EID"]),
        "页数": safe_get(row, ["Page count", "页数"]),
        "作者单位": formatted_affils,
        "第一作者": first_author_name,
        "Scopus被引次数": safe_get(row, ["Cited by", "被引次数", "施引文献"]),
        "来源库": "SCOPUS",
    }


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

    addresses = safe_get(row, ["Addresses", "C1", "作者单位"])
    
    formatted_authors = authors_af
    formatted_affils = addresses
    first_author_aff = ""

    if addresses and '[' in addresses:
        pattern = re.compile(r'\[(.*?)\]\s*([^\[]+)')
        matches = pattern.findall(addresses)
        if matches:
            affil_list = []
            author_affil_map = {}
            
            for authors_in_bracket, affil in matches:
                affil = affil.strip().rstrip(';')
                if affil not in affil_list:
                    affil_list.append(affil)
                affil_idx = affil_list.index(affil) + 1
                
                for au in authors_in_bracket.split(';'):
                    au_key = normalize_author_match_key(au)
                    if not au_key:
                        continue
                    if au_key not in author_affil_map:
                        author_affil_map[au_key] = []
                    author_affil_map[au_key].append(affil_idx)

            last_name_affil_map = {}
            last_name_conflicts = set()
            for authors_in_bracket, _ in matches:
                for au in authors_in_bracket.split(';'):
                    au_key = normalize_author_match_key(au)
                    last_key = normalize_author_last_key(au)
                    if not au_key or not last_key:
                        continue
                    indices = tuple(sorted(set(author_affil_map.get(au_key, []))))
                    if last_key in last_name_affil_map and last_name_affil_map[last_key] != indices:
                        last_name_conflicts.add(last_key)
                    else:
                        last_name_affil_map[last_key] = indices
            
            fmt_aus = []
            for au in af_list:
                au_key = normalize_author_match_key(au)
                indices = author_affil_map.get(au_key)
                last_key = normalize_author_last_key(au)
                if not indices and last_key and last_key not in last_name_conflicts:
                    indices = list(last_name_affil_map.get(last_key, ()))
                if indices:
                    idx_str = ",".join(map(str, sorted(set(indices))))
                    fmt_aus.append(f"{au} ({idx_str})")
                else:
                    fmt_aus.append(au)
            
            formatted_authors = "; ".join(fmt_aus)
            formatted_affils = "; ".join([f"({i+1}) {aff}" for i, aff in enumerate(affil_list)])
            
            first_author_aff = affil_list[0] if affil_list else ""
            if af_list:
                first_key = normalize_author_match_key(af_list[0])
                first_indices = author_affil_map.get(first_key)
                first_last_key = normalize_author_last_key(af_list[0])
                if not first_indices and first_last_key and first_last_key not in last_name_conflicts:
                    first_indices = list(last_name_affil_map.get(first_last_key, ()))
                if first_indices:
                    first_author_aff = "; ".join(
                        affil_list[idx - 1]
                        for idx in sorted(set(first_indices))
                        if 0 < idx <= len(affil_list)
                    )
    else:
        if addresses:
            first_author_aff = addresses.split(';')[0].strip()

    # 提取通讯作者全名及单位
    rp_address = safe_get(row, ["Reprint Addresses", "RP", "通讯地址"])
    corr_author = ""
    corr_author_aff = ""
    if rp_address:
        rp_lower = rp_address.lower()
        if "(corresponding author)" in rp_lower or "(reprint author)" in rp_lower:
            idx = rp_address.find('(')
            idx2 = rp_address.find(')', idx)
            if idx != -1 and idx2 != -1:
                corr_author_short = rp_address[:idx].strip()
                corr_author_aff = rp_address[idx2+1:].strip()
                if corr_author_aff.startswith(","):
                    corr_author_aff = corr_author_aff[1:].strip()
                
                # 匹配全名
                corr_author = corr_author_short
                if corr_author_short and af_list:
                    short_last = corr_author_short.split(",")[0].strip().lower()
                    for au_full in af_list:
                        au_full_last = au_full.split(",")[0].strip().lower()
                        if short_last == au_full_last or short_last in au_full_last:
                            corr_author = au_full
                            break
        else:
            corr_author_aff = rp_address

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
        "URL": "",
        "语种": lang,
        "发表日期": final_date,
        "作者": formatted_authors,
        "第一作者": first_author,
        "通讯作者": corr_author,
        "通讯作者单位": corr_author_aff,
        "第一作者单位": first_author_aff,
        "作者单位": formatted_affils,
    }

    record["题名"] = safe_get(row, ["Article Title", "Title", "TI"])
    record["发表期刊"] = safe_get(row, ["Source Title", "Journal", "SO"])
    record["ISSN"] = safe_get(row, ["ISSN", "SN"])
    record["EISSN"] = safe_get(row, ["eISSN", "EISSN", "EI"])
    record["卷号"] = safe_get(row, ["Volume", "VL"])
    record["期号"] = safe_get(row, ["Issue", "IS"])
    record["页码"] = page_value
    record["资助项目"] = safe_get(row, ["Funding Orgs", "FU"])
    record["出版者"] = safe_get(row, ["Publisher", "PU"])
    record["原始文献类型"] = safe_get(row, ["Document Type", "DT"])
    record["发表状态"] = "在线发表" if safe_get(row, ["Early Access Date"]) else normalize_publication_status(
        safe_get(row, ["Publication Status", "Publication Stage"])
    )

    return record


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

    return {
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


def count_author_affiliation_markers(author_text):
    text = str(author_text or "")
    if not text or text.lower() == "nan":
        return 0
    return len(re.findall(r"\(\d+(?:,\d+)*\)", text))


# 合并
def merge_records(existing, new_data):
    for key, val in new_data.items():
        if key == "DOI":
            continue
        if val is None:
            continue
        sval = str(val)
        if not sval or sval == "nan":
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

        if key == "作者":
            existing_marker_count = count_author_affiliation_markers(existing.get(key, ""))
            new_marker_count = count_author_affiliation_markers(val)
            if new_marker_count > existing_marker_count:
                existing[key] = val
            elif key not in existing or not existing[key] or str(existing[key]) in ["nan", "nan-nan", "-"]:
                existing[key] = val
            continue

        if key not in existing or not existing[key] or str(existing[key]) in ["nan", "nan-nan", "-"]:
            existing[key] = val
            continue

        if key == "发表日期":
            if len(str(val)) > len(str(existing[key])):
                existing[key] = val

    return existing


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
    merged_db = {}
    publication_name_to_email = {}
    is_external_achievement = mode in {"external", "校外", "非本校成果", "校外成果"}

    print(f"准备处理 {len(input_paths)} 个文件...")
    alias_registry = build_scholar_alias_registry(
        accounts_path=accounts_path,
        article_library_path=article_library_path,
        alias_path=alias_path,
    )
    claim_filter_emails = parse_claim_email_filter(claim_email_filter) if is_external_achievement else []
    if is_external_achievement and str(claim_email_filter or "").strip():
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

                doi = record.get("DOI")
                if doi:
                    if doi in merged_db:
                        merged_db[doi] = merge_records(merged_db[doi], record)
                    else:
                        merged_db[doi] = record

        except Exception as e:
            print(f"读取错误 {file_path}: {e}")

    output_df = pd.DataFrame(list(merged_db.values()))

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
        "pending": sheet_counts.get("待确认", 0),
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
