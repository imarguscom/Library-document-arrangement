"""
Scopus CSV to CSpace 批量导入模板_期刊论文 XLS Converter
=======================================================
Reads a Scopus-exported tab-separated CSV file and converts it to the
CSpace bulk-import template format for journal articles (期刊论文).

Output filename convention:
    CSpace批量导入模板_期刊论文_<YYYYMMDD>.xls

CSpace template column mapping (two-row header):
    Row 1 – Chinese field labels
    Row 2 – Internal field keys

Usage:
    python converter.py <input_csv> [output_dir]
    python converter.py samples/sample_scopus_input.csv
    python converter.py samples/sample_scopus_input.csv ./output
"""

import argparse
import os
import re
import sys
from datetime import date

import pandas as pd
import xlwt


# ---------------------------------------------------------------------------
# CSpace template definition
# ---------------------------------------------------------------------------

# Each entry: (Chinese label, internal key, scopus_column_or_None)
# When scopus_column_or_None is None, the field is left blank unless filled
# by a transform function.
CSPACE_COLUMNS = [
    ("题名",         "dc.title",                       "Title"),
    ("作者",         "dc.contributor.author",           "_authors_formatted"),
    ("第一作者",     "dc.contributor.firstauthor",      "_first_author"),
    ("通讯作者",     "dc.contributor.correspondingauthor", None),
    ("作者机构",     "dc.contributor.affiliation",      None),
    ("摘要",         "dc.description.abstract",         None),
    ("关键词",       "dc.subject",                      None),
    ("来源期刊",     "dc.source.journal",               "Source title"),
    ("ISSN",         "dc.identifier.issn",              None),
    ("年份",         "dc.date.issued",                  "Year"),
    ("卷",           "dc.description.volume",           "Volume"),
    ("期",           "dc.description.issue",            "Issue"),
    ("文章编号",     "dc.identifier.articlenumber",     "Art. No."),
    ("起始页",       "dc.description.startpage",        "Page start"),
    ("结束页",       "dc.description.endpage",          "Page end"),
    ("页数",         "dc.description.pagecount",        "Page count"),
    ("DOI",          "dc.identifier.doi",               "DOI"),
    ("被引次数",     "dc.description.citedby",          "Cited by"),
    ("文献类型",     "dc.type",                         "Document Type"),
    ("出版阶段",     "dc.description.publicationstage", "Publication Stage"),
    ("开放获取",     "dc.rights.accessrights",          "Open Access"),
    ("数据来源",     "dc.source",                       "Source"),
    ("资源标识符",   "dc.identifier.eid",               "EID"),
    ("链接",         "dc.identifier.uri",               "Link"),
]

CHINESE_LABELS = [col[0] for col in CSPACE_COLUMNS]
INTERNAL_KEYS  = [col[1] for col in CSPACE_COLUMNS]


# ---------------------------------------------------------------------------
# Author formatting helpers
# ---------------------------------------------------------------------------

def _strip_ids_from_fullname_list(raw: str) -> list[str]:
    """
    Parse 'Author full names' field such as:
        "Xu, Jiatong (57215283977); Luxu, Shupeng (57424730800); ..."
    and return a list of clean names:
        ["Xu, Jiatong", "Luxu, Shupeng", ...]
    """
    if not raw or pd.isna(raw):
        return []
    names = []
    for part in str(raw).split(";"):
        part = part.strip()
        # Remove trailing Scopus author ID in parentheses, e.g. " (57215283977)"
        clean = re.sub(r"\s*\(\d+\)\s*$", "", part).strip()
        if clean:
            names.append(clean)
    return names


def _format_authors(full_names: str) -> str:
    """
    Return a semicolon-separated list of author names derived from the
    'Author full names' field.  Example output:
        "Xu, Jiatong; Luxu, Shupeng; Huang, Hsi-Yuan"
    """
    return "; ".join(_strip_ids_from_fullname_list(full_names))


def _first_author(full_names: str) -> str:
    names = _strip_ids_from_fullname_list(full_names)
    return names[0] if names else ""


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------

def _convert_row(row: pd.Series) -> dict:
    """Convert a single Scopus row to a dict keyed by CSpace internal keys."""
    result = {}

    def _get(col: str) -> str:
        """Safely retrieve a value from the Scopus row; return empty string if missing."""
        val = row.get(col, "")
        if pd.isna(val):
            return ""
        return str(val).strip()

    for _label, key, src_col in CSPACE_COLUMNS:
        if src_col is None:
            result[key] = ""
        elif src_col == "_authors_formatted":
            result[key] = _format_authors(_get("Author full names"))
        elif src_col == "_first_author":
            result[key] = _first_author(_get("Author full names"))
        else:
            result[key] = _get(src_col)

    return result


# ---------------------------------------------------------------------------
# XLS writer
# ---------------------------------------------------------------------------

def _make_header_styles(workbook: xlwt.Workbook):
    """Create cell styles for the two header rows."""
    header1_style = xlwt.XFStyle()
    header2_style = xlwt.XFStyle()

    font1 = xlwt.Font()
    font1.bold = True
    font1.name = "Microsoft YaHei"
    header1_style.font = font1

    font2 = xlwt.Font()
    font2.bold = False
    font2.name = "Arial"
    header2_style.font = font2

    # Light-blue background for row 1
    pattern1 = xlwt.Pattern()
    pattern1.pattern = xlwt.Pattern.SOLID_PATTERN
    pattern1.pattern_fore_colour = 0x1F  # pale_blue
    header1_style.pattern = pattern1

    return header1_style, header2_style


def write_xls(records: list[dict], output_path: str) -> None:
    """
    Write *records* (list of dicts keyed by CSpace internal key) to an XLS
    file at *output_path* following the CSpace two-row header convention.
    """
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("期刊论文", cell_overwrite_ok=True)

    header1_style, header2_style = _make_header_styles(wb)

    # Row 0 – Chinese labels
    for col_idx, label in enumerate(CHINESE_LABELS):
        ws.write(0, col_idx, label, header1_style)

    # Row 1 – internal keys
    for col_idx, key in enumerate(INTERNAL_KEYS):
        ws.write(1, col_idx, key, header2_style)

    # Data rows start at row index 2
    data_style = xlwt.XFStyle()
    data_style.alignment = xlwt.Alignment()
    data_style.alignment.wrap = xlwt.Alignment.WRAP_AT_RIGHT

    for row_idx, record in enumerate(records, start=2):
        for col_idx, key in enumerate(INTERNAL_KEYS):
            value = record.get(key, "")
            ws.write(row_idx, col_idx, value, data_style)

    wb.save(output_path)


# ---------------------------------------------------------------------------
# Main conversion logic
# ---------------------------------------------------------------------------

def convert(input_csv: str, output_dir: str = ".") -> str:
    """
    Read *input_csv* (Scopus tab-separated export) and write the CSpace XLS.

    Returns the path of the generated XLS file.
    """
    # Scopus exports are tab-separated; encoding is UTF-8 with BOM
    df = pd.read_csv(
        input_csv,
        sep="\t",
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
    )

    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]

    records = [_convert_row(row) for _, row in df.iterrows()]

    today = date.today().strftime("%Y%m%d")
    filename = f"CSpace批量导入模板_期刊论文_{today}.xls"
    output_path = os.path.join(output_dir, filename)

    os.makedirs(output_dir, exist_ok=True)
    write_xls(records, output_path)

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Convert a Scopus-exported CSV to a CSpace 批量导入模板_期刊论文 XLS file."
        )
    )
    parser.add_argument(
        "input_csv",
        help="Path to the Scopus tab-separated CSV export file.",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Directory to write the output XLS file (default: current directory).",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input_csv):
        print(f"Error: input file not found: {args.input_csv}", file=sys.stderr)
        sys.exit(1)

    output_path = convert(args.input_csv, args.output_dir)
    print(f"Output written to: {output_path}")


if __name__ == "__main__":
    main()
