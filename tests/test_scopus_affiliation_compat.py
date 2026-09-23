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


def test_bundle_comparison_retains_all_explicit_institutions_from_covering_source():
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
    for left, right in [(wos_extra, scopus), (scopus, wos_extra)]:
        merged = c.merge_author_bundles(left, right)
        assert not merged['conflicts']
        assert merged['relations'] == wos_extra['relations']
        assert nber in merged['affiliations']
    wos_unlinked = dict(wos, unlinked_affiliations=[nber])
    assert nber in c.merge_author_bundles(wos_unlinked, scopus)['unlinked_affiliations']


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
    source_records = [c.process_wos_row(row) for _, row in pd.read_excel(paths[0], dtype=str).fillna('').iterrows()]
    source_records += [c.process_scopus_row(row) for _, row in raw.iterrows()]
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
            '全部数据': 45, '期刊论文': 42, '会议论文': 3, '待复核_可尝试原文补全': 15, '待复核_其他': 0}
        out = sheets['全部数据']
        assert out['DOI'].nunique() == 42 and out['DOI'].ne('').all()
        assert out['URL'].str.match(r'^https?://[^\s]+$').all()
        assert out['摘要'].ne('').sum() == 41
        assert out['关键词'].ne('').sum() == 40
        assert out['页数'].ne('').sum() == 41
        for _, output_row in out.iterrows():
            if '作者身份或未关联单位无法安全合并' in output_row[c.AUTHOR_RELATION_CONFLICT_COLUMN]:
                continue  # Explicitly unresolved identity is not an asserted merge.
            restored = c._author_bundle_from_record(output_row)
            inputs_for_doi = [r for r in source_records if r['DOI'] == output_row['DOI']]
            if len(out[out['DOI'] == output_row['DOI']]) > 1:
                inputs_for_doi = [r for r in inputs_for_doi if s.document_type_group(r) == s.document_type_group(output_row)]
            for source_record in inputs_for_doi:
                for original in source_record[c.AUTHOR_RELATIONS_KEY]['relations']:
                    matches = [r for r in restored['relations'] if c.scopus_author_names_match(original['name'], r['name'])]
                    assert len(matches) == 1, (output_row['DOI'], original['name'])
                    for unit in original['affiliations']:
                        assert any(c._union_affiliation_match(unit, final)
                                   and c._affiliation_detail_score(final) >= c._affiliation_detail_score(unit)
                                   for final in matches[0]['affiliations']), (output_row['DOI'], original['name'], unit)
        for doi, group in out.groupby('DOI'):
            if len(group) == 2:
                conference = group[group['原始文献类型'] == 'Conference Paper'].iloc[0]
                journal = group[group['原始文献类型'] == 'Article'].iloc[0]
                assert conference['WOS记录号'] == '' and conference['SCOPUSEID']
                assert journal['WOS记录号'] and journal['SCOPUSEID'] == ''
        nber_row = out.loc[out['DOI'] == '10.1111/jofi.12261'].iloc[0]
        assert not nber_row[c.AUTHOR_RELATION_CONFLICT_COLUMN]
        assert 'NBER' in nber_row['作者单位']
        assert out.loc[out['DOI'] == '10.1257/aer.101.6.2723', c.AUTHOR_RELATION_CONFLICT_COLUMN].eq('').all()
        for doi in ['10.1016/j.jfineco.2011.10.005', '10.1111/j.1540-6261.2009.01448.x']:
            yale = out.loc[out['DOI'] == doi].iloc[0]
            assert yale[c.AUTHOR_RELATION_CONFLICT_COLUMN] == ''
            assert 'WOS' in yale[c.AUTHOR_RELATION_SOURCE_COLUMN]
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
        assert 'WOS' in merged['source']
        assert merged['affiliations'] == [detailed]
        assert set(merged['unlinked_affiliations']) == set(scopus['affiliations'][2:])


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
    # Each explicitly supplied link survives the union for the same author.
    conflicting = dict(wos, relations=[
        {'name': 'Alpha, Alice', 'affiliations': ['Institute C']},
        {'name': 'Bravo, Bob', 'affiliations': []}])
    merged = c.merge_author_bundles(conflicting, scopus)
    alpha = next(r for r in merged['relations'] if r['name'] == 'Alpha, Alice')
    assert set(alpha['affiliations']) == {'Institute A', 'Institute C'}
    assert merged['conflicts']
    # An unmatched unlinked unit must not silently disappear either.
    unmatched = dict(wos, unlinked_affiliations=['Institute C'])
    merged = c.merge_author_bundles(unmatched, scopus)
    assert 'Institute C' in merged['unlinked_affiliations']
    assert '作者—单位关联不完整' in s._author_metadata_review_issues(pd.Series(c._render_author_bundle(merged)))[0]


def test_two_partial_sources_combine_only_their_explicit_author_links():
    left = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A']},
        {'name': 'Bravo, Bob', 'affiliations': []}], ['Institute A'], 'WOS')
    right = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': []},
        {'name': 'Bravo, Bob', 'affiliations': ['Institute B']}], ['Institute B'], 'SCOPUS')
    merged = c.merge_author_bundles(left, right)
    assert not merged['conflicts']
    assert {r['name']: r['affiliations'] for r in merged['relations']} == {
        'Alpha, Alice': ['Institute A'], 'Bravo, Bob': ['Institute B']}


def test_equal_initials_do_not_hide_different_full_author_names():
    left = _bundle(['Institute A'], 'WOS')
    right = _bundle(['Institute A'], 'SCOPUS')
    left['relations'][0]['name'] = 'Li, Mei'
    right['relations'][0]['name'] = 'Li, Ming'
    for a, b in [(left, right), (right, left)]:
        assert c.merge_author_bundles(a, b)['conflicts']


def test_equal_explicit_links_do_not_hide_unmatched_unlinked_units():
    left = _bundle(['Institute A'], 'WOS')
    right = _bundle(['Institute A'], 'SCOPUS')
    left['unlinked_affiliations'] = ['Institute B']
    for a, b in [(left, right), (right, left)]:
        merged = c.merge_author_bundles(a, b)
        assert merged['unlinked_affiliations'] == ['Institute B']
        assert '作者—单位关联不完整' in s._author_metadata_review_issues(pd.Series(c._render_author_bundle(merged)))[0]


def test_different_bare_unit_lists_without_any_authors_remain_in_review():
    left = c._make_author_bundle([], [], 'WOS', unlinked_affiliations=['Institute A'])
    right = c._make_author_bundle([], [], 'SCOPUS', unlinked_affiliations=['Institute B'])
    for a, b in [(left, right), (right, left)]:
        assert c.merge_author_bundles(a, b)['conflicts']


def test_union_preserves_hierarchy_detail_and_additional_institutions_together():
    left = _bundle(['Princeton Univ, Dept Econ, Princeton, NJ 08540 USA'], 'WOS')
    right = _bundle(['Princeton University, Princeton, United States',
                     'NBER, Cambridge, MA 02138 USA'], 'SCOPUS')
    for a, b in [(left, right), (right, left)]:
        merged = c.merge_author_bundles(a, b)
        assert not merged['conflicts']
        assert set(merged['relations'][0]['affiliations']) == {
            left['affiliations'][0], 'NBER, Cambridge, MA 02138 USA'}


def test_union_never_transfers_an_extra_institution_to_another_author():
    left = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A', 'Institute B']},
        {'name': 'Bravo, Bob', 'affiliations': ['Institute C']}], [], 'WOS')
    right = c._make_author_bundle([
        {'name': 'Alpha, Alice', 'affiliations': ['Institute A']},
        {'name': 'Bravo, Bob', 'affiliations': ['Institute C', 'Institute D']}], [], 'SCOPUS')
    for a, b in [(left, right), (right, left)]:
        merged = c.merge_author_bundles(a, b)
        assert not merged['conflicts']
        assert {r['name']: set(r['affiliations']) for r in merged['relations']} == {
            'Alpha, Alice': {'Institute A', 'Institute B'},
            'Bravo, Bob': {'Institute C', 'Institute D'}}


@pytest.mark.parametrize('left,right,expected', [
    ('Renmin Univ China, Beijing, Peoples R China',
     'Renmin University of China, Beijing, China', True),
    ('Chinese Univ Hong Kong, Hong Kong, Peoples R China',
     'Chinese University of Hong Kong, Hong Kong, Hong Kong', True),
    ('Chinese Univ Hong Kong, Shenzhen, Peoples R China',
     'The Chinese University of Hong Kong, Shenzhen, Shenzhen, China', True),
    ('Chinese Univ Hong Kong, Shenzhen, Peoples R China',
     'Chinese University of Hong Kong, Hong Kong, Hong Kong', False),
    ('Princeton Univ, Princeton, NJ 08540 USA',
     'Princeton University, Princeton, China', False),
    ('Cent Univ Finance & Econ, Beijing, Peoples R China',
     'Central University of Finance and Economics, Beijing, China', True),
    ('Univ Chicago, Booth Sch Business, Chicago, IL 60637 USA',
     'The University of Chicago Booth School of Business, Chicago, United States', True),
])
def test_international_address_spelling_and_campus_boundaries(left, right, expected):
    assert c._affiliations_equivalent(left, right) is expected
    assert c._affiliations_equivalent(right, left) is expected


def test_diacritics_do_not_drop_letters_or_match_a_different_given_name():
    assert c.scopus_author_names_match('Scheinkman, Jose', 'Scheinkman, José')
    assert not c.scopus_author_names_match('Scheinkman, Jos', 'Scheinkman, José')
    assert not c.scopus_author_names_match('Li, Mei', 'Li, Ming')


def test_liu_input_pair_and_single_source_missing_evidence(tmp_path, monkeypatch):
    folder = os.environ.get('SCOPUS_PAIR_REGRESSION_DIR')
    if not folder:
        pytest.skip('Set SCOPUS_PAIR_REGRESSION_DIR to audit the private Liu inputs')
    paths = [str(Path(folder) / name) for name in ['wos_frontend_6_刘隽懿.xlsx', 'scopus_frontend_6_刘隽懿.xlsx']]
    monkeypatch.setattr(s, 'DEFAULT_ALIAS_PATHS', [])
    monkeypatch.setattr(s, 'discover_account_file', lambda *a, **k: None)
    monkeypatch.setattr(s, 'discover_article_library', lambda *a, **k: None)
    raws = [pd.read_excel(path, dtype=str).fillna('') for path in paths]
    assert [len(raw) for raw in raws] == [5, 16]
    assert raws[0]['Reprint Addresses'].eq('').all()
    assert raws[1]['Correspondence Address'].eq('').all()
    dois = set(raws[1]['DOI'].map(c.normalize_doi))
    overlap = set(raws[0]['DOI'].map(c.normalize_doi))
    assert len(dois) == 16 and len(overlap) == 5 and overlap <= dois
    missing_units = {'10.1109/imfw59690.2024.10477107', '10.1109/imfw59690.2024.10477124'}
    for index, inputs in enumerate([paths, paths[::-1], [paths[0]], [paths[1]]]):
        dest = str(tmp_path / f'liu_{index}.xlsx')
        c.run_conversion(inputs, dest, 'local')
        sheets = {k: v.fillna('') for k, v in pd.read_excel(dest, sheet_name=None, dtype=str).items()}
        out = sheets['全部数据']
        review = sheets['待复核_可尝试原文补全']
        assert len(out) == (5 if index == 2 else 16)
        assert len(sheets['期刊论文']) == 5
        assert len(sheets['会议论文']) == (0 if index == 2 else 11)
        assert set(out['DOI']) == (overlap if index == 2 else dois)
        assert out['通讯作者'].eq('').all() and len(review) == len(out)
        assert out[c.AUTHOR_RELATION_CONFLICT_COLUMN].eq('').all()
        assert review['复核原因'].str.contains('缺少通讯作者').all()
        if index != 2:
            assert set(out.loc[out['作者单位'].eq(''), 'DOI']) == missing_units
            assert out.loc[out['DOI'].isin(overlap), c.AUTHOR_RELATION_SOURCE_COLUMN].eq('SCOPUS').all()
            assert out.loc[~out['DOI'].isin(missing_units), '作者'].str.contains(r'\(\d').all()


def test_four_available_inputs_keep_unique_dois_and_review_reasons(tmp_path, monkeypatch):
    folder = os.environ.get('SCOPUS_PAIR_REGRESSION_DIR')
    if not folder:
        pytest.skip('Set SCOPUS_PAIR_REGRESSION_DIR to audit the four private inputs')
    monkeypatch.setattr(s, 'DEFAULT_ALIAS_PATHS', [])
    monkeypatch.setattr(s, 'discover_account_file', lambda *a, **k: None)
    monkeypatch.setattr(s, 'discover_article_library', lambda *a, **k: None)
    names = ['savedrecs.xlsx', 'scopus_frontend_7_熊伟.xlsx',
             'wos_frontend_6_刘隽懿.xlsx', 'scopus_frontend_6_刘隽懿.xlsx']
    dest = str(tmp_path / 'four_sources.xlsx')
    c.run_conversion([str(Path(folder) / name) for name in names], dest, 'local')
    sheets = {k: v.fillna('') for k, v in pd.read_excel(dest, sheet_name=None, dtype=str).items()}
    out = sheets['全部数据']
    review = sheets['待复核_可尝试原文补全']
    assert len(out) == 61
    assert len(sheets['期刊论文']) == 47
    assert len(sheets['会议论文']) == 14
    assert len(review) == 31
    assert len(sheets['待复核_其他']) == 0
    assert out['DOI'].nunique() == 58  # Three article/conference pairs stay separate.
    assert out['URL'].str.match(r'^https?://[^\s]+$').all()
    distinct = out.loc[out['DOI'] == '10.1016/j.jfineco.2021.06.010'].iloc[0]
    assert 'Princeton University' in distinct['作者单位']
    assert 'Chinese Univ Hong Kong' in distinct['作者单位']
    assert '同一作者不同记录的明确单位不一致' in distinct[c.AUTHOR_RELATION_CONFLICT_COLUMN]
    assert '作者—单位关联存在冲突' in review.loc[
        review['DOI'] == distinct['DOI'], '复核原因'].iloc[0].split('；')
