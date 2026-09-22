import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from converter import merge_records, process_ei_row, process_scopus_row, process_wos_row
from metadata_completion import EVIDENCE_COLUMN, numbered_affiliations
from scope_rules import _author_metadata_review_issues, split_output_frames


def ei_row(**overrides):
    raw = {
        "DOI": "10.1000/ei-complete", "Title": "EI record",
        "Author": "Li, Ming (2, 5); Wang, Wei (5)",
        "Author affiliation": "(2) Institute A, City; 100000, China (5) Institute B, City; 200000, China",
        "Corresponding author(s)": "Li, Ming(m@example.org); Wang, Wei(w@example.org)",
    }
    raw.update(overrides)
    return pd.Series(raw)


def test_ei_uses_explicit_correspondence_and_nonsequential_indices():
    record = process_ei_row(ei_row())
    assert record["作者"] == "Li, Ming(2,5); Wang, Wei(5)"
    assert record["通讯作者"] == "Li, Ming; Wang, Wei"
    assert record["通讯作者单位"] == "Institute A, City, 100000, China; Institute B, City, 200000, China"
    assert record["第一作者"] == "Li, Ming"
    assert record["第一作者单位"] == record["通讯作者单位"]
    assert "原始单位编号" in record[EVIDENCE_COLUMN]
    assert _author_metadata_review_issues(pd.Series(record))[0] == []


def test_ei_ambiguous_abbreviation_does_not_assign_institution():
    record = process_ei_row(ei_row(**{
        "Author": "Li, Ming (2); Li, Mei (5)", "Corresponding author(s)": "Li, M.(m@example.org)",
    }))
    assert record["通讯作者"] == "Li, M."
    assert record["通讯作者单位"] == ""


def test_distinct_full_given_names_are_not_matched_by_initials():
    record = process_ei_row(ei_row(**{"Corresponding author(s)": "Li, Mei"}))
    assert record["通讯作者"] == "Li, Mei"
    assert record["通讯作者单位"] == ""
    assert "尚未唯一匹配" in record["通讯作者—单位关联冲突原因"]


def test_surname_given_boundary_is_preserved_during_matching():
    record = process_ei_row(ei_row(**{
        "Author": "Liu, An (2)", "Corresponding author(s)": "Li, Uan",
    }))
    assert record["通讯作者"] == "Li, Uan"
    assert record["通讯作者单位"] == ""


def test_ei_one_unresolved_correspondent_keeps_incomplete_unit_visible():
    record = process_ei_row(ei_row(**{"Corresponding author(s)": "Li, Ming; Unknown, Person"}))
    assert record["通讯作者单位"] == ""
    assert "缺少通讯作者单位" in _author_metadata_review_issues(pd.Series(record))[0]


def test_ei_duplicate_unit_ids_are_not_resolved():
    assert numbered_affiliations("(1) Institute A (1) Institute B") is None
    record = process_ei_row(ei_row(**{"Author affiliation": "(2) Institute A (2) Institute B"}))
    assert record["通讯作者单位"] == ""
    assert record["第一作者单位"] == ""


def test_ei_invalid_author_reference_remains_in_review():
    record = process_ei_row(ei_row(**{"Author": "Li, Ming (2, 99); Wang, Wei (5)"}))
    assert record["通讯作者单位"] == ""
    assert "作者—单位关联不完整" in _author_metadata_review_issues(pd.Series(record))[0]


def test_ei_without_explicit_correspondence_does_not_guess():
    record = process_ei_row(ei_row(**{"Corresponding author(s)": ""}))
    assert not record.get("通讯作者")
    assert "缺少通讯作者" in _author_metadata_review_issues(pd.Series(record))[0]


def test_single_wos_author_can_use_own_explicit_reprint_address():
    record = process_wos_row(pd.Series({
        "Authors": "Lin, XM", "Addresses": "",
        "Reprint Addresses": "Lin, XM (corresponding author), Institute A, Australia.",
    }))
    assert record["作者"] == "Lin, XM (1)"
    assert record["作者单位"] == "(1) Institute A, Australia."
    assert record["第一作者单位"] == "Institute A, Australia."
    assert _author_metadata_review_issues(pd.Series(record))[0] == []
    assert "Reprint Addresses" in record[EVIDENCE_COLUMN]


def test_wos_partial_completion_does_not_assign_other_authors():
    record = process_wos_row(pd.Series({
        "DOI": "10.1000/partial", "Authors": "Lin, XM; Zhou, Q",
        "Addresses": "Institute A; Institute B",
        "Reprint Addresses": "Lin, XM (corresponding author), Institute A.",
    }))
    assert record["作者"] == "Lin, XM (1); Zhou, Q"
    assert record["作者单位"] == "(1) Institute A; Institute B"
    frames = split_output_frames(pd.DataFrame([record]))
    pending = frames["待复核_可尝试原文补全"].iloc[0]
    assert "尚待核验作者—单位：Zhou, Q" in pending["建议复核路径"]
    assert pending["原文链接"] == "https://doi.org/10.1000/partial"


def test_wos_one_unit_without_explicit_author_evidence_stays_unlinked():
    record = process_wos_row(pd.Series({"Authors": "Lin, XM; Zhou, Q", "Addresses": "Institute A"}))
    assert record["作者"] == "Lin, XM; Zhou, Q"
    assert not record.get(EVIDENCE_COLUMN)


def test_wos_ambiguous_initials_do_not_complete_author_links():
    record = process_wos_row(pd.Series({
        "Authors": "Li, Ming; Li, Mei", "Addresses": "Institute A",
        "Reprint Addresses": "Li, M. (corresponding author), Institute A.",
    }))
    assert record["作者"] == "Li, Ming; Li, Mei"


def test_multiple_wos_correspondence_groups_complete_only_their_own_author():
    record = process_wos_row(pd.Series({
        "Authors": "Lin, XM; Zhou, Q", "Addresses": "Institute A; Institute B",
        "Reprint Addresses": "Lin, XM (corresponding author), Institute A; Zhou, Q (corresponding author), Institute B",
    }))
    assert record["作者"] == "Lin, XM (1); Zhou, Q (2)"
    assert record["作者单位"] == "(1) Institute A; (2) Institute B"
    assert record["通讯作者"] == "Lin, XM; Zhou, Q"
    assert record["通讯作者单位"] == "Institute A; Institute B"


def test_scopus_uses_direct_address_for_an_unlinked_corresponding_author():
    record = process_scopus_row(pd.Series({
        "Author full names": "Qin, Xinyu; Chang, Tsung-Hui",
        "Authors with affiliations": "Qin X. (Institute A); Chang T.-H.",
        "Affiliations": "Institute A; Institute B",
        "Correspondence Address": "T.-H. Chang; Institute B; email: c@example.org",
    }))
    assert record["作者"] == "Qin, Xinyu (1); Chang, Tsung-Hui (2)"
    assert record["作者单位"] == "(1) Institute A; (2) Institute B"
    assert "Correspondence Address" in record[EVIDENCE_COLUMN]


def test_spaced_valid_indices_and_dangling_indices_are_distinguished():
    row = pd.Series({"作者": "Li, Ming (2, 5)", "作者单位": "(2) A; (5) B", "通讯作者": "Li, Ming", "通讯作者单位": "A; B"})
    assert _author_metadata_review_issues(row)[0] == []
    row["作者单位"] = "(2) A"
    assert "作者—单位关联不完整" in _author_metadata_review_issues(row)[0]


def test_ei_correspondence_relations_survive_doi_merge_without_cross_assignment():
    ei = process_ei_row(ei_row(**{
        "Author": "Li, Ming (2); Wang, Wei (5)",
    }))
    other = {"DOI": ei["DOI"], "来源库": "WOS", "作者": "Li, Ming; Wang, Wei"}
    merged = merge_records(other, ei)
    relations = merged["_correspondence_relations"]["relations"]
    assert relations == [
        {"name": "Li, Ming", "affiliations": ["Institute A, City, 100000, China"]},
        {"name": "Wang, Wei", "affiliations": ["Institute B, City, 200000, China"]},
    ]
    assert merged["作者"] == "Li, Ming(1); Wang, Wei(2)"
    assert merged["作者单位"] == "(1) Institute A, City, 100000, China; (2) Institute B, City, 200000, China"


def test_reverse_link_completion_is_kept_when_record_is_merged():
    wos = process_wos_row(pd.Series({
        "DOI": "10.1000/reverse", "Authors": "Lin, XM",
        "Reprint Addresses": "Lin, XM (corresponding author), Institute A.",
    }))
    merged = merge_records(wos, {"DOI": wos["DOI"], "来源库": "EI"})
    assert merged["作者"] == "Lin, XM (1)"
    assert merged["作者单位"] == "(1) Institute A."
    assert "Reprint Addresses" in merged[EVIDENCE_COLUMN]


def test_dangling_ei_unit_stays_auditable_after_doi_merge():
    ei = process_ei_row(ei_row(**{"Author": "Li, Ming (2, 99); Wang, Wei (5)"}))
    other = {"DOI": ei["DOI"], "来源库": "SCOPUS", "通讯作者": "Li, Ming", "通讯作者单位": "Institute A"}
    merged = merge_records(ei, other)
    assert "99" in merged["作者—单位关联冲突原因"]
    assert "Li, Ming" in merged["作者—单位关联冲突原因"]
    frames = split_output_frames(pd.DataFrame([merged]))
    assert len(frames["待复核_可尝试原文补全"]) + len(frames["待复核_其他"]) == 1


def test_unresolved_ei_correspondent_survives_merge_in_review_evidence():
    ei = process_ei_row(ei_row(**{"Corresponding author(s)": "Li, Ming; Unknown, Person"}))
    other = {"DOI": ei["DOI"], "来源库": "SCOPUS", "通讯作者": "Li, Ming", "通讯作者单位": "Institute A"}
    for first, second in [(ei.copy(), other.copy()), (other.copy(), ei.copy())]:
        merged = merge_records(first, second)
        assert "Unknown, Person" in merged["通讯作者—单位关联冲突原因"]
        frames = split_output_frames(pd.DataFrame([merged]))
        assert len(frames["待复核_可尝试原文补全"]) + len(frames["待复核_其他"]) == 1


def test_shared_middle_initial_does_not_hide_different_full_given_names():
    from metadata_completion import unique_author
    assert unique_author("Li, Ming A.", ["Li, Mei A."]) is None
    assert unique_author("Li, M. A.", ["Li, Ming Alan"]) == 0
