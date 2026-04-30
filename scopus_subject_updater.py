import requests
import urllib.parse
import xml.etree.ElementTree as ET
import pandas as pd
from time import sleep

API_KEY = "0c04fccbb9e77bce241b397054c99792"
INPUT_XLSX = "result.xlsx"
OUTPUT_XLSX = "result_with_subjects.xlsx"
SHEET_NAME = 0
DOI_COLUMN = "DOI"
EID_COLUMN = "SCOPUSEID"

def fetch_xml(doi: str, eid: str) -> str:
    doi = (doi or "").strip()
    eid = (eid or "").strip()

    if doi:
        url = f"https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}"
    elif eid:
        url = f"https://api.elsevier.com/content/abstract/eid/{urllib.parse.quote(eid)}"
    else:
        return ""

    headers = {
        "X-ELS-APIKey": API_KEY,
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

def main():
    df_raw = pd.read_excel(INPUT_XLSX, sheet_name=SHEET_NAME, dtype=str)

    if DOI_COLUMN not in df_raw.columns:
        raise ValueError(f"找不到指定 DOI 列：{DOI_COLUMN}")
    
    if EID_COLUMN not in df_raw.columns:
        df_raw[EID_COLUMN] = ""

    df_raw[DOI_COLUMN] = df_raw[DOI_COLUMN].fillna("").str.strip()
    df_raw[EID_COLUMN] = df_raw[EID_COLUMN].fillna("").str.strip()

    tasks = df_raw[[DOI_COLUMN, EID_COLUMN]].drop_duplicates()
    tasks = tasks[(tasks[DOI_COLUMN] != "") | (tasks[EID_COLUMN] != "")]

    records = []
    total = len(tasks)

    for i, (doi, eid) in enumerate(tasks.values, start=1):
        print(f"[{i}/{total}] DOI={doi} | EID={eid} ...", end=" ")

        try:
            xml_text = fetch_xml(doi, eid)
            names_str, codes_str = parse_subjects(xml_text)
            if names_str or codes_str:
                print("OK")
            else:
                print("无学科信息")
        except Exception as e:
            print("出错：", e)
            names_str, codes_str = "", ""

        records.append({
            DOI_COLUMN: doi,
            EID_COLUMN: eid,
            "Scopus_subject_names": names_str,
            "Scopus_subject_codes": codes_str,
        })

        sleep(0.2)

    if records:
        df_sub = pd.DataFrame(records)
        df_merged = df_raw.merge(df_sub, how="left", on=[DOI_COLUMN, EID_COLUMN])
        df_merged.to_excel(OUTPUT_XLSX, index=False)
        print("完成，已写入：", OUTPUT_XLSX)
    else:
        print("无有效 DOI 或 EID，未执行查询。")

if __name__ == "__main__":
    main()