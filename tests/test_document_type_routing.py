"""Publication-type routing must not erase records or leak merged metadata."""
from copy import deepcopy
from itertools import permutations

import pandas as pd
import pytest

from converter import merge_doi_group, merge_records
from scope_rules import document_type_group, split_output_frames


def record(kind, source="WOS", **extra):
    return {"DOI": "10.1000/types", "原始文献类型": kind, "来源库": source,
            "数据归属": "本校", "题名": source, **extra}


@pytest.mark.parametrize("kind,group", [
    ("Article; Proceedings Paper", "journal"),
    ("Proceedings Paper；Article", "journal"),
    ("ARTICLE / Proceedings Paper / Early Access", "journal"),
    ("Review; Conference Paper", "journal"),
    ("Journal Article", "journal"),
    ("Conference Paper", "conference"), ("Proceedings Paper", "conference"),
    ("Workshop", "conference"), ("Symposium", "conference"),
    ("", "other"), ("Editorial", "other"),
])
def test_classification_and_export_agree(kind, group):
    row = record(kind)
    assert document_type_group(row) == group
    frames = split_output_frames(pd.DataFrame([row]))
    assert len(frames["全部数据"]) == 1
    assert len(frames["期刊论文"]) == (group == "journal")
    assert len(frames["会议论文"]) == (group == "conference")
    assert frames["全部数据"].iloc[0]["原始文献类型"] == kind
    assert frames["待复核_其他"].empty


def test_type_separation_is_order_independent_and_keeps_source_fields():
    rows = [record("Article; Proceedings Paper", "WOS", WOS记录号="WOS:1"),
            record("Conference Paper", "SCOPUS", SCOPUSEID="2-s2.0-1"),
            record("Journal Article", "EI", EI入藏号="EI:1")]
    for ordering in permutations(rows):
        result = merge_doi_group(deepcopy(ordering))
        assert len(result) == 2
        by_type = {document_type_group(r): r for r in result}
        assert set(by_type["journal"]["来源库"].split("; ")) == {"WOS", "EI"}
        assert not by_type["journal"].get("SCOPUSEID")
        assert by_type["conference"]["SCOPUSEID"] == "2-s2.0-1"
        assert not by_type["conference"].get("WOS记录号")
        assert by_type["conference"]["原始文献类型"] == "Conference Paper"


def test_unknown_type_cannot_bridge_or_pollute_conflicting_groups():
    rows = [record("Article", "WOS"), record("Conference Paper", "SCOPUS"),
            record("", "EI", 摘要="Only unknown source has this")]
    for ordering in permutations(rows):
        result = merge_doi_group(deepcopy(ordering))
        assert len(result) == 3
        assert all(not r.get("摘要") for r in result if document_type_group(r) != "other")


@pytest.mark.parametrize("kinds", [
    ["Article", "Review"], ["Conference Paper", "Proceedings Paper"],
    ["Article", ""], ["", "Conference Paper"], ["Editorial", ""],
])
def test_nonconflicting_groups_use_existing_merge_behavior(kinds):
    rows = [record(kinds[0]), record(kinds[1], "SCOPUS", 摘要="Supplement")]
    expected = merge_records(deepcopy(rows[0]), deepcopy(rows[1]))
    assert merge_doi_group(deepcopy(rows)) == [expected]


def test_type_rule_does_not_suppress_author_or_scope_review():
    row = record("Article; Proceedings Paper", 作者="Li, Ming", 作者单位="", 通讯作者="")
    frames = split_output_frames(pd.DataFrame([row]))
    assert len(frames["期刊论文"]) == 1
    assert len(frames["待复核_可尝试原文补全"]) == 1
    row.update({"数据归属": "校外", "本校学者邮箱": "", "本校学者匹配": "待确认"})
    frames = split_output_frames(pd.DataFrame([row]))
    assert len(frames["待复核_其他"]) == 1
