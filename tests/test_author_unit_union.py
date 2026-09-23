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


@pytest.mark.parametrize('sources', [('SCOPUS', 'SCOPUS'), ('WOS', 'WOS'), ('WOS', 'SCOPUS')])
def test_different_units_survive_in_one_paper_and_require_review(sources):
    a = bundle(sources[0], **{'Li, Ming': ['Institute A']})
    b = bundle(sources[1], **{'Li, Ming': ['Institute B']})
    for left, right in [(a, b), (b, a)]:
        result = c.merge_author_bundles(left, right)
        assert graph(result) == {'Li, Ming': {'Institute A', 'Institute B'}}
        assert result['conflicts']
        reason = '；'.join(result['conflicts'])
        assert all(value in reason for value in ['Li, Ming', 'Institute A', 'Institute B', *sources])
        record_a = c.apply_author_bundle({'DOI': '10.1000/same', '原始文献类型': 'Article'}, left)
        record_b = c.apply_author_bundle({'DOI': '10.1000/same', '原始文献类型': 'Article'}, right)
        rows = c.merge_doi_group([record_a, record_b])
        assert len(rows) == 1
        assert graph(rows[0][c.AUTHOR_RELATIONS_KEY]) == graph(result)
        assert '作者—单位关联存在冲突' in s._author_metadata_review_issues(pd.Series(rows[0]))[0]


def test_yale_hierarchy_and_nber_complete_address_both_survive():
    yale = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    nber = 'NBER, Cambridge, MA 02138 USA'
    sources = [bundle('WOS', **{'Li, Ming': [yale]}),
               bundle('SCOPUS', **{'Li, Ming': ['Yale School of Management, New Haven, United States', 'NBER']}),
               bundle('EI', **{'Li, Ming': [nber]})]
    for sequence in permutations(sources):
        result = c.merge_author_bundles(c.merge_author_bundles(*sequence[:2]), sequence[2])
        assert graph(result) == {'Li, Ming': {yale, nber}}
        # Yale-only and NBER-only records disagree even if a third record
        # supplies both. Original evidence, not import order, controls review.
        assert result['conflicts']
        rendered = c._render_author_bundle(result)
        restored = c._author_bundle_from_record(rendered)
        assert graph(restored) == graph(result)  # Rebuilt indices retain exact edges.


@pytest.mark.parametrize('extra', [[], ['NBER']])
def test_equivalent_names_and_subset_completeness_do_not_require_conflict_review(extra):
    full = 'Yale Univ, Sch Management, New Haven, CT 06511 USA'
    short = 'Yale School of Management, New Haven, United States'
    a = bundle('WOS', **{'Li, Ming': [full]})
    b = bundle('SCOPUS', **{'Li, Ming': [short, *extra]})
    for left, right in [(a, b), (b, a)]:
        result = c.merge_author_bundles(left, right)
        assert graph(result) == {'Li, Ming': {full, *extra}}
        assert not result['conflicts']


def test_partial_overlap_is_distinct_units_not_missing_evidence():
    a = bundle('WOS', **{'Li, Ming': ['Institute A', 'Institute B']})
    b = bundle('WOS', **{'Li, Ming': ['Institute A', 'Institute C']})
    for left, right in [(a, b), (b, a)]:
        result = c.merge_author_bundles(left, right)
        assert graph(result) == {'Li, Ming': {'Institute A', 'Institute B', 'Institute C'}}
        assert result['conflicts']


@pytest.mark.parametrize('long_name,short_name', [
    ('Cornell Univ, Johnson Grad Sch Management, Ithaca, NY 14853 USA',
     'Cornell SC Johnson College of Business, Ithaca, United States'),
    ('Chinese Univ Hong Kong, CUHK Business Sch, Hong Kong, Peoples R China',
     'CUHK Business School, Hong Kong, Hong Kong'),
    ('Chinese Univ Hong Kong, Sch Management & Econ, Shenzhen 518172, Guangdong, Peoples R China',
     'The Chinese University of Hong Kong, Shenzhen, Shenzhen, China'),
    ('Dartmouth Coll, Tuck Sch Business, Hanover, NH 03755 USA',
     'Tuck School of Business at Dartmouth, Hanover, United States'),
    ('Univ Penn, Philadelphia, PA 19104 USA',
     'University of Pennsylvania, Philadelphia, United States'),
    ('Univ Michigan, Ross Sch Business, Ann Arbor, MI 48109 USA',
     'Stephen M. Ross School of Business, Ann Arbor, United States'),
    ('Duke Univ, Fuqua Sch Business, Durham, NC 27708 USA',
     'Fuqua School of Business, Durham, United States'),
])
def test_known_institution_hierarchy_prefers_detailed_original_without_review(long_name, short_name):
    for left, right in [(long_name, short_name), (short_name, long_name)]:
        result = c.merge_author_bundles(bundle('WOS', **{'Li, Ming': [left]}),
                                         bundle('SCOPUS', **{'Li, Ming': [right]}))
        assert graph(result) == {'Li, Ming': {long_name}}
        assert not result['conflicts']


def test_same_parent_but_different_campus_or_department_stays_in_review():
    cases = [
        ('CUHK Business School, Hong Kong, Hong Kong',
         'Chinese Univ Hong Kong, Sch Management & Econ, Shenzhen 518172, Guangdong, Peoples R China'),
        ('Chinese Univ Hong Kong, CUHK Business Sch, Hong Kong, Peoples R China',
         'Chinese Univ Hong Kong, Dept Econ, Shatin, Hong Kong, Peoples R China'),
    ]
    for left, right in cases:
        result = c.merge_author_bundles(bundle('WOS', **{'Li, Ming': [left]}),
                                         bundle('SCOPUS', **{'Li, Ming': [right]}))
        assert graph(result) == {'Li, Ming': {left, right}}
        assert result['conflicts']


def test_third_record_cannot_mask_a_conflict_or_make_it_order_dependent():
    sources = [bundle('SCOPUS', **{'Li, Ming': ['Institute A']}),
               bundle('SCOPUS', **{'Li, Ming': ['Institute B']}),
               bundle('SCOPUS', **{'Li, Ming': ['Institute A', 'Institute B']})]
    conflicts = []
    for sequence in permutations(sources):
        result = c.merge_author_bundles(c.merge_author_bundles(*sequence[:2]), sequence[2])
        assert graph(result) == {'Li, Ming': {'Institute A', 'Institute B'}}
        assert result['conflicts']
        conflicts.append(set(result['conflicts']))
    assert all(value == conflicts[0] for value in conflicts)


def test_original_unit_observations_follow_author_identity_not_position():
    sources = [bundle('WOS', **{'Li, Ming': ['Institute A'], 'Wu, Wei': ['Institute C']}),
               bundle('SCOPUS', **{'Wu, Wei': ['Institute C'], 'Li, Ming': ['Institute B']}),
               bundle('WOS', **{'Li, Ming': ['Institute A', 'Institute B'], 'Wu, Wei': []})]
    for sequence in permutations(sources):
        result = c.merge_author_bundles(c.merge_author_bundles(*sequence[:2]), sequence[2])
        assert graph(result) == {'Li, Ming': {'Institute A', 'Institute B'}, 'Wu, Wei': {'Institute C'}}
        assert result['conflicts']
        assert all('Li, Ming' in reason and 'Wu, Wei' not in reason for reason in result['conflicts'])


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
    result = c.merge_author_bundles(bundle('WOS', **{'Li, Ming': [a]}),
                                     bundle('SCOPUS', **{'Li, Ming': [b]}))
    assert graph(result) == {'Li, Ming': {a, b}}
    assert result['conflicts']


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
