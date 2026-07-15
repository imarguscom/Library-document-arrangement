import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scope_rules import (
    CLAIM_COLUMN,
    apply_scope_fields,
    build_author_claim_value,
    build_scholar_alias_registry,
    infer_record_scope,
    normalize_name,
    split_author_names,
    write_multi_sheet_excel,
)


def registry_with_email(email="scholar@cuhk.edu.cn"):
    return {
        "aliases": {
            normalize_name("Wang, Jiawei"): {
                "alias": "Wang, Jiawei",
                "real_name": "王嘉伟",
                "email": email,
                "sources": ["账户表"],
            }
        },
        "local_keywords": ["cuhk-shenzhen", "the chinese university of hong kong, shenzhen"],
    }


def test_local_mode_defaults_to_local_without_alias():
    scope = infer_record_scope({"题名": "A", "作者": "Unknown Author"}, "local", {"aliases": {}})
    assert scope["数据归属"] == "本校"
    assert "用户选择本校成果模式" in scope["归属依据"]


def test_external_mode_alias_with_email():
    scope = infer_record_scope({"题名": "A", "作者": "Wang, Jiawei"}, "external", registry_with_email())
    assert scope["数据归属"] == "校外"
    assert scope["本校学者匹配"] == "王嘉伟"
    assert scope["本校学者邮箱"] == "scholar@cuhk.edu.cn"
    assert "作者命中别名" in scope["学者匹配依据"]


def test_external_mode_alias_without_email_needs_email():
    scope = infer_record_scope({"题名": "A", "作者": "Wang, Jiawei"}, "external", registry_with_email(""))
    assert scope["数据归属"] == "校外"
    assert scope["本校学者匹配"] == "王嘉伟"
    assert scope["本校学者邮箱"] == ""
    assert "需补邮箱" in scope["学者匹配依据"]


def test_external_mode_without_alias_is_pending():
    scope = infer_record_scope({"题名": "A", "作者": "No Match"}, "external", registry_with_email())
    assert scope["数据归属"] == "校外"
    assert scope["本校学者匹配"] == "待确认"
    assert scope["本校学者邮箱"] == ""
    assert "需人工确认" in scope["学者匹配依据"]


def test_affiliation_keyword_is_only_auxiliary_evidence():
    scope = infer_record_scope(
        {
            "题名": "A",
            "作者": "No Match",
            "作者单位": "The Chinese University of Hong Kong, Shenzhen",
        },
        "external",
        registry_with_email(),
    )
    assert scope["数据归属"] == "校外"
    assert scope["本校学者匹配"] == "待确认"
    assert "作者单位命中本校单位关键词" in scope["归属依据"]


def test_english_comma_name_is_not_split():
    assert split_author_names("Wang, Jiawei; Li, Ming") == ["Wang, Jiawei", "Li, Ming"]


def test_existing_claim_is_not_overwritten():
    df = pd.DataFrame([{"题名": "A", "作者": "Wang, Jiawei", "作品认领": "existing@cuhk.edu.cn"}])
    result = apply_scope_fields(df, "external", registry_with_email())
    assert result.loc[0, "作品认领"] == "existing@cuhk.edu.cn"
    assert result.loc[0, "本校学者邮箱"] == "scholar@cuhk.edu.cn"


def test_excel_output_contains_expected_sheets(tmp_path):
    df = pd.DataFrame(
        [
            {"题名": "Local", "作者": "No Match"},
            {"题名": "External", "作者": "Wang, Jiawei"},
            {"题名": "Pending", "作者": "No Match"},
        ]
    )
    local = apply_scope_fields(df.iloc[[0]], "local", registry_with_email())
    external = apply_scope_fields(df.iloc[[1, 2]], "external", registry_with_email())
    output_df = pd.concat([local, external], ignore_index=True)
    output = tmp_path / "out.xlsx"
    counts = write_multi_sheet_excel(output_df, output)
    sheets = pd.ExcelFile(output).sheet_names
    assert {"全部数据", "本校成果", "校外成果", "待确认"}.issubset(set(sheets))
    assert counts["全部数据"] == 3
    assert counts["本校成果"] == 1
    assert counts["校外成果"] == 1
    assert counts["待确认"] == 1


def test_default_scholar_author_name_forms_structure_can_be_read():
    path = Path(__file__).resolve().parents[1] / "src" / "scholar_author_name_forms.xlsx"
    assert path.exists()
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=path)
    assert registry["alias_path"].endswith("scholar_author_name_forms.xlsx")
    assert "unique_name_forms" in registry["alias_sheets"]
    assert len(registry["aliases"]) > 0


def test_alias_file_priority_over_account_sources(tmp_path):
    alias_path = tmp_path / "aliases.xlsx"
    account_path = tmp_path / "accounts.xlsx"
    pd.DataFrame(
        [{"真实姓名": "Priority Scholar", "发文名": "Priority, P.", "邮箱": "priority@cuhk.edu.cn"}]
    ).to_excel(alias_path, index=False)
    pd.DataFrame(
        [{"姓名": "Account Scholar", "英文名": "Priority, P.", "Email": "account@cuhk.edu.cn"}]
    ).to_excel(account_path, index=False)
    registry = build_scholar_alias_registry(
        accounts_path=account_path,
        article_library_path=None,
        alias_path=alias_path,
    )
    scope = infer_record_scope({"题名": "A", "作者": "Priority, P."}, "external", registry)
    assert scope["本校学者匹配"] == "Priority Scholar"
    assert scope["本校学者邮箱"] == "priority@cuhk.edu.cn"
    assert "学者别名表" in scope["学者匹配依据"]


def test_alias_conflict_goes_to_pending(tmp_path):
    alias_path = tmp_path / "aliases.xlsx"
    pd.DataFrame(
        [
            {"真实姓名": "Scholar A", "发文名": "Same, Alias", "邮箱": "a@cuhk.edu.cn"},
            {"真实姓名": "Scholar B", "发文名": "Same, Alias", "邮箱": "b@cuhk.edu.cn"},
        ]
    ).to_excel(alias_path, index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    scope = infer_record_scope({"题名": "A", "作者": "Same, Alias"}, "external", registry)
    assert scope["本校学者匹配"] == "待确认"
    assert scope["本校学者邮箱"] == ""
    assert "别名冲突" in scope["学者匹配依据"]


def test_web_app_imports_without_streamlit_runtime_error():
    import web_app

    assert hasattr(web_app, "main")


def _disable_default_account_and_article_discovery(monkeypatch):
    import scope_rules

    monkeypatch.setattr(scope_rules, "discover_article_library", lambda *args, **kwargs: None)
    monkeypatch.setattr(scope_rules, "discover_account_file", lambda *args, **kwargs: None)


def test_formal_three_column_alias_table_can_be_read(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [{"别名": "ZHANG, Peng", "姓名": "张鹏", "邮箱": "peng@cuhk.edu.cn"}]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    scope = infer_record_scope({"题名": "A", "作者": "ZHANG, Peng"}, "external", registry)
    assert scope["本校学者匹配"] == "张鹏"
    assert scope["本校学者邮箱"] == "peng@cuhk.edu.cn"
    assert scope["学者匹配依据"] == "命中正式别名表: ZHANG, Peng -> 张鹏"


def test_formal_alias_table_takes_default_priority_over_legacy_file(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    formal_path = tmp_path / "博文阁用户别名表.xlsx"
    legacy_path = tmp_path / "scholar_author_name_forms.xlsx"
    pd.DataFrame(
        [{"别名": "Priority, P.", "姓名": "正式学者", "邮箱": "formal@cuhk.edu.cn"}]
    ).to_excel(formal_path, sheet_name="epersonnamealias", index=False)
    pd.DataFrame(
        [{"真实姓名": "旧表学者", "发文名": "Priority, P.", "邮箱": "legacy@cuhk.edu.cn"}]
    ).to_excel(legacy_path, index=False)

    import scope_rules

    monkeypatch.setattr(scope_rules, "DEFAULT_ALIAS_PATHS", [str(formal_path), str(legacy_path)])
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None)
    scope = infer_record_scope({"题名": "A", "作者": "Priority, P."}, "external", registry)
    assert registry["alias_path"] == str(formal_path)
    assert scope["本校学者匹配"] == "正式学者"
    assert scope["本校学者邮箱"] == "formal@cuhk.edu.cn"


def test_formal_alias_exact_duplicate_rows_are_deduplicated(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [
            {"别名": "Same, One", "姓名": "同一学者", "邮箱": "same@cuhk.edu.cn"},
            {"别名": "Same, One", "姓名": "同一学者", "邮箱": "same@cuhk.edu.cn"},
        ]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    assert len(registry["aliases"]) == 1
    assert registry["conflict_aliases"] == []


def test_formal_alias_conflicting_email_goes_to_pending(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [
            {"别名": "Zhang P", "姓名": "张鹏", "邮箱": "one@cuhk.edu.cn"},
            {"别名": "Zhang P", "姓名": "张鹏", "邮箱": "two@cuhk.edu.cn"},
        ]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    scope = infer_record_scope({"题名": "A", "作者": "Zhang P"}, "external", registry)
    assert scope["本校学者匹配"] == "待确认"
    assert scope["本校学者邮箱"] == ""
    assert scope["学者匹配依据"] == "正式别名表中该别名对应多个学者/邮箱，需人工确认"


def test_formal_alias_with_email_fills_claim_value(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [{"别名": "Li, Ming", "姓名": "李明", "邮箱": "ming@cuhk.edu.cn"}]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    df = pd.DataFrame([{"题名": "A", "作者": "Li, Ming", CLAIM_COLUMN: "unknown"}])
    result = apply_scope_fields(df, "external", registry)
    assert result.loc[0, "本校学者匹配"] == "李明"
    assert result.loc[0, "本校学者邮箱"] == "ming@cuhk.edu.cn"
    assert result.loc[0, CLAIM_COLUMN] == "ming@cuhk.edu.cn"


def test_claim_value_preserves_author_positions(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [
            {"别名": "Wang, Jiawei", "姓名": "王嘉伟", "邮箱": "jiawei@cuhk.edu.cn"},
            {"别名": "Li, Ming", "姓名": "李明", "邮箱": "ming@cuhk.edu.cn"},
        ]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    record = {"作者": "Wang, Jiawei(1); Li, Ming(2); Unknown, Person(3)"}

    claim = build_author_claim_value(record, registry, "unknown;unknown;unknown")

    assert claim == "jiawei@cuhk.edu.cn;ming@cuhk.edu.cn;unknown"


def test_link_email_is_not_claimable(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    alias_path = tmp_path / "博文阁用户别名表.xlsx"
    pd.DataFrame(
        [{"别名": "Student, One", "姓名": "学生一", "邮箱": "student@link.cuhk.edu.cn"}]
    ).to_excel(alias_path, sheet_name="epersonnamealias", index=False)
    registry = build_scholar_alias_registry(accounts_path=None, article_library_path=None, alias_path=alias_path)
    df = pd.DataFrame([{"题名": "A", "作者": "Student, One", CLAIM_COLUMN: "unknown"}])

    result = apply_scope_fields(df, "external", registry)

    assert result.loc[0, "本校学者匹配"] == "学生一"
    assert result.loc[0, "本校学者邮箱"] == ""
    assert result.loc[0, CLAIM_COLUMN] == "unknown"


def test_default_alias_discovery_used_by_converter(tmp_path, monkeypatch):
    _disable_default_account_and_article_discovery(monkeypatch)
    formal_path = tmp_path / "博文阁用户别名表.xlsx"
    input_path = tmp_path / "scopus.csv"
    output_path = tmp_path / "out.xlsx"
    pd.DataFrame(
        [{"别名": "Chen, Test", "姓名": "陈测试", "邮箱": "chen@cuhk.edu.cn"}]
    ).to_excel(formal_path, sheet_name="epersonnamealias", index=False)
    pd.DataFrame(
        [
            {
                "DOI": "10.1000/test-formal",
                "Title": "Formal Alias Test",
                "Authors": "Chen, Test",
                "Year": "2026",
                "Source title": "Journal",
                "EID": "2-s2.0-test",
            }
        ]
    ).to_csv(input_path, index=False)

    import scope_rules

    monkeypatch.setattr(scope_rules, "DEFAULT_ALIAS_PATHS", [str(formal_path)])
    from converter import run_conversion

    stats = run_conversion([input_path], output_path, "external", accounts_path=None, article_library_path=None)
    assert stats["alias_path"] == str(formal_path)
    assert stats["alias_count"] == 1
    xl = pd.ExcelFile(output_path)
    assert {"全部数据", "校外成果", "待确认", "需补邮箱"}.issubset(set(xl.sheet_names))
    external = pd.read_excel(output_path, sheet_name="校外成果", dtype=str).fillna("")
    assert external.loc[0, "本校学者邮箱"] == "chen@cuhk.edu.cn"
