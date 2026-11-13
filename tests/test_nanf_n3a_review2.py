"""Gate N3 part a, plan Amendment 8: the second review's findings. Synthetic data only; no workbook,
no fit, nothing frozen outside a throw-away repository."""

import ast
import dataclasses
import math
import subprocess

import numpy as np
import pytest

from nanf_freeze_support import (
    ARTIFACT_REL,
    GOOD_FIT,
    git,
    good_checks,
    make_repo,
    patch_module_paths,
    write_record,
)
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_freeze as nf
from opticps.measurement import nanf_import
from opticps.measurement import nanf_scoring as sc
from opticps.measurement.nanf_benchmark import numerical_profile
from opticps.receiver.dfe import DfeResult, RlsDfeConfig

SMALL = nc.ChainConfig(n_symbols=14_000, training_symbols=2_000)
MID = nc.TxRxParameters()
NAN = math.nan


def locked(**kw):
    return pytest.raises(nf.HoldoutLockedError, **kw)


def stub_equalizer(monkeypatch, caps=0):
    """A cheap stand-in for the RLS loop (the analogue chain still runs in full)."""
    real = nc.rls_equalize

    def fake(samples, reference, cfg=None):
        n = samples.size // 2
        zeros = np.zeros(n)
        return DfeResult(
            zeros, zeros, np.zeros(n, dtype=np.int64), np.zeros(24), np.eye(24), 1.0, 0.0, caps
        )

    monkeypatch.setattr(nc, "rls_equalize", fake)
    return real


# --- finding 2: no route from an unscorable result to a score -------------------------------


def test_an_unscorable_result_cannot_become_an_outcome_or_an_array():
    r = nc.simulate_point(MID, 100, -6.0, config=SMALL)  # the review's repro: config overridden
    assert not r.scorable
    with pytest.raises(nc.NotScorableError, match="chain configuration overridden"):
        nc.PointOutcome("x", -6.0, r)  # the reasons are kept in the error text (Amendment 9)
    # a forged outcome (the guard bypassed) is still refused by curve_arrays
    forged = object.__new__(nc.PointOutcome)
    for name, value in (("label", "x"), ("rop_dbm", -6.0), ("result", r), ("reason", "")):
        object.__setattr__(forged, name, value)
    with pytest.raises(nc.NotScorableError):
        nc.curve_arrays([forged], calibration=True)
    # and so no score_* can be fed from it: the arrays never exist
    for diagnostic in (
        nc.simulate_point(MID, 100, -6.0, config=SMALL, noise=False),
        nc.simulate_point(MID, 100, -6.0, config=SMALL, diagnostic=True),
    ):
        with pytest.raises(nc.NotScorableError):
            nc.PointOutcome("y", -6.0, diagnostic)


def scorable_result(rate=100, rop=-6.0, index=0, link=None, vector=MID, caps_free=True):
    r = nc.simulate_point(vector, rate, rop, config=SMALL, point_index=index, link=link)
    return dataclasses.replace(r, unscorable_reasons=())  # stands in for a pinned full-size run


def test_the_calibration_flag_is_checked_not_trusted(tmp_path, monkeypatch):
    """Amendment 9 H-A: the review's repros. A typed flag cannot make a result scorable."""
    nanf = nc.LinkSpec(numerical_profile("NANF", length_km=4.76, d_ps_per_nm_km=2.04))
    declared = frozenset({(100, -6.0, 0), (112, -7.0, 77)})  # the NANF point is "declared" too
    monkeypatch.setattr(nc, "DECLARED_CALIBRATION_POINTS", declared)
    b2b = nc.PointOutcome("b2b", -6.0, scorable_result())
    # a declared back-to-back point, no record anywhere: calibration is allowed ...
    assert nc.curve_arrays([b2b], calibration=True).valid.tolist() == [True]
    # ... and scoring is not (no verified freeze record to score under)
    with pytest.raises(nc.NotScorableError, match="no verified freeze record"):
        nc.curve_arrays([b2b])
    # (a) a retuned vector on a NANF link at a free index, then a record appears: refused both ways
    retuned = scorable_result(
        rate=112, rop=-7.0, index=77, link=nanf, vector=nc.TxRxParameters(tx_bandwidth_ghz=55.0)
    )
    bad = nc.PointOutcome("x", -7.0, retuned)
    with pytest.raises(nc.NotScorableError, match="back-to-back"):
        nc.curve_arrays([bad], calibration=True)  # the NANF link is not a calibration point
    repo = make_repo(tmp_path)
    patch_module_paths(monkeypatch, repo)
    assert nf.freeze_record_present()
    with pytest.raises(nc.NotScorableError, match="once a freeze record exists"):
        nc.curve_arrays([b2b], calibration=True)  # even a clean B2B point: calibration is over
    with pytest.raises(nc.NotScorableError, match="verified freeze record"):
        nc.curve_arrays([b2b])  # run without the record
    # (b) the record is deleted: the retuned NANF result is neither a calibration nor a scoring input
    repo.record_path.unlink()
    assert not nf.freeze_record_present()
    with pytest.raises(nc.NotScorableError):
        nc.curve_arrays([bad], calibration=True)
    with pytest.raises(nc.NotScorableError):
        nc.curve_arrays([bad])
    # a result at an undeclared point or index cannot be a calibration point either
    other = nc.PointOutcome("o", -6.0, scorable_result(index=3))
    with pytest.raises(nc.NotScorableError, match="not a declared calibration point"):
        nc.curve_arrays([other], calibration=True)
    # an outcome whose ROP differs from its result's is refused
    skewed = nc.PointOutcome("s", -5.0, scorable_result())
    with pytest.raises(nc.NotScorableError, match="another ROP"):
        nc.curve_arrays([skewed], calibration=True)


def test_a_result_must_carry_the_hash_of_the_record_that_verifies_now(tmp_path, monkeypatch):
    """Amendment 9 H-A (c): 'verified' is true now, not at run time; a typed hash is refused."""
    base = scorable_result()  # run before the freeze exists (the small chain is refused after it)
    repo = make_repo(tmp_path)
    patch_module_paths(monkeypatch, repo)
    ok = dataclasses.replace(base, frozen_record_hash=repo.hash)
    assert nc.curve_arrays([nc.PointOutcome("p", -6.0, ok)]).valid.tolist() == [True]
    for wrong in ("a" * 64, None, "0" * 64):
        fake = dataclasses.replace(ok, frozen_record_hash=wrong)
        with pytest.raises(nc.NotScorableError, match="verified freeze record"):
            nc.curve_arrays([nc.PointOutcome("p", -6.0, fake)])
    # the plan changes after the run: the record no longer verifies, so the result is refused
    repo.plan.write_text(repo.plan.read_text() + "\nlate edit\n")
    with pytest.raises(nc.NotScorableError, match="no verified freeze record"):
        nc.curve_arrays([nc.PointOutcome("p", -6.0, ok)])
    # the record is deleted after the run: refused
    repo.plan.write_text(repo.plan.read_text().replace("\nlate edit\n", ""))
    assert nc.curve_arrays([nc.PointOutcome("p", -6.0, ok)]).valid.tolist() == [True]
    repo.record_path.unlink()
    with pytest.raises(nc.NotScorableError, match="no verified freeze record"):
        nc.curve_arrays([nc.PointOutcome("p", -6.0, ok)])
    with pytest.raises(nc.NotScorableError):
        nc.require_scorable([ok], frozen_hash="b" * 64)


# --- finding 3: the fibre and the noise index are not free after a freeze --------------------


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    patch_module_paths(monkeypatch, repo)
    return repo


def test_after_a_freeze_an_undeclared_fibre_or_noise_index_is_not_scorable(frozen, monkeypatch):
    stub_equalizer(monkeypatch)
    nanf20 = nc.LinkSpec(numerical_profile("NANF", length_km=4.76, d_ps_per_nm_km=20.0))
    res = nc.simulate_point(None, 112, -7.0, link=nanf20)  # the review's repro: NANF with D = 20
    assert not res.scorable and any(
        "link not in the declared table" in w for w in res.unscorable_reasons
    )
    wavelength = nc.simulate_point(None, 112, -7.0, link=nc.LinkSpec(None, 1300.0))
    assert not wavelength.scorable
    index = nc.simulate_point(None, 112, -7.0, point_index=123)
    assert not index.scorable and any("point_index" in w for w in index.unscorable_reasons)
    with pytest.raises(nc.NotScorableError):
        nc.run_point("p", None, 112, -7.0, link=nanf20)
    # a declared link and a declared index are scorable, and carry the record they used
    monkeypatch.setattr(nc, "DECLARED_LINKS", {"NANF-D2.04": nanf20})
    monkeypatch.setattr(nc, "DECLARED_POINT_INDICES", frozenset({0, 123}))
    ok = nc.simulate_point(None, 112, -7.0, link=nanf20, point_index=123)
    assert ok.scorable and ok.frozen_record_hash == frozen.hash
    still = nc.simulate_point(None, 112, -7.0, link=nc.LinkSpec(None, 1300.0), point_index=0)
    assert not still.scorable
    # B2B is the default link and needs only a declared index
    assert nc.simulate_point(None, 112, -7.0, point_index=0).scorable


def test_before_a_freeze_the_link_and_the_index_stay_free_for_calibration(monkeypatch):
    stub_equalizer(monkeypatch)
    res = nc.simulate_point(MID, 112, -7.0, point_index=123)
    assert res.scorable and res.frozen_record_hash is None


# --- finding 4: a fake fit, the checks that ran, grafts, replace refs ------------------------


def build_with(tmp_path, name, **kw):
    return make_repo(tmp_path, name=name, **kw)


@pytest.mark.parametrize(
    "fit",
    [
        {**GOOD_FIT, "converged": False},
        {**GOOD_FIT, "converged": 1},
        {**GOOD_FIT, "n_evaluations": 1},
        {**GOOD_FIT, "n_evaluations": nf.MIN_EVALUATIONS - 1},
        {**GOOD_FIT, "n_calibration_points": 1},
        {**GOOD_FIT, "n_calibration_points": nf.MIN_CALIBRATION_POINTS - 1},
        {**GOOD_FIT, "n_calibration_points": nf.MAX_CALIBRATION_POINTS + 1},
        {**GOOD_FIT, "cost": 0},
        {**GOOD_FIT, "cost": 0.0},
    ],
)
def test_a_fake_fit_is_refused(tmp_path, fit):
    with locked(match="evidence of a converged calibration"):
        build_with(tmp_path, "fake", fit_result=fit)


def test_the_fit_boundaries_are_inclusive(tmp_path):
    lo = {**GOOD_FIT, "n_evaluations": nf.MIN_EVALUATIONS, "n_calibration_points": 9, "cost": 1e-9}
    hi = {**GOOD_FIT, "n_calibration_points": 33}
    assert build_with(tmp_path, "lo", fit_result=lo).record
    assert build_with(tmp_path, "hi", fit_result=hi).record


def test_the_artefact_must_record_that_the_checks_ran(tmp_path):
    good = good_checks(1)
    bad_cases = {
        "missing": None,
        "not checked": {**good, "chosen_fit_checked": False},
        "truthy": {**good, "chosen_fit_checked": 1},
        "lost point": {**good, "n_lost_points_in_grid": 1},
        "extra key": {**good, "extra": 1},
        "five eigenvalues": {**good, "identifiability_eigenvalues": [1.0] * 5},
        "descending": {**good, "identifiability_eigenvalues": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]},
        "negative": {**good, "identifiability_eigenvalues": [-1.0, 1.0, 2.0, 3.0, 4.0, 5.0]},
        "nan": {**good, "identifiability_eigenvalues": [NAN, 1.0, 2.0, 3.0, 4.0, 5.0]},
    }
    for label, checks in bad_cases.items():
        if checks is None:
            # a hand-written artefact without the key at all
            with locked():
                repo = make_repo(tmp_path, name="m")
                raw = (repo.root / ARTIFACT_REL).read_text()
                import json

                body = json.loads(raw)
                del body["checks"]
                (repo.root / ARTIFACT_REL).write_bytes(nf.canonical_json(body))
                git(repo.root, "add", "-A")
                git(repo.root, "commit", "-q", "-m", "no checks")
                nf.build_freeze_record(ARTIFACT_REL, root=repo.root, plan_path=repo.plan)
            continue
        with locked(match="checks|check_chosen_fit|eigenvalues"):
            build_with(tmp_path, label.replace(" ", "_"), checks=checks)


def test_eigenvalues_must_ascend_even_when_the_flag_count_would_match(tmp_path):
    # descending values: the largest is read as 1.0, no value is low, zero flags would match
    desc = {**good_checks(0), "identifiability_eigenvalues": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]}
    with locked(match="six ascending"):
        build_with(tmp_path, "desc", flags=(), checks=desc)


def test_flags_must_match_the_b4_eigenvalues(tmp_path):
    # no flag although one eigenvalue is far below 1e-3 of the largest
    with locked(match="do not match the B4 eigenvalues"):
        build_with(tmp_path, "unflagged", flags=(), checks=good_checks(1))
    # one flag although no eigenvalue is low
    with locked(match="do not match the B4 eigenvalues"):
        build_with(tmp_path, "overflagged", checks=good_checks(0))
    # the singular case flags everything
    all_names = tuple(nf.B4_NAMES)
    prior = nc.TxRxParameters()
    assert build_with(
        tmp_path, "singular", parameters=prior, flags=all_names, checks=good_checks(6)
    )
    # the boundary: an eigenvalue exactly at 1e-3 of the largest is not low
    edge = {**good_checks(0), "identifiability_eigenvalues": [1e-3, 1.0, 1.0, 1.0, 1.0, 1.0]}
    assert build_with(tmp_path, "edge", flags=(), checks=edge).record
    below = {**good_checks(0), "identifiability_eigenvalues": [0.999e-3, 1.0, 1.0, 1.0, 1.0, 1.0]}
    with locked(match="do not match"):
        build_with(tmp_path, "below", flags=(), checks=below)


def test_a_graft_makes_the_repository_untrustworthy(tmp_path):
    repo = make_repo(tmp_path)
    main = git(repo.root, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo.root, "checkout", "-q", "--orphan", "side")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "same files, unrelated history")
    side = git(repo.root, "rev-parse", "HEAD")
    git(repo.root, "checkout", "-q", "-f", main)
    forged = dict(repo.record, calibration={**repo.record["calibration"], "commit": side})
    forged["freeze_hash"] = nf.compute_freeze_hash(
        forged["plan_sha256"], forged["code_identity"], forged["parameters"],
        forged["unidentifiable"], forged["calibration"], forged["calibration_partition_sha256"],
    )  # fmt: skip
    write_record(repo, forged)
    kw = dict(record_path=repo.record_path, plan_path=repo.plan, root=repo.root)
    with locked(match="not an ancestor"):
        nf.require_freeze(forged["freeze_hash"], **kw)
    head = git(repo.root, "rev-parse", "HEAD")
    (repo.root / ".git/info").mkdir(exist_ok=True)
    (repo.root / ".git/info/grafts").write_text(f"{head} {side}\n")  # now side is an ancestor
    with locked(match="grafts"):
        nf.require_freeze(forged["freeze_hash"], **kw)


def test_replace_refs_are_not_honoured(tmp_path):
    repo = make_repo(tmp_path)
    main = git(repo.root, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo.root, "checkout", "-q", "--orphan", "side")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "same files, unrelated history")
    side = git(repo.root, "rev-parse", "HEAD")
    git(repo.root, "checkout", "-q", "-f", main)
    head = git(repo.root, "rev-parse", "HEAD")
    git(
        repo.root, "replace", "--graft", head, side
    )  # with replace refs honoured, side is an ancestor
    assert (
        subprocess.run(
            ["git", "-C", str(repo.root), "merge-base", "--is-ancestor", side, "HEAD"]
        ).returncode
        == 0
    )
    forged = dict(repo.record, calibration={**repo.record["calibration"], "commit": side})
    forged["freeze_hash"] = nf.compute_freeze_hash(
        forged["plan_sha256"], forged["code_identity"], forged["parameters"],
        forged["unidentifiable"], forged["calibration"], forged["calibration_partition_sha256"],
    )  # fmt: skip
    write_record(repo, forged)
    with locked(match="not an ancestor"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, plan_path=repo.plan, root=repo.root
        )


def test_the_fibre_profiles_are_part_of_the_code_identity(tmp_path):
    repo = make_repo(tmp_path)
    names = nf.identity_files(repo.root)
    yaml = [n for n in names if n.startswith("configs/fibers/")]
    assert len(yaml) >= 4 and all(n.endswith(".yaml") for n in yaml)
    before = nf.code_identity(repo.root)
    target = repo.root / yaml[0]
    target.write_text(target.read_text() + "\n# edited\n")
    assert nf.code_identity(repo.root) != before


# --- finding 5: H3 for points above -5 dBm; the gate gets a ROP axis ------------------------


def test_c3_ignores_a_lost_point_above_the_cap_and_one_outside_the_penalty_set():
    n_rop = [-9.0, -8.0, -4.0]
    s_rop = [-9.0, -8.0, -4.0]
    n_snr, s_snr = [20.0, 21.0, NAN], [15.0, 16.0, NAN]
    ber = [0.1, 0.1, NAN]
    args = (80, n_rop, n_snr, s_rop, s_snr, ber)
    ok = sc.score_c3(*args, nanf_valid=[True, True, False], ssmf_valid=[True, True, False])
    assert ok.passed and ok.n_points == 2  # lost points at -4 dBm do not fail and do not raise
    # a lost NANF scored point outside the SSMF ROP range is not needed for the penalty
    wide = sc.score_c3(
        80, [-11.0, -9.0, -8.0], [NAN, 20.0, 21.0], [-9.0, -8.0], [15.0, 16.0], [0.1, 0.1],
        nanf_valid=[False, True, True],
    )  # fmt: skip
    assert wide.passed and wide.n_points == 2
    # a lost NANF point inside the set, or any lost scored SSMF point, still fails
    for kw in ({"nanf_valid": [True, False, False]}, {"ssmf_valid": [True, False, False]}):
        bad = sc.score_c3(*args, **kw)
        assert bad.passed is False and "lost-lock" in bad.reason


def test_the_b2b_gate_takes_a_rop_axis_and_ignores_points_above_the_cap():
    point = sc.Crossing("point", -9.0, -9.0)
    snr = [10.0, 11.0, NAN]
    gate = sc.b2b_gate(
        snr, [10.0, 11.0, 50.0], point, point, rop=[-9.0, -8.0, -4.0],
        simulated_valid=[True, True, False],
    )  # fmt: skip
    assert gate.passed  # the lost point at -4 dBm is not scored
    lost_scored = sc.b2b_gate(
        snr, [10.0, 11.0, 50.0], point, point, rop=[-9.0, -8.0, -7.0],
        simulated_valid=[True, True, False],
    )  # fmt: skip
    assert lost_scored.passed is False and lost_scored.label == "B2B CALIBRATION POOR"
    # the ROP axis is required: without it the gate cannot say which points are scored (H-D)
    with pytest.raises(TypeError):
        sc.b2b_gate([10.0], [10.0], point, point)
    with pytest.raises(TypeError):
        sc.b2b_gate([10.0], [10.0], point, point, simulated_valid=[False])
    # the review's repro: 8 scored points with 1.4 dB error, 5 unscored with 0 dB
    rop13 = [-14.0 + k for k in range(13)]  # -14 ... -2: eight at most -5 dBm
    sim = [10.0 + 1.4 if r <= -5.0 else 10.0 for r in rop13]
    pub = [10.0] * 13
    assert sc.b2b_gate(sim, pub, point, point, rop=rop13).passed is False
    assert sc.b2b_gate(sim[:8] + pub[8:], pub, point, point, rop=rop13).passed is False


def test_c4_and_c5_ignore_a_lost_point_that_is_not_scored():
    c4 = sc.score_c4([-9.0, -4.0], [1e-3, 1e-3], [1e-3, NAN], 10**6, simulated_valid=[True, False])
    assert c4.passed and c4.n_invalid == 0  # -4 dBm is above the cap
    wl = [1460.0 + 10.0 * k for k in range(17)] + [1630.0, 1640.0]
    snr = [20.0] * 17 + [NAN, NAN]
    mask = [True] * 17 + [False, False]
    c5 = sc.score_c5("nanf", wl, snr, [20.0] * 19, simulated_valid=mask)
    assert c5.passed and c5.n_invalid == 0  # 1630 and 1640 are reported apart, never scored


def test_a_published_curve_has_no_lost_points():
    with pytest.raises(ValueError, match="published series has no lost-lock"):
        sc.c1_crossing([-12.0, -11.0], [1e-1, 1e-3], published=True, valid=[True, True])


# --- finding 6, 7: refused is not lost; the guards of run_point -----------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"config": SMALL},
        {"config": nc.ChainConfig(dac_bits=6)},
        {"equalizer": RlsDfeConfig(p_trace_cap=1.0)},
        {"equalizer": RlsDfeConfig(p_trace_cap=1e4)},
        {"equalizer": RlsDfeConfig(p_trace_cap=1e12)},
        {"equalizer": RlsDfeConfig(forgetting=0.5)},
        {"equalizer": RlsDfeConfig(forgetting=0.5, p_trace_cap=1.0)},
        {"equalizer": RlsDfeConfig(ff_taps=15)},
        {"equalizer": RlsDfeConfig(fb_taps=3)},
        {"equalizer": RlsDfeConfig(delta=1.0)},
        {"equalizer": RlsDfeConfig(decision_directed=False)},
        {"noise": False},
        {"diagnostic": True},
        {"unknown_switch": 1},
    ],
)
def test_anything_that_makes_a_run_non_pinned_is_refused_before_it_runs(monkeypatch, kwargs):
    """Amendment 9 H-E: even when the cap acts (stubbed), an illegal run is refused, never lost."""
    stub_equalizer(monkeypatch, caps=3)
    with pytest.raises(nc.NotScorableError, match="pinned chain"):
        nc.run_point("p", MID, 80, -5.0, **kwargs)
    assert nc.nonpinned_reasons(kwargs)


def test_the_pinned_arguments_are_not_refused_and_a_real_loss_is_still_lost(monkeypatch):
    stub_equalizer(monkeypatch, caps=3)
    assert nc.nonpinned_reasons({}) == []
    assert nc.nonpinned_reasons(
        {"config": nc.ChainConfig(), "equalizer": RlsDfeConfig(), "noise": True, "diagnostic": False,
         "link": None, "point_index": 3}
    ) == []  # fmt: skip
    out = nc.run_point("p", MID, 80, -5.0)  # pinned arguments, the cap acts: a lost-lock run
    assert out.lost and "trace cap acted" in out.reason


def test_run_point_catches_only_the_two_lost_lock_errors(monkeypatch):
    for exc in (FloatingPointError("x"), ArithmeticError("x"), ZeroDivisionError("x")):

        def boom(*a, exc=exc, **k):
            raise exc

        monkeypatch.setattr(nc, "simulate_point", boom)
        with pytest.raises(type(exc)):
            nc.run_point("p", MID, 80, -5.0)


def test_a_single_cap_action_invalidates_the_run(monkeypatch):
    stub_equalizer(monkeypatch, caps=1)
    with pytest.raises(nc.TraceCapActedError):
        nc.simulate_point(MID, 80, -5.0, config=SMALL)
    stub_equalizer(monkeypatch, caps=0)
    assert nc.simulate_point(MID, 80, -5.0, config=SMALL).dfe.n_trace_caps == 0


def test_relative_imports_are_resolved_by_level():
    tree = ast.parse(
        "from . import a\nfrom .b import c\nfrom .. import d\nfrom ..e import f\nfrom ... import g\n"
    )
    found = nf._imported_modules(tree, "opticps.measurement.sub")
    assert {"opticps.measurement.sub", "opticps.measurement.sub.a", "opticps.measurement.sub.b",
            "opticps.measurement.sub.b.c", "opticps.measurement", "opticps.measurement.d",
            "opticps.measurement.e", "opticps.measurement.e.f", "opticps", "opticps.g"} <= found  # fmt: skip
    assert "opticps.measurement.sub.d" not in found and "opticps.d" not in found


# --- finding 1: Fig.11 is excluded from scoring ----------------------------------------------


def test_every_fig11_series_is_refused_by_code():
    assert nanf_import.SCORING_EXCLUDED_SHEETS == frozenset({"Fig.11"})
    fig11 = [
        (ly.name, b.label, s.header)
        for ly in nanf_import.SHEET_LAYOUTS
        for b in ly.blocks
        for s in b.series
        if ly.name == "Fig.11"
    ]
    assert len(fig11) == 2
    wb = nanf_import.NanfWorkbook("0" * 64, {}, ())
    for key in (nanf_import.series_key(*t) for t in fig11):
        with pytest.raises(nanf_import.NanfImportError) as err:
            wb[key]
        assert err.value.code == "EXCLUDED_FROM_SCORING"
    with pytest.raises(KeyError):
        wb["Fig.12/table/SMF-DMT Capacity"]  # other sheets are not refused, only absent here


def test_the_calibration_partition_is_unchanged_by_the_fig11_exclusion():
    kept = [
        ly.name
        for ly in nanf_import.SHEET_LAYOUTS
        for b in ly.blocks
        for s in b.series
        if s.role is not nanf_import.DataRole.HOLDOUT
    ]
    assert "Fig.11" not in kept and len(kept) == 21


# --- Amendment 9 H-B: grafts are read from the common git directory --------------------------


def test_grafts_are_refused_from_a_linked_worktree_too(tmp_path):
    repo = make_repo(tmp_path)
    main = git(repo.root, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo.root, "checkout", "-q", "--orphan", "side")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "same files, unrelated history")
    side = git(repo.root, "rev-parse", "HEAD")
    git(repo.root, "checkout", "-q", "-f", main)
    wt = tmp_path / "wt"
    git(repo.root, "worktree", "add", "-q", "--detach", str(wt))
    head = git(repo.root, "rev-parse", "HEAD")
    (repo.root / ".git/info").mkdir(exist_ok=True)
    (repo.root / ".git/info/grafts").write_text(f"{head} {side}\n")  # in the COMMON directory
    ancestor = subprocess.run(
        ["git", "-C", str(wt), "merge-base", "--is-ancestor", side, "HEAD"], capture_output=True
    )
    assert ancestor.returncode == 0  # plain Git, in the worktree, believes the graft
    forged = dict(repo.record, calibration={**repo.record["calibration"], "commit": side})
    forged["freeze_hash"] = nf.compute_freeze_hash(
        forged["plan_sha256"], forged["code_identity"], forged["parameters"],
        forged["unidentifiable"], forged["calibration"], forged["calibration_partition_sha256"],
    )  # fmt: skip
    write_record(repo, forged)
    for root in (repo.root, wt):
        with locked(match="grafts"):
            nf.require_freeze(
                forged["freeze_hash"],
                record_path=repo.record_path,
                plan_path=root / "docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md",
                root=root,
            )
    # without the graft file, the worktree verifies a genuine record
    (repo.root / ".git/info/grafts").unlink()
    write_record(repo)
    got = nf.require_freeze(
        repo.hash,
        record_path=repo.record_path,
        plan_path=wt / "docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md",
        root=wt,
    )
    assert got.freeze_hash == repo.hash


# --- Amendment 9 H-C: a true rank deficiency is legal at B4.5 ---------------------------------


def linear_residuals(matrix):
    specs = sc.B4_PARAMETERS

    def residuals(values):
        u = np.array([(values[s.name] - s.low) / (s.high - s.low) for s in specs])
        return matrix @ u

    return residuals


def midpoint():
    return {s.name: 0.5 * (s.low + s.high) for s in sc.B4_PARAMETERS}


def test_a_true_rank_deficiency_with_roundoff_negatives_is_legal_and_flags_the_right_count():
    rng = np.random.default_rng(0)
    base = rng.normal(size=(40, 6))
    same = base.copy()
    same[:, 1] = same[:, 0]  # two identical columns: rank 5
    out = sc.identifiability_check(linear_residuals(same), midpoint())
    assert np.all(out.eigenvalues >= 0.0)
    assert out.eigenvalues[0] <= sc.EIGENVALUE_ROUNDOFF_RELATIVE * out.eigenvalues[-1]
    assert len(out.flagged) == 1 and not out.singular
    rank1 = np.outer(rng.normal(size=40), np.ones(6))  # rank 1: five zero eigenvalues
    out1 = sc.identifiability_check(linear_residuals(rank1), midpoint())
    assert np.all(out1.eigenvalues >= 0.0) and len(out1.flagged) == 5
    assert np.count_nonzero(out1.eigenvalues == 0.0) >= 1  # the round-off negatives were floored
    zero_col = base.copy()
    zero_col[:, 2] = 0.0
    assert len(sc.identifiability_check(linear_residuals(zero_col), midpoint()).flagged) == 1
    # the artefact can record the output as it is: non-negative, ascending, flags equal the count
    checks = {
        "chosen_fit_checked": True,
        "n_lost_points_in_grid": 0,
        "identifiability_eigenvalues": [float(e) for e in out1.eigenvalues],
    }
    nf._check_checks(checks, out1.flagged)


def test_a_truly_negative_eigenvalue_is_still_refused(monkeypatch):
    rng = np.random.default_rng(4)
    matrix = rng.normal(size=(40, 6))
    residuals = linear_residuals(matrix)
    real = np.linalg.eigh

    def with_negative(factor):
        def fake(a):
            w, v = real(a)
            w = w.copy()
            w[0] = -factor * w[-1]
            return w, v

        return fake

    inside = 0.5 * sc.EIGENVALUE_ROUNDOFF_RELATIVE
    outside = 2.0 * sc.EIGENVALUE_ROUNDOFF_RELATIVE
    monkeypatch.setattr(np.linalg, "eigh", with_negative(inside))
    floored = sc.identifiability_check(residuals, midpoint())
    assert floored.eigenvalues[0] == 0.0
    monkeypatch.setattr(np.linalg, "eigh", with_negative(outside))
    with pytest.raises(ValueError, match="negative eigenvalue beyond round-off"):
        sc.identifiability_check(residuals, midpoint())
    assert 1e-10 <= sc.EIGENVALUE_ROUNDOFF_RELATIVE <= 1e-9
    assert sc.EIGENVALUE_ROUNDOFF_RELATIVE < 1e-3 * 1e-5  # far below the B4.3 threshold


def test_a_negative_eigenvalue_in_a_hand_written_artefact_is_still_refused():
    bad = {
        "chosen_fit_checked": True,
        "n_lost_points_in_grid": 0,
        "identifiability_eigenvalues": [-1e-15, 1.0, 2.0, 3.0, 4.0, 5.0],
    }
    with locked(match="six ascending non-negative"):
        nf._check_checks(bad, ("bias_fraction",))


def test_a_declared_calibration_point_still_needs_a_scorable_run_without_a_record(monkeypatch):
    """Two gaps found by the mutant run: the checks of the calibration path are each needed."""
    monkeypatch.setattr(nc, "DECLARED_CALIBRATION_POINTS", frozenset({(100, -6.0, 0)}))
    unscorable = nc.simulate_point(
        MID, 100, -6.0, config=SMALL
    )  # config overridden, point declared
    assert (unscorable.rate_gbps, unscorable.rop_dbm, unscorable.point_index) == (100, -6.0, 0)
    forged = object.__new__(nc.PointOutcome)  # the outcome guard bypassed
    for name, value in (("label", "u"), ("rop_dbm", -6.0), ("result", unscorable), ("reason", "")):
        object.__setattr__(forged, name, value)
    with pytest.raises(nc.NotScorableError, match="cannot be scored"):
        nc.curve_arrays([forged], calibration=True)
    stamped = dataclasses.replace(scorable_result(), frozen_record_hash="a" * 64)
    with pytest.raises(nc.NotScorableError, match="without a record"):
        nc.curve_arrays([nc.PointOutcome("s", -6.0, stamped)], calibration=True)
    clean = nc.PointOutcome("c", -6.0, scorable_result())
    assert nc.curve_arrays([clean], calibration=True).valid.tolist() == [True]


def test_a_back_to_back_point_at_another_wavelength_is_not_a_calibration_point(monkeypatch):
    """Review 4 finding 1: the wavelength half of the back-to-back check (profile None, 1460 nm)."""
    monkeypatch.setattr(nc, "DECLARED_CALIBRATION_POINTS", frozenset({(100, -6.0, 0)}))
    off = nc.LinkSpec(wavelength_nm=1460.0)
    assert off.profile is None and off != nc.LinkSpec()
    other = nc.PointOutcome("w", -6.0, scorable_result(link=off))
    with pytest.raises(nc.NotScorableError, match="back-to-back"):
        nc.curve_arrays([other], calibration=True)
    clean = nc.PointOutcome("c", -6.0, scorable_result())
    assert nc.curve_arrays([clean], calibration=True).valid.tolist() == [True]


@pytest.mark.parametrize("kind", ["garbage", "dangling_symlink"])
def test_calibration_is_refused_while_a_broken_record_exists(kind, tmp_path, monkeypatch):
    """Review 4 finding 2: a garbage file or a dangling symlink at the record path counts."""
    monkeypatch.setattr(nc, "DECLARED_CALIBRATION_POINTS", frozenset({(100, -6.0, 0)}))
    clean = nc.PointOutcome("c", -6.0, scorable_result())
    assert nc.curve_arrays([clean], calibration=True).valid.tolist() == [True]
    record = tmp_path / "NANF_FREEZE_RECORD.json"
    if kind == "garbage":
        record.write_text("not json {{{")
    else:
        record.symlink_to(tmp_path / "missing_target.json")
        assert not record.exists()
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", record)
    assert nf.freeze_record_present()
    with pytest.raises(nc.NotScorableError, match="once a freeze record exists"):
        nc.curve_arrays([clean], calibration=True)
