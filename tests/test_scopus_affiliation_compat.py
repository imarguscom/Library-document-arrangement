"""Conservative name/address compatibility; private inputs are opt-in."""
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

import converter as c
import scope_rules as s


@pytest.mark.parametrize('full,short', [
    ('(Jinfan) Chang, Jeffery', '(Jinfan) Chang J.'),
    ('Cheng, Ing Haw', 'Cheng I.'),
    ('Brunnermeier, Markus K.', 'Brunnermeier M.'),
    ('Ou-Yang, Hui', 'Ou-Yang H.'),
    ('Ou-Yang, Hui', 'H. Ou-Yang'),
    ('van der Waals, Johannes', 'van der Waals J.'),
])
def test_scopus_name_variants_use_explicit_same_row_links(full, short):
    entry = f'{short} (University A (Main Campus), City; University B, City)'
    bundle = c.build_scopus_author_bundle([full], [entry], [])
    assert not bundle['conflicts']
    assert bundle['relations'] == [{'name': full, 'affiliations': [
        'University A (Main Campus), City', 'University B, City']}]


@pytest.mark.parametrize('names,entries', [
    (['Li, Mei', 'Li, Ming'], ['Li M. (Institute A)']),
    (['Li, Mei', 'Li, Ming'], ['Li M. (Institute A)', 'Li M. (Institute B)']),
    (['Cheng, Ing Haw', 'Cheng, Ian Henry'], ['Cheng I. (Institute A)']),
    (['Li, Ming'], ['Li, Mei (Institute A)']),
    (['Li, Ming H.'], ['Li, Mei H. (Institute A)']),
    (['Ou, Yang Hui'], ['Ou-Yang H. (Institute A)']),
    (['Li, Ming H.'], ['Li M.K. (Institute A)']),
])
def test_incompatible_or_ambiguous_names_do_not_gain_affiliations(names, entries):
    bundle = c.build_scopus_author_bundle(names, entries, [])
    assert bundle['conflicts']
    assert all(not relation['affiliations'] for relation in bundle['relations'])


def test_distinct_complete_initials_take_precedence_over_short_initial_fallback():
    bundle = c.build_scopus_author_bundle(
        ['Xiong, Wei A.', 'Xiong, Wei'],
        ['Xiong W. (Princeton University)', 'Xiong W.A. (Shenzhen Stock Exchange)'], [])
    assert not bundle['conflicts']
    assert [r['affiliations'] for r in bundle['relations']] == [
        ['Shenzhen Stock Exchange'], ['Princeton University']]


@pytest.mark.parametrize('left,right,expected', [
    ('Princeton Univ, Dept Econ, Princeton, NJ 08540 USA',
     'Princeton University, Princeton, United States', True),
    ('Univ Texas Austin, Austin, TX 78712 USA',
     'The University of Texas at Austin, Austin, United States', True),
    ('Natl Bur Econ Res, Cambridge, MA 02138 USA',
     'National Bureau of Economic Research, Cambridge, United States', True),
    ('Dartmouth Coll, Hanover, NH 03755 USA',
     'Dartmouth College, Hanover, United States', True),
    ('Duke Univ, Fuqua Sch Business, Durham, NC 27708 USA',
     'Fuqua School of Business, Durham, United States', False),
    ('Princeton Univ, Dept Physics, Princeton, NJ 08540 USA',
     'Princeton Univ, Dept Econ, Princeton, NJ 08540 USA', False),
    ('University California, Berkeley, CA 94720 USA',
     'University California, Los Angeles, United States', False),
    ('University California, Berkeley Campus, Berkeley, CA 94720 USA',
     'University California, Berkeley, United States', False),
    ('Princeton Univ, Princeton, NJ 08540 USA',
     'Princeton University, Princeton, IN 47670 USA', False),
    ('Princeton Univ, Princeton, NJ 08540 USA',
     'Princeton University Press, Princeton, United States', False),
    ('Chinese Univ Hong Kong, Shenzhen, Peoples R China',
     'Chinese University of Hong Kong, Hong Kong, Hong Kong', False),
])
def test_institution_equivalence_is_explicit_and_symmetric(left, right, expected):
    assert c._affiliations_equivalent(left, right) is expected
    assert c._affiliations_equivalent(right, left) is expected


def _bundle(affiliations, source):
    return c._make_author_bundle([{'name': 'Xiong, Wei', 'affiliations': affiliations}], affiliations, source)


def test_bundle_comparison_allows_department_detail_but_not_an_added_institution():
    wos = _bundle([
        'Princeton Univ, Dept Econ, Princeton, NJ 08540 USA',
        'Princeton Univ, Bendheim Ctr Finance, Princeton, NJ 08540 USA'], 'WOS')
    scopus = _bundle(['Princeton University, Princeton, United States'], 'SCOPUS')
    for left, right in [(wos, scopus), (scopus, wos)]:
        merged = c.merge_author_bundles(left, right)
        assert not merged['conflicts']
        assert merged['relations'] == wos['relations']  # Preserve detailed atomic bundle.
    nber = 'NBER, Cambridge, MA 02138 USA'
    wos_extra = _bundle([*wos['affiliations'], nber], 'WOS')
    assert c.merge_author_bundles(wos_extra, scopus)['conflicts']
    assert c.merge_author_bundles(scopus, wos_extra)['conflicts']
    wos_unlinked = dict(wos, unlinked_affiliations=[nber])
    assert c.merge_author_bundles(wos_unlinked, scopus)['conflicts']


def test_equivalence_does_not_collapse_two_different_full_given_names():
    wos = _bundle(['Princeton University, Princeton, United States'], 'WOS')
    scopus = _bundle(['Princeton Univ, Princeton, NJ 08540 USA'], 'SCOPUS')
    wos['relations'][0]['name'] = 'Li, Mei'
    scopus['relations'][0]['name'] = 'Li, Ming'
    assert c.merge_author_bundles(wos, scopus)['conflicts']


def test_original_pair_roundtrip_and_input_order(tmp_path, monkeypatch):
    folder = os.environ.get('SCOPUS_PAIR_REGRESSION_DIR')
    if not folder:
        pytest.skip('Set SCOPUS_PAIR_REGRESSION_DIR to audit the two private inputs')
    paths = [str(Path(folder) / name) for name in ['savedrecs.xlsx', 'scopus_frontend_7_熊伟.xlsx']]
    monkeypatch.setattr(s, 'DEFAULT_ALIAS_PATHS', [])
    monkeypatch.setattr(s, 'discover_account_file', lambda *a, **k: None)
    monkeypatch.setattr(s, 'discover_article_library', lambda *a, **k: None)
    raw = pd.read_excel(paths[1], dtype=str).fillna('')
    assert len(raw) == 44
    for _, row in raw.iterrows():
        record = c.process_scopus_row(row)
        assert not record[c.AUTHOR_RELATION_CONFLICT_COLUMN]
        relations = record[c.AUTHOR_RELATIONS_KEY]['relations']
        if '(' in row['Authors with affiliations']:
            assert all(relation['affiliations'] for relation in relations)
        else:
            # This real record provides names only. Do not invent units.
            assert row['Title'] == 'Decentralization through Tokenization'
            assert all(not relation['affiliations'] for relation in relations)
    outputs = []
    for index, inputs in enumerate([paths, paths[::-1]]):
        dest = str(tmp_path / f'pair_{index}.xlsx')
        c.run_conversion(inputs, dest, 'local')
        sheets = pd.read_excel(dest, sheet_name=None, dtype=str)
        sheets = {k: v.fillna('') for k, v in sheets.items()}
        assert {k: len(sheets[k]) for k in ['全部数据', '期刊论文', '会议论文', '待复核_可尝试原文补全', '待复核_其他']} == {
            '全部数据': 45, '期刊论文': 42, '会议论文': 3, '待复核_可尝试原文补全': 34, '待复核_其他': 0}
        out = sheets['全部数据']
        assert out['DOI'].nunique() == 42 and out['DOI'].ne('').all()
        assert out['URL'].str.match(r'^https?://[^\s]+$').all()
        assert out['摘要'].ne('').sum() == 41
        assert out['关键词'].ne('').sum() == 40
        assert out['页数'].ne('').sum() == 41
        for doi, group in out.groupby('DOI'):
            if len(group) == 2:
                conference = group[group['原始文献类型'] == 'Conference Paper'].iloc[0]
                journal = group[group['原始文献类型'] == 'Article'].iloc[0]
                assert conference['WOS记录号'] == '' and conference['SCOPUSEID']
                assert journal['WOS记录号'] and journal['SCOPUSEID'] == ''
        assert out.loc[out['DOI'] == '10.1111/jofi.12261', c.AUTHOR_RELATION_CONFLICT_COLUMN].ne('').all()
        assert out.loc[out['DOI'] == '10.1257/aer.101.6.2723', c.AUTHOR_RELATION_CONFLICT_COLUMN].eq('').all()
        for doi in ['10.1016/j.jfineco.2011.10.005', '10.1111/j.1540-6261.2009.01448.x']:
            yale = out.loc[out['DOI'] == doi].iloc[0]
            assert yale[c.AUTHOR_RELATION_CONFLICT_COLUMN] == ''
            assert yale[c.AUTHOR_RELATION_SOURCE_COLUMN] == 'WOS'
            assert 'Yale Univ, Sch Management' in yale['作者单位']
        outputs.append(Counter((row['DOI'], tuple(sorted(c.split_semicolon_values(row['原始文献类型']))))
                               for _, row in out.iterrows()))
    assert outputs[0] == outputs[1]


def test_explicit_yale_hierarchy_wins_in_both_input_orders():
    detailed = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    abbreviated = 'Yale School of Management, New Haven, United States'
    wos, scopus = _bundle([detailed], 'WOS'), _bundle([abbreviated], 'SCOPUS')
    for left, right in [(wos, scopus), (scopus, wos)]:
        merged = c.merge_author_bundles(left, right)
        assert not merged['conflicts']
        assert merged['source'] == 'WOS'
        assert merged['relations'] == wos['relations']
        assert merged['affiliations'] == [detailed]


def test_duplicate_coarse_addresses_do_not_outweigh_explicit_hierarchy():
    detailed = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    wos = _bundle([detailed], 'WOS')
    scopus = _bundle([
        'Yale School of Management, New Haven, United States',
        'Yale School of Management, New Haven, CT 06511 USA'], 'SCOPUS')
    # Unassigned master-list units do not prove richer author-linked evidence.
    scopus['affiliations'] += [
        'Other Univ, Dept Physics, New Haven, CT 06511 USA',
        'Other Univ, Dept Biology, New Haven, CT 06511 USA']
    for left, right in [(wos, scopus), (scopus, wos)]:
        merged = c.merge_author_bundles(left, right)
        assert not merged['conflicts']
        assert merged['source'] == 'WOS'
        assert merged['affiliations'] == [detailed]


@pytest.mark.parametrize('short', [
    'Yale School of Medicine, New Haven, United States',
    'Yale School of Management, New York, United States',
    'Yale School of Management, New Haven, IN 46774 USA',
    'Yale West School of Management, New Haven, United States',
    'School of Management, New Haven, United States',
])
def test_school_shorthand_cannot_hide_a_different_school_or_location(short):
    full = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    assert not c._affiliations_equivalent(full, short)
    assert not c._affiliations_equivalent(short, full)


def test_complete_source_resolves_missing_links_without_using_position():
    wos = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A']},
        {'name': 'Bravo, Bob', 'affiliations': []}],
        ['Institute A'], 'WOS', unlinked_affiliations=['Institute B'])
    scopus = c._make_author_bundle([
        {'name': 'Bravo, Bob', 'affiliations': ['Institute B']},
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A']}],
        ['Institute B', 'Institute A'], 'SCOPUS')
    for left, right in [(wos, scopus), (scopus, wos)]:
        merged = c.merge_author_bundles(left, right)
        assert not merged['conflicts']
        assert merged['relations'] == scopus['relations']
        assert c._render_author_bundle(merged)['作者'] == 'Bravo, Bob(1); Alpha, Alice(2)'
    # Already supplied contradictory links must not be mistaken for blanks.
    conflicting = dict(wos, relations=[
        {'name': 'Alpha, Alice', 'affiliations': ['Institute C']},
        {'name': 'Bravo, Bob', 'affiliations': []}])
    assert c.merge_author_bundles(conflicting, scopus)['conflicts']
    # An unmatched unlinked unit must not silently disappear either.
    unmatched = dict(wos, unlinked_affiliations=['Institute C'])
    assert c.merge_author_bundles(unmatched, scopus)['conflicts']


def test_two_partial_sources_are_not_mislabeled_as_one_complete_source():
    left = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A']},
        {'name': 'Bravo, Bob', 'affiliations': []}], ['Institute A'], 'WOS')
    right = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': []},
        {'name': 'Bravo, Bob', 'affiliations': ['Institute B']}], ['Institute B'], 'SCOPUS')
    assert c.merge_author_bundles(left, right)['conflicts']
