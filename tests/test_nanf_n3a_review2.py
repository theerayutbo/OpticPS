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
    with pytest.raises(nc.NotScorableError, match="only hold a scorable result"):
        nc.PointOutcome("x", -6.0, r)
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


def test_deleting_the_record_does_not_make_a_vector_scorable_for_scoring():
    r = nc.simulate_point(MID, 100, -6.0, config=SMALL)
    ok = dataclasses.replace(r, unscorable_reasons=())  # a scorable result run without a freeze
    out = nc.PointOutcome("p", -6.0, ok)
    with pytest.raises(nc.NotScorableError, match="verified freeze record"):
        nc.curve_arrays([out])  # the default is scoring: a freeze record is required
    arrays = nc.curve_arrays([out], calibration=True)  # the B2B points of a fit before a freeze
    assert arrays.valid.tolist() == [True]
    framed = nc.PointOutcome("p", -6.0, dataclasses.replace(ok, frozen_record_hash="a" * 64))
    assert nc.curve_arrays([framed]).valid.tolist() == [True]
    with pytest.raises(nc.NotScorableError):
        nc.require_scorable([ok], frozen=True)


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
    with pytest.raises(ValueError, match="needs the ROP axis"):
        sc.b2b_gate([10.0], [10.0], point, point, simulated_valid=[False])


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


def test_an_illegal_cap_through_run_point_is_refused_not_lost_lock():
    for cap in (1.0, 1e4, 1e12):
        with pytest.raises(nc.NotScorableError, match="trace cap cannot be changed"):
            nc.run_point("p", MID, 80, -5.0, equalizer=RlsDfeConfig(p_trace_cap=cap))


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
