from copy import deepcopy
import os

import pandas as pd
import pytest

from converter import process_wos_row, merge_records, CORRESPONDENCE_RELATIONS_KEY
from scope_rules import split_output_frames


def wos(**overrides):
    row = {"DOI": "10.1000/wos", "Document Type": "Article; Proceedings Paper",
           "Authors": "Zhang, WJ; Yuan, L; Zheng, BL",
           "Author Full Names": "Zhang, Wenjie; Yuan, Long; Zheng, Bolong"}
    row.update(overrides)
    return process_wos_row(pd.Series(row))


def test_wos_preserves_nonempty_input_fields_and_tag_aliases():
    record = wos(Abstract="Full abstract", **{
        "Author Keywords": "one; two", "Keywords Plus": "fallback",
        "Number of Pages": "13", "DOI Link": "https://doi.org/10.1000/wos",
        "Cited References": "Reference A; Reference B"})
    assert record['摘要'] == 'Full abstract'
    assert record['关键词'] == 'one; two'
    assert record['页数'] == '13'
    assert record['URL'] == 'https://doi.org/10.1000/wos'
    assert record['参考文献'] == 'Reference A; Reference B'
    tagged = process_wos_row(pd.Series({"AB": "abstract", "DE": "keyword", "PG": "8", "CR": "reference"}))
    assert [tagged[x] for x in ['摘要','关键词','页数','参考文献']] == ['abstract','keyword','8','reference']
    assert wos(**{'Keywords Plus': 'fallback'})['关键词'] == 'fallback'


def test_wos_cached_hyperlink_zero_is_not_exported_as_a_url():
    assert wos(**{'DOI Link':'0', 'Web of Science Record':'0'})['URL'] == 'https://doi.org/10.1000/wos'
    assert wos(**{'DOI':'', 'DOI Link':'0', 'Web of Science Record':'0'})['URL'] == ''
    assert wos(**{'DOI Link':'0', 'URL':'https://example.org/paper'})['URL'] == 'https://example.org/paper'
    assert wos(**{'DOI':'n/a','DOI Link':'javascript:alert(1)'})['URL'] == ''


def test_wos_parallel_author_fields_resolve_pinyin_initials():
    record = wos(**{'Reprint Addresses': 'Zhang, WJ (corresponding author), Institute A.'})
    assert record['通讯作者'] == 'Zhang, Wenjie'
    assert record['通讯作者单位'] == 'Institute A.'
    assert record['通讯作者—单位关联冲突原因'] == ''
    assert record['作者'].startswith('Zhang, Wenjie (1)')


def test_wos_multiple_authors_groups_and_repeated_person_do_not_cross_assign():
    record = wos(**{'Reprint Addresses': (
        'Yuan, L; Zheng, BL (corresponding author), Institute A.; '
        'Zhang, WJ (reprint author), Institute B.; '
        'Zhang, WJ (corresponding author), Institute C.')})
    assert record['通讯作者'] == 'Yuan, Long; Zheng, Bolong; Zhang, Wenjie'
    assert record['通讯作者单位'] == 'Institute A.; Institute B.; Institute C.'
    relations = record[CORRESPONDENCE_RELATIONS_KEY]['relations']
    assert relations == [
        {'name':'Yuan, Long','affiliations':['Institute A.']},
        {'name':'Zheng, Bolong','affiliations':['Institute A.']},
        {'name':'Zhang, Wenjie','affiliations':['Institute B.','Institute C.']},
    ]
    assert 'author)' not in record['通讯作者单位']
    for first, second in [(record, {'DOI': record['DOI'], '来源库': 'SCOPUS'}),
                          ({'DOI': record['DOI'], '来源库': 'SCOPUS'}, record)]:
        result = merge_records(deepcopy(first), deepcopy(second))
        assert result[CORRESPONDENCE_RELATIONS_KEY]['relations'] == relations


@pytest.mark.parametrize('short,full,candidate', [
    ('Li, M; Li, M', 'Li, Ming; Li, Mei', 'Li, M'),
    ('Zhang, WJ', 'Zhang, Wenjie; Yuan, Long', 'Zhang, WJ'),
    ('Zhang, WJ; Yuan, L', 'Yuan, Long; Zhang, Wenjie', 'Zhang, WJ'),
    ('Li, M', 'Li, Ming', 'Li, Mei'),
])
def test_unreliable_or_ambiguous_name_pairing_stays_in_review(short,full,candidate):
    record = wos(**{'Authors':short, 'Author Full Names':full,
                   'Reprint Addresses':candidate+' (corresponding author), Institute A.'})
    assert record['通讯作者—单位关联冲突原因']
    assert '(1)' not in record['作者']
    frames = split_output_frames(pd.DataFrame([record]))
    assert sum(len(frames[name]) for name in ['待复核_其他','待复核_可尝试原文补全']) == 1


def test_unresolved_person_is_not_discarded_among_multiple_groups():
    record = wos(**{'Reprint Addresses': 'Zhang, WJ (corresponding author), Institute A.; Unknown, U (corresponding author), Institute B.'})
    assert record['通讯作者'] == 'Zhang, Wenjie; Unknown, U'
    assert 'Unknown, U' in record['通讯作者—单位关联冲突原因']
    assert 'Institute B.' not in record['作者单位']


def test_missing_group_separator_is_not_guessed():
    record = wos(**{'Reprint Addresses': 'Zhang, WJ (corresponding author), Institute A. Yuan, L (corresponding author), Institute B.'})
    assert '缺少明确分隔符' in record['通讯作者—单位关联冲突原因']
    assert '(1)' not in record['作者']


def test_unknown_full_name_before_shared_marker_is_not_an_institution():
    raw = 'Alpha, A (corresponding author), Institute A.; Unknown, Person; Known, K (corresponding author), Institute B.'
    record = wos(**{'Authors':'Alpha, A; Known, K', 'Author Full Names':'Alpha, Alice; Known, Kevin', 'Reprint Addresses':raw})
    assert '边界不明确' in record['通讯作者—单位关联冲突原因']
    assert 'Unknown, Person' in record['通讯作者—单位关联冲突原因']
    assert record['作者单位'] == ''
    assert '(1)' not in record['作者']
    assert record[CORRESPONDENCE_RELATIONS_KEY]['relations'] == []
    assert record[CORRESPONDENCE_RELATIONS_KEY]['raw_affiliations'] == raw


def test_real_wos_file_output_field_coverage(tmp_path, monkeypatch):
    path = os.environ.get('WOS_REGRESSION_INPUT')
    if not path:
        pytest.skip('Set WOS_REGRESSION_INPUT to audit the original private input')
    import converter
    import scope_rules
    monkeypatch.setattr(scope_rules, 'DEFAULT_ALIAS_PATHS', [])
    monkeypatch.setattr(scope_rules, 'discover_article_library', lambda: None)
    monkeypatch.setattr(scope_rules, 'discover_account_file', lambda **kw: None)
    raw = pd.read_excel(path, dtype=str).fillna('')
    output_path = tmp_path / 'wos_result.xlsx'
    converter.run_conversion([path], output_path, 'local')
    frames = pd.read_excel(output_path, sheet_name=None, dtype=str)
    out = frames['全部数据'].fillna('')
    assert len(raw) == len(out) == 362
    for source, target in [('Article Title','题名'),('Document Type','原始文献类型'),
                           ('Abstract','摘要'),('Number of Pages','页数'),
                           ('UT (Unique WOS ID)','WOS记录号')]:
        assert out[target].tolist() == raw[source].tolist(), (source,target)
    for i, row in raw.iterrows():
        expected_keywords = converter.normalize_keywords(row['Author Keywords'] or row['Keywords Plus'])
        assert out.loc[i,'关键词'] == expected_keywords
        if row['DOI']:
            assert out.loc[i,'URL'] == 'https://doi.org/' + converter.normalize_doi(row['DOI'])
        else:
            assert out.loc[i,'URL'] == ''
    assert not out['URL'].eq('0').any()
    assert out['通讯作者—单位关联冲突原因'].eq('').all()
    assert not out['通讯作者单位'].str.contains(r'\((?:corresponding|reprint) author\)',regex=True,case=False).any()
    assert out.loc[raw['Reprint Addresses'].ne(''),'通讯作者'].ne('').all()
    assert len(frames['期刊论文']) == 228
    assert len(frames['会议论文']) == 133
    assert len(frames['待复核_可尝试原文补全']) == 25
    pending = frames['待复核_可尝试原文补全']
    pending_ids = set(pending['WOS记录号'])
    assert pending['复核原因'].str.contains('作者—单位关联').all()
    # Bare addresses may be resolved by explicit RP evidence; bracketed ones
    # may still omit a listed author. Neither group is a proxy for completeness.
    assert not pending_ids.intersection({'WOS:000187774500008', 'WOS:000085777500013', 'WOS:A1997YC98800004'})
    assert {'WOS:001124222100031', 'WOS:001054156204087', 'WOS:000306148300002'} <= pending_ids
    assert frames['待复核_其他'].empty
    assert out.loc[raw['DOI'].eq(''),'DOI'].eq('').sum() == 1
