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
from scope_rules import split_output_frames


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


def test_process_scopus_row_uses_author_affiliation_entry_for_corresponding_author_unit():
    row = pd.Series(
        {
            "DOI": "10.1000/scopus-corresponding-affiliation",
            "Title": "Scopus Corresponding Author Affiliation Test",
            "Author full names": "Du, Jian; Xing, Weiwei; Li, Ming",
            "Affiliations": (
                "Beijing Jiaotong University, Beijing, China; "
                "Guangdong Laboratory of Artificial Intelligence, Shenzhen, China"
            ),
            "Authors with affiliations": (
                "Du J. (Beijing Jiaotong University, Beijing, China); "
                "Xing W. (Beijing Jiaotong University, Beijing, China); "
                "Li M. (Guangdong Laboratory of Artificial Intelligence, Shenzhen, China)"
            ),
            "Corresponding Author": "Xing, Weiwei",
            "Correspondence Address": "",
            "EID": "2-s2.0-corresponding-affiliation",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Xing, Weiwei"
    assert record["通讯作者单位"] == "Beijing Jiaotong University, Beijing, China"


def test_process_scopus_row_keeps_ambiguous_initial_match_unresolved():
    row = pd.Series(
        {
            "DOI": "10.1000/scopus-ambiguous-corresponding-affiliation",
            "Title": "Ambiguous Scopus Corresponding Author Test",
            "Author full names": "Li, Ming; Li, Mei",
            "Affiliations": "Institute A; Institute B",
            "Authors with affiliations": "Li M. (Institute A); Li M. (Institute B)",
            "Corresponding Author": "Li, Ming",
            "Correspondence Address": "",
            "EID": "2-s2.0-ambiguous-corresponding-affiliation",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Li, Ming"
    assert record["通讯作者单位"] == ""


def test_process_scopus_row_does_not_override_present_correspondence_address():
    row = pd.Series(
        {
            "DOI": "10.1000/scopus-present-correspondence-address",
            "Title": "Present Scopus Correspondence Address Test",
            "Author full names": "Du, Jian; Xing, Weiwei",
            "Affiliations": "Institute A; Institute B",
            "Authors with affiliations": "Du J. (Institute A); Xing W. (Institute B)",
            "Corresponding Author": "Xing, Weiwei",
            "Correspondence Address": "Xing, W.; email: xing@example.org",
            "EID": "2-s2.0-present-correspondence-address",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Xing, Weiwei"
    assert record["通讯作者单位"] == ""


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


def test_process_wos_row_does_not_infer_first_author_affiliation_without_author_tags():
    row = pd.Series(
        {
            "DOI": "10.1000/no-author-address-links",
            "Article Title": "Legacy WOS Address Test",
            "Author Full Names": "Pei, Jian; Lin, Xuemin",
            "Addresses": "Simon Fraser Univ, Burnaby, Canada; Univ New South Wales, Sydney, Australia",
        }
    )

    record = process_wos_row(row)

    assert record["作者"] == "Pei, Jian; Lin, Xuemin"
    assert record["作者单位"] == "Simon Fraser Univ, Burnaby, Canada; Univ New South Wales, Sydney, Australia"
    assert record["第一作者单位"] == ""


def test_process_wos_row_keeps_bare_addresses_unlinked_in_mixed_format():
    row = pd.Series(
        {
            "DOI": "10.1000/mixed-author-address-links",
            "Article Title": "Mixed WOS Address Test",
            "Author Full Names": "Ma, Chunyang; Zhang, Rui; Lin, Xuemin",
            "Addresses": (
                "[Zhang, Rui] Univ Melbourne, Melbourne, Australia; "
                "Zhejiang Univ, Hangzhou, China; Univ New South Wales, Sydney, Australia"
            ),
        }
    )

    record = process_wos_row(row)

    assert record["作者"] == "Ma, Chunyang; Zhang, Rui (1); Lin, Xuemin"
    assert record["作者单位"] == (
        "(1) Univ Melbourne, Melbourne, Australia; Zhejiang Univ, Hangzhou, China; "
        "Univ New South Wales, Sydney, Australia"
    )
    assert record["第一作者单位"] == ""


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


def test_run_conversion_keeps_article_conference_records_separate(tmp_path):
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
    assert all_records["DOI"].tolist() == [doi, doi]
    assert all_records["原始文献类型"].tolist() == ["Article", "Conference Paper"]
    assert all_records["来源库"].tolist() == ["WOS", "SCOPUS"]
    for sheet, expected_type in [("期刊论文", "Article"), ("会议论文", "Conference Paper")]:
        records = pd.read_excel(output_path, sheet_name=sheet, dtype=str).fillna("")
        assert records["原始文献类型"].tolist() == [expected_type]
    for sheet in ["待复核_其他", "待复核_可尝试原文补全"]:
        pending_records = pd.read_excel(output_path, sheet_name=sheet, dtype=str).fillna("")
        assert not pending_records["复核原因"].str.contains("文献类型冲突").any()


def test_run_conversion_supports_each_source_as_the_only_input(tmp_path):
    alias_path = tmp_path / "aliases.xlsx"
    pd.DataFrame(columns=["别名", "姓名", "邮箱"]).to_excel(alias_path, index=False)
    source_cases = [
        (
            "wos.xlsx",
            pd.DataFrame(
                [{
                    "UT": "WOS:single-source",
                    "Article Title": "Single WOS Article",
                    "Authors": "Author, A",
                    "DOI": "10.1000/single-wos",
                    "Document Type": "Article",
                }]
            ),
        ),
        (
            "scopus.xlsx",
            pd.DataFrame(
                [{
                    "EID": "2-s2.0-single-source",
                    "Title": "Single Scopus Article",
                    "Authors": "Author, A",
                    "DOI": "10.1000/single-scopus",
                    "Document Type": "Article",
                }]
            ),
        ),
        (
            "ei.csv",
            pd.DataFrame(
                [{
                    "Accession number": "EI-single-source",
                    "Classification code": "001",
                    "Title": "Single EI Article",
                    "Author": "Author, A",
                    "DOI": "10.1000/single-ei",
                    "Document type": "Article",
                }]
            ),
        ),
    ]

    for filename, frame in source_cases:
        input_path = tmp_path / filename
        output_path = tmp_path / f"{input_path.stem}_out.xlsx"
        if input_path.suffix == ".csv":
            frame.to_csv(input_path, index=False)
        else:
            frame.to_excel(input_path, index=False)

        stats = run_conversion(
            [str(input_path)],
            str(output_path),
            "local",
            alias_path=str(alias_path),
        )

        assert stats["total"] == 1
        all_records = pd.read_excel(output_path, sheet_name="全部数据", dtype=str).fillna("")
        journal_records = pd.read_excel(output_path, sheet_name="期刊论文", dtype=str).fillna("")
        assert all_records["题名"].tolist() == [frame.iloc[0]["Title"] if "Title" in frame.columns else frame.iloc[0]["Article Title"]]
        assert journal_records["DOI"].tolist() == [frame.iloc[0]["DOI"]]


def test_run_conversion_single_source_maps_records_without_doi_or_deduplication(tmp_path):
    input_path = tmp_path / "scopus_single_source.xlsx"
    alias_path = tmp_path / "aliases.xlsx"
    output_path = tmp_path / "out.xlsx"
    pd.DataFrame(
        [
            {
                "EID": "2-s2.0-no-doi",
                "Title": "Single source without DOI",
                "Authors": "Author, A",
                "Document Type": "Article",
            },
            {
                "EID": "2-s2.0-duplicate-one",
                "Title": "First row sharing a DOI",
                "Authors": "Author, A",
                "DOI": "10.1000/single-source-duplicate",
                "Document Type": "Article",
            },
            {
                "EID": "2-s2.0-duplicate-two",
                "Title": "Second row sharing a DOI",
                "Authors": "Author, A",
                "DOI": "10.1000/single-source-duplicate",
                "Document Type": "Article",
            },
        ]
    ).to_excel(input_path, index=False)
    pd.DataFrame(columns=["别名", "姓名", "邮箱"]).to_excel(alias_path, index=False)

    stats = run_conversion(
        [str(input_path)],
        str(output_path),
        "local",
        alias_path=str(alias_path),
    )

    all_records = pd.read_excel(output_path, sheet_name="全部数据", dtype=str).fillna("")
    assert stats["total"] == 3
    assert all_records["题名"].tolist() == [
        "Single source without DOI",
        "First row sharing a DOI",
        "Second row sharing a DOI",
    ]
    assert all_records["DOI"].tolist() == ["", "10.1000/single-source-duplicate", "10.1000/single-source-duplicate"]


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


def test_process_scopus_row_maps_subject_areas_and_corresponding_author():
    row = pd.Series(
        {
            "DOI": "10.1/scopus-fields",
            "Title": "Scopus field mapping",
            "Corresponding Author": "Gao, Xiaoxue",
            "Subject Areas": "Signal Processing; Applied Mathematics",
            "EID": "2-s2.0-scopus-fields",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Gao, Xiaoxue"
    assert record["Scopus学科分类"] == "Signal Processing; Applied Mathematics"


def test_merge_records_prefers_scopus_corresponding_author_and_keeps_wos_fallback():
    wos_record = {
        "DOI": "10.1/corresponding-author",
        "通讯作者": "Wang, J.",
        "来源库": "WOS",
    }
    scopus_record = {
        "DOI": "10.1/corresponding-author",
        "通讯作者": "Wang, Jianwei",
        "来源库": "SCOPUS",
    }

    merged = merge_records(wos_record.copy(), scopus_record)
    assert merged["通讯作者"] == "Wang, Jianwei"

    scopus_without_corresponding_author = {
        "DOI": "10.1/corresponding-author",
        "通讯作者": "",
        "来源库": "SCOPUS",
    }
    fallback = merge_records(wos_record.copy(), scopus_without_corresponding_author)
    assert fallback["通讯作者"] == "Wang, J."


def test_read_normal_csv_detects_semicolon_separator():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sample.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("A;B\n1;2\n")
        df = read_normal_csv_robust(path)
    assert list(df.columns) == ["A", "B"]
    assert df.iloc[0]["A"] == "1"


def test_process_scopus_row_matches_affiliations_by_author_identity_not_entry_position():
    row = pd.Series(
        {
            "DOI": "10.1000/scopus-reordered-author-entries",
            "Title": "Scopus reordered author entries",
            "Author full names": "Alpha, Alice; Bravo, Bob",
            "Affiliations": "Institute B; Institute A",
            # The entry order is intentionally different from Author full names.
            "Authors with affiliations": "Bravo B. (Institute B); Alpha A. (Institute A)",
            "EID": "2-s2.0-reordered-author-entries",
        }
    )

    record = process_scopus_row(row)

    assert record["作者"] == "Alpha, Alice(2); Bravo, Bob(1)"
    assert record["作者单位"] == "(1) Institute B; (2) Institute A"
    assert record["第一作者单位"] == "Institute A"
    assert record["作者—单位关联来源"] == "SCOPUS"


def test_process_scopus_correspondence_resolves_initials_uniquely_not_first_surname_match():
    row = pd.Series(
        {
            "DOI": "10.1000/scopus-correspondence-initials",
            "Title": "Scopus correspondence initials",
            "Author full names": "Li, Wei; Li, Ming",
            "Affiliations": "Institute Wei; Institute Ming",
            "Authors with affiliations": "Li W. (Institute Wei); Li M. (Institute Ming)",
            "Correspondence Address": "Li, M.; Institute Ming; email: ming@example.org",
            "EID": "2-s2.0-correspondence-initials",
        }
    )

    record = process_scopus_row(row)

    assert record["通讯作者"] == "Li, Ming"
    assert record["通讯作者单位"] == "Institute Ming"
    assert record["通讯作者来源"] == "SCOPUS: Correspondence Address"
    assert record["通讯作者单位来源"] == "SCOPUS: Correspondence Address"


def _paired_wos_record(doi, corresponding_author="Alpha, A", corresponding_affiliation="Institute A"):
    return process_wos_row(
        pd.Series(
            {
                "DOI": doi,
                "Article Title": "Paired author affiliations",
                "Author Full Names": "Alpha, Alice; Bravo, Bob",
                "Addresses": "[Alpha, Alice] Institute A; [Bravo, Bob] Institute B",
                "Reprint Addresses": (
                    f"{corresponding_author} (corresponding author), {corresponding_affiliation}"
                ),
                "Document Type": "Article",
            }
        )
    )


def _paired_scopus_record(doi, alpha_affiliation="Institute A", bravo_affiliation="Institute B", corresponding_author=""):
    return process_scopus_row(
        pd.Series(
            {
                "DOI": doi,
                "Title": "Paired author affiliations",
                "Author full names": "Alpha, Alice; Bravo, Bob",
                "Affiliations": "Institute B; Institute A",
                # Deliberately reversed entry order and affiliation numbering.
                "Authors with affiliations": (
                    f"Bravo B. ({bravo_affiliation}); Alpha A. ({alpha_affiliation})"
                ),
                "Corresponding Author": corresponding_author,
                "Correspondence Address": "",
                "EID": "2-s2.0-paired-author-affiliations",
                "Document Type": "Article",
            }
        )
    )


def test_merge_records_rerenders_author_numbers_from_one_selected_relationship_bundle():
    doi = "10.1000/paired-author-affiliations"
    wos_record = _paired_wos_record(doi)
    scopus_record = _paired_scopus_record(doi)

    merged = merge_records(wos_record, scopus_record)

    # Scopus is the selected, complete bundle. Its author markers and unit
    # list are regenerated together, so Alpha's (2) still means Institute A.
    assert merged["作者"] == "Alpha, Alice(2); Bravo, Bob(1)"
    assert merged["作者单位"] == "(1) Institute B; (2) Institute A"
    assert merged["作者—单位关联来源"] == "SCOPUS; WOS"
    assert merged["作者—单位关联冲突原因"] == ""
    # WOS remains the complete correspondence pair; it is not combined with a
    # name-only Scopus field.
    assert merged["通讯作者"] == "Alpha, Alice"
    assert merged["通讯作者单位"] == "Institute A"
    assert merged["通讯作者来源"] == "WOS: Reprint Addresses"
    assert merged["通讯作者单位来源"] == "WOS: Reprint Addresses"


def test_author_unit_union_does_not_change_correspondence_conflict_review():
    doi = "10.1000/paired-author-affiliation-conflict"
    wos_record = _paired_wos_record(doi)
    # Both explicitly declared units are now retained per author. A different
    # declared corresponding author remains a separate review issue.
    scopus_record = _paired_scopus_record(
        doi,
        alpha_affiliation="Institute B",
        bravo_affiliation="Institute A",
        corresponding_author="Bravo, Bob",
    )

    merged = merge_records(wos_record, scopus_record)
    review_frames = split_output_frames(pd.DataFrame([merged]))
    review = review_frames["待复核_可尝试原文补全"].fillna("")

    assert merged["作者"] == "Alpha, Alice(1,2); Bravo, Bob(1,2)"
    assert merged["作者单位"] == "(1) Institute B; (2) Institute A"
    assert "同一作者不同记录的明确单位不一致" in merged["作者—单位关联冲突原因"]
    assert merged["通讯作者"] == "Bravo, Bob"
    assert merged["通讯作者单位"] == "Institute A"
    assert merged["通讯作者来源"] == "SCOPUS: Corresponding Author"
    assert merged["通讯作者单位来源"] == "SCOPUS: Authors with affiliations"
    assert "跨来源通讯作者—单位关系不一致" in merged["通讯作者—单位关联冲突原因"]
    assert "作者—单位关联存在冲突" in review.loc[0, "复核原因"].split("；")
    assert "通讯作者—单位关联存在冲突" in review.loc[0, "复核原因"]
