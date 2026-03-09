"""
Unit tests for the Scopus → CSpace converter.
"""
import io
import os
import sys
import tempfile
import unittest

import pandas as pd
import xlrd

# Make sure the repo root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter import (
    CHINESE_LABELS,
    INTERNAL_KEYS,
    _first_author,
    _format_authors,
    _strip_ids_from_fullname_list,
    convert,
    write_xls,
)


# ---------------------------------------------------------------------------
# Author helpers
# ---------------------------------------------------------------------------

class TestStripIdsFromFullnameList(unittest.TestCase):
    def test_typical_scopus_input(self):
        raw = (
            "Xu, Jiatong (57215283977); Luxu, Shupeng (57424730800); "
            "Huang, Hsi-Yuan (37025368700)"
        )
        result = _strip_ids_from_fullname_list(raw)
        self.assertEqual(result, ["Xu, Jiatong", "Luxu, Shupeng", "Huang, Hsi-Yuan"])

    def test_single_author(self):
        raw = "Smith, Alice (12345678901)"
        result = _strip_ids_from_fullname_list(raw)
        self.assertEqual(result, ["Smith, Alice"])

    def test_empty_string(self):
        self.assertEqual(_strip_ids_from_fullname_list(""), [])

    def test_nan(self):
        self.assertEqual(_strip_ids_from_fullname_list(float("nan")), [])


class TestFormatAuthors(unittest.TestCase):
    def test_multiple_authors(self):
        raw = (
            "Xu, Jiatong (57215283977); Luxu, Shupeng (57424730800); "
            "Huang, Hsien-Da (7405615434)"
        )
        result = _format_authors(raw)
        self.assertEqual(result, "Xu, Jiatong; Luxu, Shupeng; Huang, Hsien-Da")

    def test_empty(self):
        self.assertEqual(_format_authors(""), "")


class TestFirstAuthor(unittest.TestCase):
    def test_first_author_extracted(self):
        raw = "Xu, Jiatong (57215283977); Luxu, Shupeng (57424730800)"
        self.assertEqual(_first_author(raw), "Xu, Jiatong")

    def test_single_author(self):
        raw = "Smith, Bob (99999)"
        self.assertEqual(_first_author(raw), "Smith, Bob")

    def test_empty(self):
        self.assertEqual(_first_author(""), "")


# ---------------------------------------------------------------------------
# Column structure
# ---------------------------------------------------------------------------

class TestColumnDefinitions(unittest.TestCase):
    def test_labels_and_keys_same_length(self):
        self.assertEqual(len(CHINESE_LABELS), len(INTERNAL_KEYS))

    def test_required_labels_present(self):
        required = {"题名", "作者", "来源期刊", "年份", "DOI", "第一作者"}
        self.assertTrue(required.issubset(set(CHINESE_LABELS)))

    def test_no_duplicate_keys(self):
        self.assertEqual(len(INTERNAL_KEYS), len(set(INTERNAL_KEYS)))


# ---------------------------------------------------------------------------
# write_xls
# ---------------------------------------------------------------------------

class TestWriteXls(unittest.TestCase):
    def _sample_records(self):
        return [
            {
                "dc.title": "Test Title",
                "dc.contributor.author": "Smith, Alice; Jones, Bob",
                "dc.contributor.firstauthor": "Smith, Alice",
                "dc.contributor.correspondingauthor": "",
                "dc.contributor.affiliation": "",
                "dc.description.abstract": "",
                "dc.subject": "",
                "dc.source.journal": "Nature",
                "dc.identifier.issn": "",
                "dc.date.issued": "2024",
                "dc.description.volume": "21",
                "dc.description.issue": "3",
                "dc.identifier.articlenumber": "",
                "dc.description.startpage": "100",
                "dc.description.endpage": "110",
                "dc.description.pagecount": "11",
                "dc.identifier.doi": "10.1038/test",
                "dc.description.citedby": "5",
                "dc.type": "Article",
                "dc.description.publicationstage": "Final",
                "dc.rights.accessrights": "Gold Open Access",
                "dc.source": "Scopus",
                "dc.identifier.eid": "2-s2.0-000000000001",
                "dc.identifier.uri": "https://example.com",
            }
        ]

    def test_writes_valid_xls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.xls")
            write_xls(self._sample_records(), path)
            self.assertTrue(os.path.isfile(path))

    def test_header_row1_chinese_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.xls")
            write_xls(self._sample_records(), path)
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            header_row = [ws.cell_value(0, c) for c in range(ws.ncols)]
            self.assertEqual(header_row, CHINESE_LABELS)

    def test_header_row2_internal_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.xls")
            write_xls(self._sample_records(), path)
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            key_row = [ws.cell_value(1, c) for c in range(ws.ncols)]
            self.assertEqual(key_row, INTERNAL_KEYS)

    def test_data_row_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.xls")
            write_xls(self._sample_records(), path)
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            title_col = INTERNAL_KEYS.index("dc.title")
            self.assertEqual(ws.cell_value(2, title_col), "Test Title")

    def test_sheet_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.xls")
            write_xls(self._sample_records(), path)
            wb = xlrd.open_workbook(path)
            self.assertEqual(wb.sheet_names()[0], "期刊论文")


# ---------------------------------------------------------------------------
# End-to-end convert()
# ---------------------------------------------------------------------------

SAMPLE_TSV = (
    "Authors\tAuthor full names\tAuthor(s) ID\tTitle\tYear\tSource title\t"
    "Volume\tIssue\tArt. No.\tPage start\tPage end\tPage count\t"
    "Cited by\tDOI\tLink\tDocument Type\tPublication Stage\tOpen Access\tSource\tEID\n"
    "Xu J.; Luxu S.\t"
    "Xu, Jiatong (57215283977); Luxu, Shupeng (57424730800)\t"
    "57215283977; 57424730800\t"
    "Test Paper\t"
    "2025\t"
    "Biomolecules\t"
    "15\t12\t1707\t\t\t3\t1\t"
    "10.3390/biom15121707\t"
    "https://example.com\t"
    "Review\tFinal\tGold Open Access\tScopus\t2-s2.0-105025657693\n"
)


class TestConvertEndToEnd(unittest.TestCase):
    def test_output_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            self.assertTrue(os.path.isfile(output_path))

    def test_output_filename_contains_today(self):
        from datetime import date
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            today = date.today().strftime("%Y%m%d")
            self.assertIn(today, os.path.basename(output_path))

    def test_output_filename_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            name = os.path.basename(output_path)
            self.assertTrue(name.startswith("CSpace批量导入模板_期刊论文_"))
            self.assertTrue(name.endswith(".xls"))

    def test_data_correct_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            wb = xlrd.open_workbook(output_path)
            ws = wb.sheet_by_index(0)
            title_col = INTERNAL_KEYS.index("dc.title")
            self.assertEqual(ws.cell_value(2, title_col), "Test Paper")

    def test_author_formatting_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            wb = xlrd.open_workbook(output_path)
            ws = wb.sheet_by_index(0)
            author_col = INTERNAL_KEYS.index("dc.contributor.author")
            self.assertEqual(
                ws.cell_value(2, author_col),
                "Xu, Jiatong; Luxu, Shupeng",
            )

    def test_first_author_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_TSV)
            output_path = convert(input_path, tmpdir)
            wb = xlrd.open_workbook(output_path)
            ws = wb.sheet_by_index(0)
            fa_col = INTERNAL_KEYS.index("dc.contributor.firstauthor")
            self.assertEqual(ws.cell_value(2, fa_col), "Xu, Jiatong")

    def test_two_rows_produces_two_data_rows(self):
        tsv_two = SAMPLE_TSV + (
            "Jones B.\t"
            "Jones, Bob (98765432100)\t"
            "98765432100\t"
            "Another Paper\t"
            "2023\t"
            "Science\t"
            "380\t6640\t\t10\t20\t11\t15\t"
            "10.1126/science.abc\t"
            "https://example2.com\t"
            "Article\tFinal\t\tScopus\t2-s2.0-000000000099\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.csv")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(tsv_two)
            output_path = convert(input_path, tmpdir)
            wb = xlrd.open_workbook(output_path)
            ws = wb.sheet_by_index(0)
            # 2 header rows + 2 data rows = 4 total rows
            self.assertEqual(ws.nrows, 4)


if __name__ == "__main__":
    unittest.main()
