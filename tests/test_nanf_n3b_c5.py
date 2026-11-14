"""N3b-2b: the C5 links as a run-time recipe, C5 in the verdict, the B2B-copy C2 and the marker rule
(plan Amendment 13). Synthetic workbooks, a stub chain and throw-away freeze records only: no real
workbook is opened and nothing is fitted.
"""

import dataclasses
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from nanf_fit_stub import objective  # noqa: F401  (keeps the stub module path on sys.path)
from nanf_freeze_support import patch_module_paths, session_repo
from nanf_holdout_stub import (
    FIG1_PARAMS,
    N_BITS,
    ROP_NANF_COLUMN,
    ROP_SSMF_COLUMN,
    WAVELENGTHS,
    base_snr,
    ber_of,
    fig1_d,
    fig1_series,
    holdout_workbook,
    lose_c5,
    make_stub,
    stub_point,
)
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_freeze
from opticps.measurement import nanf_holdout as nh
from opticps.measurement import nanf_import as ni
from opticps.measurement import nanf_scoring as sc
from opticps.measurement.nanf_chain import BerReading, PointResult
from opticps.optical_channel.fiber import FiberProfileError, OutOfValidityRangeError
from opticps.receiver.dfe import DfeResult

NAME = {"NANF": "NANF", "SSMF": "SSMF"}
GROUP_INDEX = {"NANF": 1.003, "SSMF": 1.4682}


@pytest.fixture
def frozen(tmp_path_factory, monkeypatch):
    repo = session_repo(tmp_path_factory)
    patch_module_paths(monkeypatch, repo)
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    return repo


class Reader:
    def __init__(self, wb):
        self.wb = wb

    def __call__(self, path, **kwargs):
        return self.wb


def run(frozen, tmp_path, wb=None, runner=stub_point):
    return nh.run_holdout(
        "unused.xlsx",
        frozen.hash,
        runner=runner,
        reader=Reader(holdout_workbook() if wb is None else wb),
        marker_path=tmp_path / "marker.json",
    )


def stub_equalizer(monkeypatch):
    def fake(samples, reference, cfg=None):
        n = samples.size // 2
        zeros = np.zeros(n)
        return DfeResult(
            zeros, zeros, np.zeros(n, dtype=np.int64), np.zeros(24), np.eye(24), 1.0, 0.0, 0
        )

    monkeypatch.setattr(nc, "rls_equalize", fake)


def with_series(wb, key, **changes):
    series = dict(wb.series)
    series[key] = dataclasses.replace(series[key], **changes)
    return ni.NanfWorkbook(wb.sha256, series)


# --- B2: the recipe ---------------------------------------------------------------------------


def test_the_recipe_builds_17_wavelengths_of_three_links_with_d_from_the_fig1_curve(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    links = nc.declare_c5_links(holdout_workbook())
    assert len(links) == 51 and nc.C5_WAVELENGTHS_NM == tuple(1460.0 + 10.0 * k for k in range(17))
    for wl in nc.C5_WAVELENGTHS_NM:
        for name, km in (("NANF", 4.76), ("SSMF", 4.53)):
            link = links[nc.c5_link_key(name, wl)]
            assert link == nc._paper_link(name, km, fig1_d(name, wl), GROUP_INDEX[name], wl)
            assert link.wavelength_nm == wl and link.profile is not None
            assert link.profile.length_km.value == km
            assert link.profile.dispersion_ps_per_nm_km.value == pytest.approx(fig1_d(name, wl))
            assert link.profile.attenuation_db_per_km.value == 0.0  # loss zero, matched power
            d_value = link.profile.dispersion_ps_per_nm_km
            assert d_value.provenance.measurement_wavelength_nm == wl  # D stated at its wavelength
        assert links[nc.c5_link_key("B2B", wl)] == nc.LinkSpec(None, wl)
    assert nc.declared_link(nc.c5_link_key("NANF", 1500.0)) is links["C5-NANF-1500"]


def test_d_follows_the_table_rule_linear_between_knots(monkeypatch):
    """A curve with knots 40 nm apart and a bend: D at 1460 is the interpolation, not a knot."""
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    wb = holdout_workbook()
    knots = [1400.0, 1440.0, 1480.0, 1520.0, 1560.0, 1600.0, 1625.0]
    d = [3.0, 2.0, 5.0, 4.0, 9.0, 7.0, 6.0]
    wb = with_series(
        wb, "Fig.1/a-CD/NANF", x=tuple(k / 1000.0 for k in knots), y=tuple(d),
        flags=tuple(wb["Fig.1/a-CD/NANF"].flags[: len(knots)]),
    )  # fmt: skip
    links = nc.declare_c5_links(wb)
    for wl in nc.C5_WAVELENGTHS_NM:
        got = links[nc.c5_link_key("NANF", wl)].profile.dispersion_ps_per_nm_km.value
        assert got == pytest.approx(float(np.interp(wl, knots, d)))


def test_a_curve_that_does_not_reach_1620_nm_is_an_error_and_declares_nothing(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    wb = holdout_workbook()
    short = fig1_series("SSMF")
    keep = 41  # 1400 to 1600 nm
    wb = with_series(
        wb, "Fig.1/a-CD/SSMF", x=short.x[:keep], y=short.y[:keep], flags=short.flags[:keep]
    )
    with pytest.raises(OutOfValidityRangeError, match="no extrapolation"):
        nc.declare_c5_links(wb)
    assert nc._RECIPE_LINKS == {}


def test_a_workbook_that_is_not_the_pinned_one_declares_nothing(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    with pytest.raises(ni.NanfImportError, match="pinned workbook"):
        nc.declare_c5_links(holdout_workbook(sha256="0" * 64))
    assert nc._RECIPE_LINKS == {}


def test_a_fig1_series_that_is_not_cross_check_is_refused(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    wb = with_series(holdout_workbook(), "Fig.1/a-CD/NANF", role=ni.DataRole.HOLDOUT)
    with pytest.raises(ValueError, match="cross-check"):
        nc.declare_c5_links(wb)
    assert nc._RECIPE_LINKS == {}


def test_a_second_declaration_replaces_the_first(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    nc.declare_c5_links(holdout_workbook())
    wb = holdout_workbook()
    wb = with_series(wb, "Fig.1/a-CD/NANF", y=tuple(v + 1.0 for v in wb["Fig.1/a-CD/NANF"].y))
    links = nc.declare_c5_links(wb)
    assert nc._RECIPE_LINKS == links and len(links) == 51
    assert links["C5-NANF-1500"].profile.dispersion_ps_per_nm_km.value == pytest.approx(
        fig1_d("NANF", 1500.0) + 1.0
    )


def test_an_undeclared_key_is_a_key_error_before_and_after_the_recipe(monkeypatch):
    monkeypatch.setattr(nc, "_RECIPE_LINKS", {})
    with pytest.raises(KeyError):
        nc.declared_link("C5-NANF-1500")
    nc.declare_c5_links(holdout_workbook())
    for key in ("C5-NANF-1630", "C5-NANF-1640", "C5-B2B-1630", "C5-NANF-1465", "SSMF-5km"):
        with pytest.raises(KeyError):
            nc.declared_link(key)
    assert nc.declared_link("NANF-4.76km-1550") is nc.DECLARED_LINKS["NANF-4.76km-1550"]


# --- B2: the link check of the scoring run ----------------------------------------------------


def reasons(link, point_index=0):
    result = nc.simulate_point(None, 112, -7.0, link=link, point_index=point_index)
    return result, [w for w in result.unscorable_reasons if "link not in the declared" in w]


def test_run_point_takes_a_recipe_link_only_after_the_recipe_and_nothing_else(frozen, monkeypatch):
    stub_equalizer(monkeypatch)
    wb = holdout_workbook()
    recipe = nc.LinkSpec(
        nc._paper_link("NANF", 4.76, fig1_d("NANF", 1500.0), 1.003, 1500.0).profile, 1500.0
    )
    _, refused = reasons(recipe, 4)
    assert refused  # the recipe has not run in this process: a C5 link is not scorable
    links = nc.declare_c5_links(wb)
    ok, refused = reasons(links["C5-NANF-1500"], 4)
    assert ok.scorable and not refused and ok.frozen_record_hash == frozen.hash
    assert nc.run_point("p", None, 112, -7.0, link=links["C5-SSMF-1500"], point_index=4).result
    assert nc.run_point("p", None, 112, -7.0, link=links["C5-B2B-1500"], point_index=4).result
    assert not reasons(nc.LinkSpec(None, 1500.0))[1]  # the recipe's back-to-back link at 1500 nm


def test_a_link_the_recipe_did_not_produce_is_refused(frozen, monkeypatch):
    stub_equalizer(monkeypatch)
    links = nc.declare_c5_links(holdout_workbook())
    base = links["C5-NANF-1500"]
    profile = base.profile
    assert profile is not None
    other_d = dataclasses.replace(
        profile,
        dispersion_ps_per_nm_km=dataclasses.replace(
            profile.dispersion_ps_per_nm_km, value=profile.dispersion_ps_per_nm_km.value + 0.5
        ),
    )
    other_length = dataclasses.replace(
        profile, length_km=dataclasses.replace(profile.length_km, value=4.9)
    )
    bad = {
        "another D": nc.LinkSpec(other_d, 1500.0),
        "another length": nc.LinkSpec(other_length, 1500.0),
        "another wavelength": dataclasses.replace(base, wavelength_nm=1510.0),
        "1630 nm": nc.LinkSpec(None, 1630.0),
        "1640 nm": nc.LinkSpec(None, 1640.0),
        "1465 nm": nc.LinkSpec(None, 1465.0),
        "1630 nm NANF": dataclasses.replace(links["C5-NANF-1620"], wavelength_nm=1630.0),
        "1640 nm SSMF": dataclasses.replace(links["C5-SSMF-1620"], wavelength_nm=1640.0),
    }
    for name, link in bad.items():
        if link.wavelength_nm > 1625.0 and link.profile is not None:
            # the profile of the curve's own band cannot even be resolved at 1630 or 1640 nm
            with pytest.raises(OutOfValidityRangeError):
                nc.simulate_point(None, 112, -7.0, link=link, point_index=4)
            continue
        result, refused = reasons(link, 4)
        assert refused and not result.scorable, name
        with pytest.raises(nc.NotScorableError):
            nc.run_point("p", None, 112, -7.0, link=link, point_index=4)


def test_the_links_at_1550_nm_and_the_default_link_behave_as_before(frozen, monkeypatch):
    stub_equalizer(monkeypatch)
    nc.declare_c5_links(holdout_workbook())  # the recipe is in force: nothing else changes
    for key in nc.DECLARED_LINKS:
        result, refused = reasons(nc.DECLARED_LINKS[key], 3)
        assert result.scorable and not refused, key
    assert nc.simulate_point(None, 112, -7.0, point_index=0).scorable  # back-to-back at 1550 nm
    assert reasons(nc.LinkSpec(None, 1300.0))[1]  # another wavelength stays refused
    moved = nc.LinkSpec(nc.DECLARED_LINKS["NANF-4.76km-1550"].profile, 1500.0)
    assert reasons(moved)[1] and not reasons(moved)[0].scorable


def test_a_paper_link_cannot_be_built_beyond_the_band_of_its_own_curves():
    with pytest.raises(FiberProfileError, match="provenance contradicts itself"):
        nc._paper_link("NANF", 4.76, 2.04, 1.003, 1630.0)  # the curves end at 1625 nm (B2)


def test_the_default_paper_link_is_unchanged_by_the_wavelength_argument():
    assert nc.DECLARED_LINKS["NANF-4.76km-1550"] == nc._paper_link(
        "NANF", 4.76, 2.04, 1.003, 1550.0
    )
    other = nc._paper_link("NANF", 4.76, 2.04, 1.003, 1500.0)
    assert other != nc.DECLARED_LINKS["NANF-4.76km-1550"] and other.wavelength_nm == 1500.0


# --- B3: the runner ---------------------------------------------------------------------------


def test_the_runner_declares_the_links_first_and_refuses_another_workbook_before_any_run(
    frozen, tmp_path
):
    calls = []

    def spy(task):
        calls.append(task)
        return stub_point(task)

    with pytest.raises(ni.NanfImportError, match="pinned workbook"):
        run(frozen, tmp_path, wb=holdout_workbook(sha256="1" * 64), runner=spy)
    assert calls == []
    run(frozen, tmp_path, runner=spy)
    assert len(nc._RECIPE_LINKS) == 51 and calls


def test_c5_is_scored_per_rate_and_link_with_the_published_columns(frozen, tmp_path):
    result = run(frozen, tmp_path)
    for rate, r in result.rates.items():
        c5 = r.c5
        assert (c5.nanf.n_points, c5.ssmf.n_points, c5.b2b.n_points) == (17, 17, 17)
        assert c5.nanf.excluded_nm == () and c5.passed and c5.lost == ()
        # the stub differs from the published curves by 0.2 dB at every wavelength
        assert c5.nanf.mean_abs_db == pytest.approx(0.2) and c5.ssmf.mean_abs_db == pytest.approx(
            0.2
        )
        assert c5.b2b.mean_abs_db == pytest.approx(0.2)
        # d: the NANF run against the back-to-back run of the same wavelength (0.3 dB apart)
        assert c5.d == pytest.approx(0.3) and not c5.discriminating
        # D3.1: the published B2B SNR as the prediction of the NANF SNR (0.3 dB apart)
        assert c5.copy.mean_abs_db == pytest.approx(0.3) and c5.copy.passed
        assert c5.rop_outside == (0, 2) and c5.ssmf_above_cap == 2  # the points of D1
        assert rate in (80, 100, 112)


def test_a_c5_value_that_misses_its_tolerance_fails_only_that_link(frozen, tmp_path):
    def ssmf_low(task):
        p = stub_point(task)
        if (task.link_key or "").startswith("C5-SSMF"):
            return nh.HoldoutPoint(False, "", p.ber, p.snr_db - 3.5, p.n_bits)  # 3.7 dB error
        return p

    result = run(frozen, tmp_path, runner=ssmf_low)
    for r in result.rates.values():
        assert not r.c5.ssmf.passed and r.c5.nanf.passed and r.c5.b2b.passed and not r.c5.passed
    assert result.verdict.startswith("failed: ") and "C5@80" in result.verdict
    assert "C5@112" in result.verdict and "consistent" not in result.verdict


def test_each_c5_link_has_its_own_tolerance(frozen, tmp_path):
    """An error of 2.6 dB passes for SSMF (3.0 dB) and fails for NANF and B2B (2.0 dB)."""

    def off_by_2_6(kind):
        def runner(task):
            p = stub_point(task)
            if (task.link_key or "").startswith(f"C5-{kind}"):
                return nh.HoldoutPoint(False, "", p.ber, p.snr_db - 2.4, p.n_bits)
            return p

        return runner

    ssmf = run(frozen, tmp_path, runner=off_by_2_6("SSMF")).rates[80].c5
    assert ssmf.ssmf.passed and ssmf.ssmf.link == "ssmf" and ssmf.nanf.passed and ssmf.b2b.passed
    assert ssmf.ssmf.mean_abs_db == pytest.approx(2.6)
    b2b = run(frozen, tmp_path, runner=off_by_2_6("B2B")).rates[80].c5
    assert not b2b.b2b.passed and b2b.b2b.link == "b2b" and b2b.ssmf.passed
    nanf = run(frozen, tmp_path, runner=off_by_2_6("NANF")).rates[80].c5
    assert not nanf.nanf.passed and nanf.nanf.link == "nanf" and nanf.ssmf.passed


@pytest.mark.parametrize("kind", ["NANF", "SSMF", "B2B"])
def test_a_lost_c5_point_fails_the_link_is_listed_and_never_reads_consistent(
    frozen, tmp_path, kind
):
    result = run(frozen, tmp_path, runner=lose_c5(kind, 1500.0))
    for r in result.rates.values():
        link = {"NANF": r.c5.nanf, "SSMF": r.c5.ssmf, "B2B": r.c5.b2b}[kind]
        assert not link.passed and link.n_invalid == 1 and not r.c5.passed  # H3: no partial credit
        assert math.isnan(link.mean_abs_db)  # nothing is averaged over the 16 that remain
        assert len(r.c5.lost) == 1 and f"LOST LOCK C5 {kind} at 1500 nm" in r.c5.lost[0]
        assert r.c5.lost[0] in r.lost
    assert len(result.lost) == 3 and result.verdict.startswith("failed: ")
    assert "C5@80" in result.verdict and "consistent" not in result.verdict
    text = nh.build_report(result)
    assert f"LOST LOCK C5 {kind} at 1500 nm" in text and "consistent with this one" not in text
    if kind in ("NANF", "B2B"):
        assert all(r.c5.d is None and not r.c5.discriminating for r in result.rates.values())


def test_the_verdict_is_the_one_of_overall_verdict_with_the_real_c5_status(
    frozen, tmp_path, monkeypatch
):
    seen = {}

    def spy(scores):
        seen.update(scores)
        return sc.Verdict("the text of the scoring module", (), ())

    monkeypatch.setattr(nh, "overall_verdict", spy)
    result = run(frozen, tmp_path, runner=lose_c5("SSMF", 1500.0))
    assert result.verdict == "the text of the scoring module"
    assert set(seen) == {80, 100, 112}
    for scores in seen.values():
        assert isinstance(scores, sc.RateScores) and scores.c5_passed is False
        assert scores.c1_passed and scores.c2_passed and scores.c3_passed
        assert scores.b2b_poor is False and not scores.c1_discriminating
    seen.clear()
    run(frozen, tmp_path)
    assert all(s.c5_passed is True and s.b2b_poor is False for s in seen.values())
    seen.clear()

    def b2b_off_at_100(task):
        p = stub_point(task)
        if task.label.startswith("B2B") and task.rate == 100:
            return nh.HoldoutPoint(False, "", p.ber, p.snr_db - 2.5, p.n_bits)
        return p

    run(frozen, tmp_path, runner=b2b_off_at_100)
    assert [seen[r].b2b_poor for r in (80, 100, 112)] == [False, True, False]


def test_a_consistent_run_needs_every_rate_discriminating_and_no_poor_gate(frozen, tmp_path):
    """The model is 2.4 dB better than the no-fibre run, and the published NANF curves say so."""
    wb = holdout_workbook(nanf_shift=2.4)
    result = run(frozen, tmp_path, wb=wb, runner=make_stub(2.4))
    for r in result.rates.values():
        assert r.c1.passed and r.c2.passed and r.c3.passed and r.c5.passed and r.gate.passed
        assert r.c1_discriminating and r.c2_discriminating and r.c5.discriminating
    assert result.verdict == "consistent with this one experiment"
    text = nh.build_report(result)
    assert "NOT DISCRIMINATING" not in text and "consistent with one published experiment" in text


@pytest.mark.parametrize(
    ("snr_shift", "ber_shift", "c1_disc", "c2_disc"),
    [(-0.3, 2.4, True, False), (2.4, -0.3, False, True)],
)
def test_one_discriminating_criterion_is_not_enough_for_consistent(
    frozen, tmp_path, snr_shift, ber_shift, c1_disc, c2_disc
):
    """A2, B3.3: C1 and C2 must both discriminate. The Fig.4 NANF curves are made so that d of C1
    and d of C2 differ: the SNR and the BER of the model are shifted by different amounts."""
    wb = holdout_workbook(nanf_shift=2.4)
    for rate in (80, 100, 112):
        for kind, shift in (("SNR", snr_shift), ("BER", ber_shift)):
            key = f"Fig.4/{kind}@{rate}/NANF-{rate}-{kind}"
            snr = [base_snr(rate, r) + shift + 0.2 for r in wb[key].x]
            wb = with_series(wb, key, y=tuple(snr if kind == "SNR" else map(ber_of, snr)))
    base = make_stub(2.4)

    def runner(task):
        if task.link_key != nh.NANF_LINK:
            return base(task)
        snr = base_snr(task.rate, task.rop_dbm)
        return nh.HoldoutPoint(False, "", ber_of(snr + ber_shift), snr + snr_shift, N_BITS)

    result = run(frozen, tmp_path, wb=wb, runner=runner)
    for r in result.rates.values():
        assert r.c1.passed and r.c2.passed and r.c3.passed and r.c5.passed and r.gate.passed
        assert (r.c1_discriminating, r.c2_discriminating) == (c1_disc, c2_disc)
    assert result.verdict == (
        "primary criteria pass; NANF criteria NOT DISCRIMINATING (rates 80, 100, 112 Gb/s)"
    )


def test_a_gate_poor_rate_with_d_above_tolerance_does_not_print_a_pass(frozen, tmp_path):
    """B3.2: at rate 100 the model B2B is 2.5 dB off. d is above every tolerance there, and the
    NANF criteria still cannot read discriminating or consistent; the other rates are unaffected."""
    runner_good = make_stub(2.4)

    def b2b_off_at_100(task):
        p = runner_good(task)
        if task.label.startswith("B2B") and task.rate == 100:
            return nh.HoldoutPoint(False, "", p.ber, p.snr_db - 2.5, p.n_bits)
        return p

    result = run(frozen, tmp_path, wb=holdout_workbook(nanf_shift=2.4), runner=b2b_off_at_100)
    poor = result.rates[100]
    assert poor.gate.label == "B2B CALIBRATION POOR" and not poor.gate.passed
    assert poor.d_snr > 1.5 and poor.d_c1 > 1.0 and poor.c5.d > 2.0  # d would discriminate
    assert poor.c1.passed and poor.c2.passed and poor.c5.passed  # ... and the criteria pass
    assert not (poor.c1_discriminating or poor.c2_discriminating or poor.c5.discriminating)
    assert result.rates[80].c1_discriminating and result.rates[112].c5.discriminating
    assert result.verdict == (
        "primary criteria pass; NANF criteria NOT DISCRIMINATING (rates 100 Gb/s)"
    )  # the weak rate is named
    rows = [x for x in nh.build_report(result).splitlines() if x.startswith("| ")]
    at = lambda rate: " ".join(x for x in rows if x.startswith(f"| {rate} Gb/s"))  # noqa: E731
    assert at(100).count("PASS, NOT DISCRIMINATING") == 3  # C1 and C2, then C5 NANF
    assert "PASS, NOT DISCRIMINATING" not in at(80) and "PASS, NOT DISCRIMINATING" not in at(112)


def test_not_discriminating_names_its_rates_and_a_fail_stays_a_fail(frozen, tmp_path):
    result = run(frozen, tmp_path)  # d is 0.3 dB at every rate
    assert "(rates 80, 100, 112 Gb/s)" in result.verdict
    text = nh.build_report(result)
    assert text.count("PASS, NOT DISCRIMINATING") == 9 and "NOT DISCRIMINATING" in text
    failed = run(frozen, tmp_path, runner=lose_c5("NANF", 1500.0))
    assert "NOT DISCRIMINATING" not in failed.verdict  # a failure is reported as a failure


# --- B3: the B2B copy (D3.1) --------------------------------------------------------------------


def test_the_b2b_copy_c2_is_scored_by_score_c2_with_its_max_check(frozen, tmp_path):
    result = run(frozen, tmp_path)
    wb = holdout_workbook()
    for rate, r in result.rates.items():
        pub_b2b, pub_ber = (
            wb[f"Fig.4/SNR@{rate}/B2B-{rate}-SNR"],
            wb[f"Fig.4/BER@{rate}/B2B-{rate}-BER"],
        )
        pub_nanf = wb[f"Fig.4/SNR@{rate}/NANF-{rate}-SNR"]
        copy = sc.b2b_copy(pub_b2b.x, pub_b2b.y, pub_ber.y, pub_nanf.x)
        expected = sc.score_c2(pub_nanf.x, copy.snr_db, pub_nanf.y)
        assert r.copy_c2 == expected and r.copy_c2.passed and r.copy_unbracketed == ()
        assert r.copy_c2.max_abs_db == pytest.approx(0.3) and r.copy_c2.n_points == 6


def test_the_b2b_copy_fails_on_one_point_beyond_3_db_though_its_mean_passes(frozen, tmp_path):
    wb = holdout_workbook()
    key = "Fig.4/SNR@80/B2B-80-SNR"
    y = list(wb[key].y)
    y[2] += 3.5  # the published B2B at -10 dBm: a 3.6 dB error of the copy there
    result = run(frozen, tmp_path, wb=with_series(wb, key, y=tuple(y)))
    copy = result.rates[80].copy_c2
    assert copy.mean_abs_db <= 1.5 and copy.max_abs_db > 3.0 and not copy.passed
    assert result.rates[100].copy_c2.passed
    text = nh.build_report(result)
    assert f"C2 mean / max {copy.mean_abs_db:.3g} / {copy.max_abs_db:.3g} dB, FAIL" in text


def test_a_nanf_rop_with_no_b2b_bracket_is_listed_and_not_scored(frozen, tmp_path):
    wb = holdout_workbook()
    for kind in ("BER", "SNR"):
        key = f"Fig.4/{kind}@80/B2B-80-{kind}"
        s = wb[key]
        wb = with_series(  # the B2B axis starts at -10 dBm: the NANF ROPs -12 and -11 have no bracket
            wb, key, x=s.x[2:], y=s.y[2:], flags=s.flags[2:]
        )
    result = run(frozen, tmp_path, wb=wb)
    copy = result.rates[80]
    assert copy.copy_unbracketed == (-12.0, -11.0) and copy.copy_c2.n_points == 4
    assert "no B2B bracket at -12, -11 dBm" in nh.build_report(result)
    assert result.rates[100].copy_unbracketed == ()


def test_a_copy_with_no_bracketed_rop_at_all_does_not_pass(frozen, tmp_path):
    wb = holdout_workbook()
    for kind in ("BER", "SNR"):
        key = f"Fig.4/{kind}@80/B2B-80-{kind}"
        s = wb[key]
        wb = with_series(wb, key, x=s.x[8:], y=s.y[8:], flags=s.flags[8:])  # -4 to -2 dBm only
    try:
        result = run(frozen, tmp_path, wb=wb)
    except ValueError:  # the model's own B2B gate needs points at most -5 dBm: also a refusal
        return
    copy = result.rates[80].copy_c2
    assert not copy.passed and copy.n_points == 0 and "no B2B bracket" in copy.reason


# --- B3: the axes ------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["Fig.6/SNR@100/NANF-100-SNR", "Fig.5/link/ROP@SSMF"])
def test_a_c5_series_off_the_19_point_axis_is_refused(frozen, tmp_path, key):
    wb = holdout_workbook()
    shifted = with_series(wb, key, x=tuple(w + 5.0 for w in wb[key].x))
    with pytest.raises(ValueError, match="19-point axis"):
        run(frozen, tmp_path, wb=shifted)
    short = wb[key]
    cut = with_series(wb, key, x=short.x[:18], y=short.y[:18], flags=short.flags[:18])
    with pytest.raises(ValueError, match="19-point axis"):
        run(frozen, tmp_path, wb=cut)


def test_1630_and_1640_nm_are_never_simulated_and_the_report_says_so(frozen, tmp_path):
    seen = []

    def spy(task):
        seen.append(task)
        return stub_point(task)

    result = run(frozen, tmp_path, runner=spy)
    c5 = [t for t in seen if t.label.startswith("C5-")]
    assert {t.point_index for t in c5} == set(range(17)) and len(c5) == 3 * 3 * 17
    text = nh.build_report(result)
    assert "1630 and 1640 nm: not simulated (plan B2)" in text
    assert "C5, the wavelength sweep" in text and "NOT RUN" not in text
    assert "operating points outside the calibrated ROP range of 17, NANF 0 and SSMF 2" in text
    assert "SSMF points above -5 dBm (plan D1): 2" in text
    assert WAVELENGTHS[17:] == (1630.0, 1640.0)
    assert ROP_NANF_COLUMN[0] < ROP_SSMF_COLUMN[3] and FIG1_PARAMS["NANF"][0] == 2.04


# --- B3: the real runner takes the recipe's link ------------------------------------------------


def test_the_real_runner_passes_the_recipe_link_of_the_task(frozen, monkeypatch):
    seen = {}

    def fake_simulate(params, rate, rop, *, link=None, point_index=0, **kw):
        record = nanf_freeze.load_freeze_record()
        seen.update(link=link, index=point_index)
        return PointResult(
            reading=BerReading.from_counts(500, 1_294_016), snr_db=12.0, ser=0.0,
            n_scored_symbols=647_008, laser_power_w=1e-3, mean_received_dbm=rop, seconds={},
            dfe=None, frozen_record_hash=record.freeze_hash, rate_gbps=rate, rop_dbm=float(rop),
            point_index=point_index, link=nc.LinkSpec() if link is None else link,
        )  # fmt: skip  # type: ignore[arg-type]

    monkeypatch.setattr(nc, "simulate_point", fake_simulate)
    task = nh.HoldoutTask("C5-SSMF/80G/1500", "C5-SSMF-1500", 80, -9.0, 4)
    with pytest.raises(KeyError):  # the recipe has not run
        nh.simulate_holdout_point(task)
    links = nc.declare_c5_links(holdout_workbook())
    point = nh.simulate_holdout_point(task)
    assert seen["link"] == links["C5-SSMF-1500"] and seen["index"] == 4 and not point.lost


# --- B3: the script prints the marker rule ----------------------------------------------------------


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "nanf_holdout.py"
    spec = importlib.util.spec_from_file_location("nanf_holdout_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_script(monkeypatch, tmp_path, outcome):
    script = load_script()

    def fake_run(workbook, freeze_hash):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(nh, "run_holdout", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "nanf_holdout.py",
            "--workbook",
            "w.xlsx",
            "--freeze-hash",
            "x",
            "--report",
            str(tmp_path / "r.md"),
        ],
    )
    return script.main()


def test_the_script_prints_the_marker_commit_rule_when_a_run_ends(
    frozen, tmp_path, monkeypatch, capsys
):
    result = run(frozen, tmp_path)
    assert call_script(monkeypatch, tmp_path, result) == 0
    out = capsys.readouterr().out
    assert result.verdict in out and nh.MARKER_RULE in out
    assert f"git add {nh.MARKER_REL}" in out and (tmp_path / "r.md").read_text().startswith(
        "# NANF"
    )
    assert (
        "committed" not in nh.MARKER_RULE.split(".")[0] or "Commit the marker and the report" in out
    )


def test_the_rule_is_printed_after_an_error_that_follows_the_marker_and_not_after_a_refusal(
    frozen, tmp_path, monkeypatch, capsys
):
    with pytest.raises(RuntimeError, match="late"):
        call_script(monkeypatch, tmp_path, RuntimeError("late"))
    assert nh.MARKER_RULE in capsys.readouterr().out  # the marker may exist: the rule holds
    for refusal in (
        nh.HoldoutAlreadyReadError("again"),
        nanf_freeze.HoldoutLockedError("locked"),
    ):
        assert call_script(monkeypatch, tmp_path, refusal) == 1
        out = capsys.readouterr().out
        assert "REFUSED" in out and nh.MARKER_RULE not in out  # nothing was written
