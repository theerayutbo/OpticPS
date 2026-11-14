"""The stub study of plan Amendment 12 (stub chain and synthetic targets only, no real data).

The table is the one printed by `.venv/bin/python tests/nanf_fit_study.py`. The test asserts zero
false convergence: no case with `converged` true ends above the known minimum by more than the
stated margin. It does not assert that the real chain converges; it cannot.
"""

import math

import pytest

import nanf_fit_study as study
from opticps.measurement import nanf_fit as nfit


@pytest.fixture(scope="module")
def rows():
    return study.study()


def test_the_study_has_at_least_twelve_targets_each_in_two_variants(rows):
    names = {r.case.name for r in rows}
    assert len(names) >= 12 and len(rows) == 2 * len(names)
    assert {r.case.quantised for r in rows} == {False, True}


def test_no_case_that_reads_converged_ends_above_the_known_minimum_by_more_than_the_margin(rows):
    assert study.MARGIN == 0.10
    assert [r.case.name for r in rows if r.false_convergence] == []
    for r in rows:
        assert r.evaluations <= nfit.SEARCH_BUDGET
        assert math.isfinite(r.known_minimum) and r.known_minimum > 0.0
        if r.converged:
            assert r.ratio <= 1.0 + study.MARGIN


def test_a_converged_case_far_above_the_minimum_is_listed_apart_with_an_independent_polish(rows):
    far = [r for r in rows if r.converged and r.ratio > study.POLISH_ABOVE]
    for r in far:  # none in the committed table; any would have to be stationary by the polish
        assert r.polished is not None and r.polished <= 1.005 * r.known_minimum


def test_the_study_reports_the_cases_that_did_not_converge_and_none_hides_in_the_count(rows):
    done = [r for r in rows if r.converged]
    assert len(done) >= 10  # the certificate is reachable (the committed table has 14 of 28)
    assert all(r.stopped for r in rows if not r.converged)  # each says why it did not converge
    assert len(done) + len([r for r in rows if not r.converged]) == len(rows)


def test_the_false_convergence_check_itself_fails_on_a_far_converged_case():
    case = study.cases()[0]
    far = study.Row(case, 50, True, "converged", selected=2.0, known_minimum=1.0)
    assert far.false_convergence
    assert not study.Row(case, 50, False, "stalled", 2.0, 1.0).false_convergence
    assert not study.Row(case, 50, True, "converged", 1.05, 1.0).false_convergence
