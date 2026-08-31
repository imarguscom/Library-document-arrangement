import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter import (
    merge_records,
    normalize_doi,
    normalize_keywords,
    normalize_wos_index,
    process_ei_row,
    process_scopus_row,
    process_wos_row,
    read_normal_csv_robust,
    run_conversion,
    split_scopus_author_affiliation_entries,
)


def test_normalize_doi_strips_prefix_and_spaces():
    assert normalize_doi(" DOI: https://doi.org/10.1000/ABC  ") == "10.1000/abc"


def test_normalize_wos_index_preserves_multiple_indexes():
    raw = (
        "Science Citation Index Expanded (SCI-EXPANDED); "
        "Conference Proceedings Citation Index - Science (CPCI-S); "
        "Social Sciences Citation Index (SSCI); "
        "Arts & Humanities Citation Index (A&HCI); "
        "Emerging Sources Citation Index; "
        "Book Citation Index (BKCI)"
    )

    assert normalize_wos_index(raw) == "SCIE; CPCI-S; SSCI; AHCI; ESCI; BKCI"


def test_normalize_keywords_uses_english_semicolon_separator():
    raw = "speech processing | audio anti-spoofing|deep learning； pattern recognition\nbiometrics"

    assert normalize_keywords(raw) == (
        "speech processing; audio anti-spoofing; deep learning; pattern recognition; biometrics"
    )


def test_process_ei_row_keeps_author_and_affiliation_fields():
    row = pd.Series(
        {
            "DOI": "10.1/test",
            "Title": "EI Paper",
            "Author": "Wang, Jiawei; Li, Ming",
            "Author affiliation": "School A; School B",
            "Source": "Conference",
            "Accession number": "123",
            "Classification code": "456",
        }
    )
    record = process_ei_row(row)
    assert record["作者"] == "Wang, Jiawei; Li, Ming"
    assert record["第一作者"] == "Wang, Jiawei"
    assert record["作者单位"] == "School A; School B"
    assert record["第一作者单位"] == "School A"


def test_process_scopus_row_extracts_multiple_corresponding_authors():
    row = pd.Series(
        {
            "DOI": "10.1117/1.AP.8.1.014002",
            "Title": "Correspondence Test",
            "Author full names": "Su, Xiang (1); Wang, Dong (2); Han, Ting (3); Tang, Ben Zhong (4)",
            "Authors with affiliations": (
                "Su X., Shenzhen University, China, Guangdong University of Technology, China; "
                "Wang D., Shenzhen University, China; "
                "Han T., Shenzhen University, China; "
                "Tang B.Z., CUHK-Shenzhen, China"
            ),
            "Affiliations": "Shenzhen University, China; Guangdong University of Technology, China; CUHK-Shenzhen, China",
            "Correspondence Address": (
                "T. Han; Shenzhen University, China; email: hanting@szu.edu.cn; "
                "B.Z. Tang; CUHK-Shenzhen, China; email: tangbenz@cuhk.edu.cn"
            ),
            "EID": "2-s2.0-test",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Han, Ting; Tang, Ben Zhong"
    assert record["通讯作者单位"] == "Shenzhen University, China; CUHK-Shenzhen, China"
    assert "B.Z. Tang" not in record["通讯作者单位"]


def test_process_scopus_row_handles_frontend_parenthesized_affiliations():
    row = pd.Series(
        {
            "DOI": "10.1093/aje/kwae220",
            "Title": "Scopus Frontend Affiliation Test",
            "Author full names": (
                "Ali, Sheikh Taslim; Wang, Lin; Xu, Xiao Ke; Du, Zhanwei; Cowling, Benjamin J."
            ),
            "Affiliations": (
                "University of Cambridge, Cambridge, United Kingdom; "
                "The University of Hong Kong Li Ka Shing Faculty of Medicine, Hong Kong, Hong Kong; "
                "Dalian Minzu University, Dalian, China; "
                "Laboratory of Data Discovery for Health, Hong Kong, China"
            ),
            "Authors with affiliations": (
                "Ali S.T. (The University of Hong Kong Li Ka Shing Faculty of Medicine, Hong Kong, Hong Kong; "
                "Laboratory of Data Discovery for Health, Hong Kong, China); "
                "Wang L. (University of Cambridge, Cambridge, United Kingdom); "
                "Xu X.K. (Dalian Minzu University, Dalian, China); "
                "Du Z. (The University of Hong Kong Li Ka Shing Faculty of Medicine, Hong Kong, Hong Kong; "
                "Laboratory of Data Discovery for Health, Hong Kong, China); "
                "Cowling B.J. (The University of Hong Kong Li Ka Shing Faculty of Medicine, Hong Kong, Hong Kong; "
                "Laboratory of Data Discovery for Health, Hong Kong, China)"
            ),
            "EID": "2-s2.0-test",
        }
    )

    entries = split_scopus_author_affiliation_entries(row["Authors with affiliations"])
    record = process_scopus_row(row)

    assert len(entries) == 5
    assert "Ali, Sheikh Taslim(2,4)" in record["作者"]
    assert "Wang, Lin(1)" in record["作者"]
    assert "Xu, Xiao Ke(3)" in record["作者"]
    assert "Cowling, Benjamin J.(2,4)" in record["作者"]
    assert record["第一作者单位"] == (
        "The University of Hong Kong Li Ka Shing Faculty of Medicine, Hong Kong, Hong Kong; "
        "Laboratory of Data Discovery for Health, Hong Kong, China"
    )


def test_process_wos_row_matches_frontend_full_names_to_addresses():
    row = pd.Series(
        {
            "DOI": "10.1093/aje/kwae220",
            "Article Title": "WOS Frontend Affiliation Test",
            "Authors": "Ali, ST; Wang, L; Xu, XK; Wu, P; Cowling, BJ",
            "Author Full Names": (
                "Ali, Sheikh Taslim; Wang, Lin; Xu, Xiao-Ke; Wu, Peng; Cowling, Benjamin J."
            ),
            "Addresses": (
                "[Ali, Sheikh Taslim; Wu, Peng; Cowling, Benjamin J.] "
                "Univ Hong Kong, Sch Publ Hlth, Hong Kong, Peoples R China; "
                "[Ali, Sheikh Taslim; Wu, Peng; Cowling, Benjamin J.] "
                "Lab Data Discovery Hlth Ltd, Hong Kong, Peoples R China; "
                "[Wang, Lin] Univ Cambridge, Cambridge, England; "
                "[Xu, Xiao-Ke] Dalian Minzu Univ, Dalian, Peoples R China"
            ),
            "Reprint Addresses": (
                "Cowling, BJ (corresponding author), Univ Hong Kong, Sch Publ Hlth, Hong Kong, Peoples R China."
            ),
            "Source Title": "American Journal of Epidemiology",
            "Web of Science Index": "Science Citation Index Expanded (SCI-EXPANDED)",
        }
    )

    record = process_wos_row(row)

    assert "Ali, Sheikh Taslim (1,2)" in record["作者"]
    assert "Wang, Lin (3)" in record["作者"]
    assert "Xu, Xiao-Ke (4)" in record["作者"]
    assert "Wu, Peng (1,2)" in record["作者"]
    assert "Cowling, Benjamin J. (1,2)" in record["作者"]
    assert record["第一作者单位"] == (
        "Univ Hong Kong, Sch Publ Hlth, Hong Kong, Peoples R China; "
        "Lab Data Discovery Hlth Ltd, Hong Kong, Peoples R China"
    )
    assert record["通讯作者"] == "Cowling, Benjamin J."


def test_merge_records_prefers_author_text_with_more_affiliation_markers():
    existing = {
        "DOI": "10.1109/lmwt.2026.3659596",
        "作者": "Liu, Junyi; Blu, Thierry; Wu, Ke-Li",
        "作者单位": "",
        "来源库": "WOS",
    }
    new_data = {
        "DOI": "10.1109/lmwt.2026.3659596",
        "作者": "Liu, Junyi(1); Blu, Thierry(1); Wu, Ke Li(1)",
        "作者单位": "(1) Chinese University of Hong Kong, Hong Kong, Hong Kong",
        "来源库": "SCOPUS",
    }

    merged = merge_records(existing, new_data)

    assert merged["作者"] == "Liu, Junyi(1); Blu, Thierry(1); Wu, Ke Li(1)"
    assert merged["作者单位"] == "(1) Chinese University of Hong Kong, Hong Kong, Hong Kong"
    assert merged["来源库"] == "WOS; SCOPUS"


def test_run_conversion_routes_article_conference_type_conflict_to_pending_review(tmp_path):
    doi = "10.1000/article-first-conference-second"
    wos_path = tmp_path / "wos.xlsx"
    scopus_path = tmp_path / "scopus.xlsx"
    alias_path = tmp_path / "aliases.xlsx"
    output_path = tmp_path / "out.xlsx"
    pd.DataFrame(
        [{
            "UT": "WOS:000001",
            "Article Title": "Article-first duplicate",
            "Authors": "Author, A",
            "DOI": doi,
            "Document Type": "Article",
        }]
    ).to_excel(wos_path, index=False)
    pd.DataFrame(
        [{
            "EID": "2-s2.0-conference",
            "Title": "Conference-second duplicate",
            "Authors": "Author, A",
            "DOI": doi,
            "Document Type": "Conference Paper",
        }]
    ).to_excel(scopus_path, index=False)
    pd.DataFrame(columns=["别名", "姓名", "邮箱"]).to_excel(alias_path, index=False)

    run_conversion(
        [str(wos_path), str(scopus_path)],
        str(output_path),
        "local",
        alias_path=str(alias_path),
    )

    all_records = pd.read_excel(output_path, sheet_name="全部数据", dtype=str)
    assert all_records.empty
    pending_records = pd.read_excel(output_path, sheet_name="待确认", dtype=str).fillna("")
    assert pending_records["DOI"].tolist() == [doi]
    assert pending_records["原始文献类型"].tolist() == ["Article; Conference Paper"]
    assert "来源文献类型冲突" in pending_records.loc[0, "文献类型审核原因"]


def test_process_scopus_row_normalizes_keywords():
    row = pd.Series(
        {
            "DOI": "10.1/keywords",
            "Title": "Keyword Test",
            "Author Keywords": "speech processing | audio anti-spoofing|deep learning",
            "EID": "2-s2.0-keyword",
        }
    )

    record = process_scopus_row(row)

    assert record["关键词"] == "speech processing; audio anti-spoofing; deep learning"


def test_read_normal_csv_detects_semicolon_separator():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sample.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("A;B\n1;2\n")
        df = read_normal_csv_robust(path)
    assert list(df.columns) == ["A", "B"]
    assert df.iloc[0]["A"] == "1"
