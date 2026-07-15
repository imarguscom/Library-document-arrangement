import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter import normalize_doi, process_ei_row, process_scopus_row, read_normal_csv_robust


def test_normalize_doi_strips_prefix_and_spaces():
    assert normalize_doi(" DOI: https://doi.org/10.1000/ABC  ") == "10.1000/abc"


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


def test_read_normal_csv_detects_semicolon_separator():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sample.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("A;B\n1;2\n")
        df = read_normal_csv_robust(path)
    assert list(df.columns) == ["A", "B"]
    assert df.iloc[0]["A"] == "1"
