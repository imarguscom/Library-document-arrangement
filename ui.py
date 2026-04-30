import customtkinter as ctk
import tkinter.filedialog as filedialog
import threading
import sys
import pandas as pd
import requests
import urllib.parse
import xml.etree.ElementTree as ET
import re
from time import sleep

# ================= 配置区域 =================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

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

DEFAULT_DATE_SUFFIX = "-01-01"

LANG_MAP = {
    "english": "英语", "chinese": "中文", "german": "德语", "french": "法语",
    "spanish": "西班牙语", "japanese": "日语", "russian": "俄语", "korean": "韩语",
    "italian": "意大利语", "portuguese": "葡萄牙语", "polish": "波兰语",
    "dutch": "荷兰语", "arabic": "阿拉伯语"
}

# ================= 数据清洗核心逻辑 =================

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
    return re.sub(r"\s*\(\d+\)", "", str(name_str)).strip()

def normalize_date(d1, d2=""):
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
    if not lang_str or pd.isna(lang_str):
        return ""
    s = str(lang_str).strip().lower()
    for eng, chn in LANG_MAP.items():
        if eng in s:
            return chn
    return str(lang_str).strip()

def parse_scopus_affiliations(aff_str):
    if pd.isna(aff_str) or not str(aff_str).strip():
        return {}, []
    aff_list = [a.strip() for a in str(aff_str).split(";") if a.strip()]
    aff_dict = {}
    master_list = []
    for idx, aff in enumerate(aff_list):
        aff_dict[aff] = idx + 1
        master_list.append(aff)
    return aff_dict, master_list

def match_author_affiliations(auth_entry, aff_dict, master_aff_list):
    indices = []
    for aff_name in master_aff_list:
        if aff_name in auth_entry:
            indices.append(aff_dict[aff_name])
    return sorted(list(set(indices)))

def safe_get(row, keys):
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
    auth_entries = str(auth_with_aff_str).split(";") if auth_with_aff_str else []

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
    corr_author_name = ""
    corr_author_affs = ""

    if corr_str:
        parts = str(corr_str).split(";")
        if parts:
            corr_author_short = parts[0].strip()
            corr_author_name = corr_author_short  
            
            if corr_author_short and full_names:
                short_last = corr_author_short.split(",")[0].strip().lower()
                for fn in full_names:
                    fn_last = fn.split(",")[0].strip().lower()
                    if short_last == fn_last or short_last in fn_last or fn_last in short_last:
                        corr_author_name = fn
                        break
        
        aff_parts = []
        for p in parts[1:]:
            if "email:" in p.lower() or "@" in p:
                continue
            aff_parts.append(p.strip())
        
        corr_author_affs = "; ".join(aff_parts)
        
        if not corr_author_affs:
            c_clean = re.sub(r'(?i)email:.*', '', str(corr_str)).strip(' ;')
            short_name = parts[0].strip() if parts else ""
            if c_clean.startswith(short_name) and len(c_clean) > len(short_name):
                c_clean = c_clean[len(short_name):].strip(' ,;')
            corr_author_affs = c_clean

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
        "关键词": safe_get(row, ["Author Keywords", "作者关键词", "作者关键字"]),
        "URL": safe_get(row, ["Link", "链接"]),
        "收录类别": "SCOPUS",
        "语种": lang,
        "资助项目": safe_get(row, ["Funding Details", "资助详细信息", "出资详情", "资金资助文本"]),
        "出版者": safe_get(row, ["Publisher", "出版商"]),
        "原始文献类型": safe_get(row, ["Document Type", "文献类型"]),
        "发表状态": safe_get(row, ["Publication Stage", "出版阶段"]),
        "参考文献": safe_get(row, ["References", "参考文献"]),
        "通讯作者": corr_author_name,
        "SCOPUS_ID": safe_get(row, ["EID"]),
        "SCOPUSEID": safe_get(row, ["EID"]),
        "页数": safe_get(row, ["Page count", "页数"]),
        "作者单位": auth_with_aff_str if auth_with_aff_str else aff_str,
        "第一作者": first_author_name,
        "Scopus被引次数": safe_get(row, ["Cited by", "被引次数", "施引文献"]),
        "来源库": "SCOPUS",
    }

def process_wos_row(row):
    doi = normalize_doi(safe_get(row, ["DOI", "DI"]))
    pub_date = safe_get(row, ["Publication Date", "PD"])
    pub_year = safe_get(row, ["Publication Year", "PY"])
    final_date = normalize_date(pub_date, pub_year)

    wos_cat = safe_get(row, ["WoS Categories", "Web of Science Categories", "WC", "Subject Category"])

    authors_af = safe_get(row, ["Author Full Names", "AF", "作者(全名)", "作者全名"])
    if not authors_af:
        authors_af = safe_get(row, ["Authors", "AU", "作者"])
    
    af_list = [x.strip() for x in str(authors_af).split(';')] if authors_af else []
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
                    au = au.strip().lower()
                    if au not in author_affil_map:
                        author_affil_map[au] = []
                    author_affil_map[au].append(affil_idx)
            
            fmt_aus = []
            for au in af_list:
                au_lower = au.lower()
                indices = author_affil_map.get(au_lower)
                if not indices:
                    for k, v in author_affil_map.items():
                        if k in au_lower or au_lower in k:
                            indices = v
                            break
                if indices:
                    idx_str = ",".join(map(str, sorted(set(indices))))
                    fmt_aus.append(f"{au} ({idx_str})")
                else:
                    fmt_aus.append(au)
            
            formatted_authors = "; ".join(fmt_aus)
            formatted_affils = "; ".join([f"({i+1}) {aff}" for i, aff in enumerate(affil_list)])
            
            first_author_aff = affil_list[0] if affil_list else ""
            if af_list:
                first_au_lower = af_list[0].lower()
                for k, v in author_affil_map.items():
                    if k in first_au_lower or first_au_lower in k:
                        if v:
                            first_author_aff = affil_list[v[0]-1]
                        break
    else:
        if addresses:
            first_author_aff = addresses.split(';')[0].strip()

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

    record = {
        "DOI": doi,
        "WOS记录号": safe_get(row, ["UT (Unique WOS ID)", "UT", "Accession Number"]),
        "WOS研究方向": safe_get(row, ["Research Areas", "SC"]),
        "WOS类目": wos_cat,
        "SCI被引次数": safe_get(row, ["Times Cited, All Databases", "TC"]),
        "影响因子": safe_get(row, ["Impact Factor", "IF", "Journal Impact Factor"]),
        "收录类别": "SCIE",
        "来源库": "WOS",
        "语种": lang,
        "发表日期": final_date,
        "作者": formatted_authors,
        "第一作者": first_author,
        "通讯作者": corr_author,
        "通讯作者单位": corr_author_aff,
        "第一作者单位": first_author_aff,
        "作者单位": formatted_affils,
    }

    record["题名"] = safe_get(row, ["Article Title", "TI"])
    record["发表期刊"] = safe_get(row, ["Source Title", "SO"])
    record["ISSN"] = safe_get(row, ["ISSN", "SN"])
    record["EISSN"] = safe_get(row, ["eISSN", "EI"])
    record["卷号"] = safe_get(row, ["Volume", "VL"])
    record["期号"] = safe_get(row, ["Issue", "IS"])
    record["页码"] = f"{safe_get(row, ['Start Page','BP'])}-{safe_get(row, ['End Page','EP'])}"
    record["资助项目"] = safe_get(row, ["Funding Orgs", "FU"])
    record["出版者"] = safe_get(row, ["Publisher", "PU"])
    record["原始文献类型"] = safe_get(row, ["Document Type", "DT"])

    return record

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
    first_author = ""
    if authors:
        first_author = authors.split(";")[0].strip()

    affiliations = safe_get(row, ["Author affiliation", "Author Affiliation", "Affiliation", "作者单位", "机构"])
    first_author_aff = ""
    if affiliations:
        first_author_aff = affiliations.split(";")[0].strip()

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
        "EI入藏号": safe_get(row, ["Accession number"]),
        "EI主题词": ei_terms,
        "EI分类号": safe_get(row, ["Classification code"]),
        "收录类别": "EI",
        "来源库": "EI",
    }

def merge_records(existing, new_data):
    for key, val in new_data.items():
        if key == "DOI":
            continue
        if val is None:
            continue
        sval = str(val)
        if not sval or sval == "nan":
            continue

        if key in ["收录类别", "来源库"]:
            if key in existing and existing[key]:
                if sval not in existing[key]:
                    existing[key] += "; " + sval
            else:
                existing[key] = sval
            continue

        if key not in existing or not existing[key] or str(existing[key]) in ["nan", "nan-nan", "-"]:
            existing[key] = val
            continue

        if key == "发表日期":
            if len(str(val)) > len(str(existing[key])):
                existing[key] = val

    return existing

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

# ================= 文章查询 API =================

def fetch_xml(doi: str, eid: str, api_key: str) -> str:
    doi = (doi or "").strip()
    eid = (eid or "").strip()

    if doi:
        url = f"https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}"
    elif eid:
        url = f"https://api.elsevier.com/content/abstract/eid/{urllib.parse.quote(eid)}"
    else:
        return ""

    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/xml"
    }
    params = {"view": "FULL"}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.text

def parse_subjects(xml_text: str):
    if not xml_text:
        return "", ""

    ns = {"ab": "http://www.elsevier.com/xml/svapi/abstract/dtd"}
    root = ET.fromstring(xml_text)

    subject_areas = []
    for sa in root.findall(".//ab:subject-areas/ab:subject-area", ns):
        code = sa.attrib.get("code")
        name = (sa.text or "").strip()
        if code or name:
            subject_areas.append((code, name))

    if not subject_areas:
        return "", ""

    names_str = "; ".join(name for code, name in subject_areas if name)
    codes_str = "; ".join(code for code, name in subject_areas if code)
    return names_str, codes_str

# ================= UI 界面 =================

class RedirectText:
    def __init__(self, text_widget):
        self.text_widget = text_widget
    def write(self, string):
        self.text_widget.insert(ctk.END, string)
        self.text_widget.see(ctk.END)
    def flush(self): pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("文献数据处理工具")
        self.geometry("750x650")
        self.input_files = []

        self.api_label = ctk.CTkLabel(self, text="Scopus API Key:", font=("Arial", 14, "bold"))
        self.api_label.grid(row=0, column=0, padx=20, pady=(20, 0), sticky="w")
        self.api_entry = ctk.CTkEntry(self, width=400, placeholder_text="若为空，则仅合并文件跳过文章查询")
        self.api_entry.insert(0, "0c04fccbb9e77bce241b397054c99792")
        self.api_entry.grid(row=0, column=1, padx=20, pady=(20, 0), sticky="w")

        self.in_label = ctk.CTkLabel(self, text="选择原始数据:", font=("Arial", 14, "bold"))
        self.in_label.grid(row=1, column=0, padx=20, pady=(15, 0), sticky="w")
        self.in_entry = ctk.CTkEntry(self, width=400, placeholder_text="支持多选 CSV/Excel/TXT")
        self.in_entry.grid(row=1, column=1, padx=20, pady=(15, 0), sticky="w")
        self.in_btn = ctk.CTkButton(self, text="浏览多文件...", width=90, command=self.browse_inputs)
        self.in_btn.grid(row=1, column=2, padx=10, pady=(15, 0))

        self.out_label = ctk.CTkLabel(self, text="保存最终结果:", font=("Arial", 14, "bold"))
        self.out_label.grid(row=2, column=0, padx=20, pady=(15, 0), sticky="w")
        self.out_entry = ctk.CTkEntry(self, width=400)
        self.out_entry.grid(row=2, column=1, padx=20, pady=(15, 0), sticky="w")
        self.out_btn = ctk.CTkButton(self, text="选择保存...", width=90, command=self.browse_output)
        self.out_btn.grid(row=2, column=2, padx=10, pady=(15, 0))

        self.run_btn = ctk.CTkButton(self, text="开始运行", font=("Arial", 16, "bold"), command=self.start_processing)
        self.run_btn.grid(row=3, column=0, columnspan=3, pady=(25, 10))

        self.log_box = ctk.CTkTextbox(self, width=700, height=300, font=("Consolas", 12))
        self.log_box.grid(row=4, column=0, columnspan=3, padx=20, pady=(10, 20))
        sys.stdout = RedirectText(self.log_box)

    def browse_inputs(self):
        filepaths = filedialog.askopenfilenames(filetypes=[("Data files", "*.xlsx *.xls *.csv *.txt")])
        if filepaths:
            self.input_files = list(filepaths)
            self.in_entry.delete(0, ctk.END)
            self.in_entry.insert(0, f"已选中 {len(filepaths)} 个文件")

    def browse_output(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if filepath:
            self.out_entry.delete(0, ctk.END)
            self.out_entry.insert(0, filepath)

    def start_processing(self):
        self.run_btn.configure(state="disabled", text="运行中...")
        self.log_box.delete("0.0", ctk.END)
        api_key = self.api_entry.get().strip()
        out_file = self.out_entry.get().strip()

        if not self.input_files or not out_file:
            print("错误：请确保已选择输入文件并设置保存位置。")
            self.run_btn.configure(state="normal", text="开始运行")
            return

        threading.Thread(target=self.run_pipeline, args=(api_key, self.input_files, out_file)).start()

    def run_pipeline(self, api_key, input_files, out_file):
        try:
            print("================ 第一阶段：合并与清洗 ================")
            merged_db = {}
            for file_path in input_files:
                print(f"正在读取: {file_path}")
                try:
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

                        doi = record.get("DOI")
                        if doi:
                            if doi in merged_db:
                                merged_db[doi] = merge_records(merged_db[doi], record)
                            else:
                                merged_db[doi] = record

                except Exception as e:
                    print(f"读取错误 {file_path}: {e}")

            output_df = pd.DataFrame(list(merged_db.values()))
            
            for col in TARGET_COLUMNS:
                if col not in output_df.columns:
                    output_df[col] = ""
                    
            print(f"合并结束，共有 {len(output_df)} 条记录。")

            print("\n================ 第二阶段：按文章补充学科信息 ================")
            if not api_key:
                print("API Key为空，跳过该步骤。")
                df_merged = output_df
            else:
                df_raw = output_df.copy()
                
                if "DOI" not in df_raw.columns: df_raw["DOI"] = ""
                if "SCOPUSEID" not in df_raw.columns: df_raw["SCOPUSEID"] = ""
                
                df_raw["DOI"] = df_raw["DOI"].fillna("").str.strip()
                df_raw["SCOPUSEID"] = df_raw["SCOPUSEID"].fillna("").str.strip()

                tasks = df_raw[["DOI", "SCOPUSEID"]].drop_duplicates()
                tasks = tasks[(tasks["DOI"] != "") | (tasks["SCOPUSEID"] != "")]

                records = []
                total = len(tasks)
                print(f"发现 {total} 条文章记录，开始查询...")

                for i, (doi, eid) in enumerate(tasks.values, start=1):
                    print(f"[{i}/{total}] DOI={doi} | EID={eid} ... ", end="")
                    try:
                        xml_text = fetch_xml(doi, eid, api_key)
                        names_str, codes_str = parse_subjects(xml_text)
                        if names_str or codes_str:
                            print("OK")
                        else:
                            print("无学科信息")
                    except Exception as e:
                        print("出错:", e)
                        names_str, codes_str = "", ""

                    records.append({
                        "DOI": doi,
                        "SCOPUSEID": eid,
                        "Scopus学科分类": names_str
                    })
                    sleep(0.2)

                if records:
                    df_sub = pd.DataFrame(records)
                    df_merged = df_raw.drop(columns=["Scopus学科分类"], errors="ignore").merge(df_sub, how="left", on=["DOI", "SCOPUSEID"])
                else:
                    df_merged = df_raw

            print("\n================ 第三阶段：保存文件 ================")
            df_final = df_merged[TARGET_COLUMNS]
            df_final.to_excel(out_file, index=False)
            print(f"完成，已保存至：\n{out_file}")

        except Exception as e:
            print(f"\n严重错误: {e}")
        finally:
            self.run_btn.configure(state="normal", text="开始运行")

if __name__ == "__main__":
    app = App()
    app.mainloop()