"""Graph-level checks for the user-approved per-author affiliation union."""
from itertools import permutations

import pandas as pd
import pytest

import converter as c
import scope_rules as s


def bundle(source, **authors):
    return c._make_author_bundle([
        {'name': name, 'affiliations': units} for name, units in authors.items()], [], source)


def graph(value):
    return {r['name']: set(r['affiliations']) for r in value['relations']}


@pytest.mark.parametrize('source', ['SCOPUS', 'WOS'])
def test_same_source_different_units_survive_without_extra_paper(source):
    a = bundle(source, **{'Li, Ming': ['Institute A']})
    b = bundle(source, **{'Li, Ming': ['Institute B']})
    for left, right in [(a, b), (b, a)]:
        result = c.merge_author_bundles(left, right)
        assert graph(result) == {'Li, Ming': {'Institute A', 'Institute B'}}
        assert not result['conflicts']
        record_a = c.apply_author_bundle({'DOI': '10.1000/same', '原始文献类型': 'Article'}, left)
        record_b = c.apply_author_bundle({'DOI': '10.1000/same', '原始文献类型': 'Article'}, right)
        rows = c.merge_doi_group([record_a, record_b])
        assert len(rows) == 1
        assert graph(rows[0][c.AUTHOR_RELATIONS_KEY]) == graph(result)


def test_yale_hierarchy_and_nber_complete_address_both_survive():
    yale = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    nber = 'NBER, Cambridge, MA 02138 USA'
    sources = [bundle('WOS', **{'Li, Ming': [yale]}),
               bundle('SCOPUS', **{'Li, Ming': ['Yale School of Management, New Haven, United States', 'NBER']}),
               bundle('EI', **{'Li, Ming': [nber]})]
    for sequence in permutations(sources):
        result = c.merge_author_bundles(c.merge_author_bundles(*sequence[:2]), sequence[2])
        assert graph(result) == {'Li, Ming': {yale, nber}}
        assert not result['conflicts']
        rendered = c._render_author_bundle(result)
        restored = c._author_bundle_from_record(rendered)
        assert graph(restored) == graph(result)  # Rebuilt indices retain exact edges.


def test_another_authors_department_is_never_borrowed():
    general = 'Princeton University, Princeton, United States'
    department = 'Princeton Univ, Dept Econ, Princeton, NJ 08540 USA'
    a = bundle('WOS', **{'Li, Ming': [general], 'Wu, Wei': [department]})
    b = bundle('SCOPUS', **{'Li, Ming': [general], 'Wu, Wei': [general]})
    for left, right in [(a, b), (b, a)]:
        assert graph(c.merge_author_bundles(left, right)) == {
            'Li, Ming': {general}, 'Wu, Wei': {department}}


def test_unlinked_department_cannot_be_attached_using_general_institution_match():
    general = 'Princeton University, Princeton, United States'
    department = 'Princeton Univ, Dept Econ, Princeton, NJ 08540 USA'
    a = bundle('WOS', **{'Li, Ming': []})
    a['unlinked_affiliations'] = [department]
    b = bundle('SCOPUS', **{'Li, Ming': [general]})
    result = c.merge_author_bundles(a, b)
    assert graph(result) == {'Li, Ming': {general}}
    assert result['unlinked_affiliations'] == [department]
    assert '作者—单位关联不完整' in s._author_metadata_review_issues(pd.Series(c._render_author_bundle(result)))[0]


def test_nber_short_name_cannot_choose_between_two_explicit_addresses():
    a = 'NBER, Cambridge, MA 02138 USA'
    b = 'NBER, Cambridge, MA 01238 USA'
    assert not c._union_affiliation_match(a, b)
    assert set(c._coalesce_author_units(['NBER', a, b])) == {'NBER', a, b}
    spelled_out = 'National Bureau of Economic Research, Cambridge, United States'
    assert c._coalesce_author_units([a, spelled_out]) == [a]


@pytest.mark.parametrize('source', ['WOS', 'SCOPUS'])
def test_same_initials_different_full_names_remain_unresolved(source):
    a = bundle(source, **{'Li, Ming': ['Institute A']})
    b = bundle(source, **{'Li, Mei': ['Institute B']})
    result = c.merge_author_bundles(a, b)
    assert result['conflicts']
    assert set(result['affiliations'] + result['unlinked_affiliations']) == {'Institute A', 'Institute B'}


def test_department_and_campus_differences_are_retained_as_distinct_units():
    units = ['Princeton Univ, Dept Econ, Princeton, NJ 08540 USA',
             'Princeton Univ, Dept Physics, Princeton, NJ 08540 USA',
             'Chinese Univ Hong Kong, Hong Kong, Peoples R China',
             'Chinese Univ Hong Kong, Shenzhen, Peoples R China']
    assert set(c._coalesce_author_units(units)) == set(units)
