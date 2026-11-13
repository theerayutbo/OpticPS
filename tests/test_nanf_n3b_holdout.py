"""N3 part b: the freeze script, the holdout runner and the report, on a stub chain and a synthetic
workbook. No real data, no real workbook, no simulation; the freeze record lives in a throw-away
repository. Plan Amendment 11 J-G.
"""

import json
import math
import subprocess

import pytest

from nanf_fit_stub import objective
from nanf_freeze_support import (
    ARTIFACT_REL,
    PLAN_REL,
    copy_tree,
    git,
    make_repo,
    patch_module_paths,
    session_repo,
)
from nanf_holdout_stub import holdout_workbook, lose_nanf_at_minus_12, stub_point
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_fit as nfit
from opticps.measurement import nanf_freeze as nfz
from opticps.measurement import nanf_holdout as nh
from opticps.measurement.nanf_chain import BerReading, PointResult


@pytest.fixture
def frozen(tmp_path_factory, monkeypatch):
    repo = session_repo(tmp_path_factory)  # shared and never modified by these tests
    patch_module_paths(monkeypatch, repo)
    return repo


class Reader:
    """A stand-in for `read_nanf_workbook` that records how it was called."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return holdout_workbook()


def run(frozen, tmp_path, runner=stub_point, reader=None):
    reader = Reader() if reader is None else reader
    result = nh.run_holdout(
        "unused.xlsx",
        frozen.hash,
        runner=runner,
        reader=reader,
        marker_path=tmp_path / "marker.json",
    )
    return result, reader


# --- the order of the run (D5) ------------------------------------------------------------------


def test_without_a_freeze_record_the_run_stops_before_the_marker_and_before_the_read(tmp_path):
    reader = Reader()
    with pytest.raises(nfz.HoldoutLockedError):
        nh.run_holdout(
            "unused.xlsx",
            "0" * 64,
            runner=stub_point,
            reader=reader,
            marker_path=tmp_path / "m.json",
        )
    assert reader.calls == [] and not (tmp_path / "m.json").exists()


def test_a_hash_that_is_not_the_record_hash_is_refused_before_the_marker(frozen, tmp_path):
    reader = Reader()
    with pytest.raises(nfz.HoldoutLockedError):
        nh.run_holdout(
            "unused.xlsx",
            "f" * 64,
            runner=stub_point,
            reader=reader,
            marker_path=tmp_path / "m.json",
        )
    assert reader.calls == [] and not (tmp_path / "m.json").exists()


def test_the_read_asks_for_the_holdout_with_the_freeze_hash_and_the_marker_holds_that_hash(
    frozen, tmp_path
):
    result, reader = run(frozen, tmp_path)
    assert reader.calls == [("unused.xlsx", {"include_holdout": True, "freeze_hash": frozen.hash})]
    assert json.loads((tmp_path / "marker.json").read_text())["freeze_hash"] == frozen.hash
    assert result.freeze_hash == frozen.hash and set(result.rates) == {80, 100, 112}


def test_a_second_run_under_the_same_record_is_allowed_and_gives_the_same_result(frozen, tmp_path):
    first, _ = run(frozen, tmp_path)
    second, _ = run(frozen, tmp_path)
    assert nh.build_report(first) == nh.build_report(second)


def test_a_run_under_another_record_after_the_marker_exists_is_refused_before_the_read(
    frozen, tmp_path
):
    (tmp_path / "marker.json").write_text(json.dumps({"freeze_hash": "a" * 64}))
    reader = Reader()
    with pytest.raises(nh.HoldoutAlreadyReadError, match="another freeze record"):
        run(frozen, tmp_path, reader=reader)
    assert reader.calls == []


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"other": 1}'])
def test_a_marker_that_cannot_be_read_is_a_refusal(frozen, tmp_path, content):
    (tmp_path / "marker.json").write_text(content)
    reader = Reader()
    with pytest.raises(nh.HoldoutAlreadyReadError, match="cannot be read"):
        run(frozen, tmp_path, reader=reader)
    assert reader.calls == []


# --- the scores and the verdict -------------------------------------------------------------------


def test_the_stub_run_scores_the_primary_criteria_and_never_reads_consistent(frozen, tmp_path):
    result, _ = run(frozen, tmp_path)
    for r in result.rates.values():
        assert r.c1.passed and r.c2.passed and r.c3.passed and r.gate.passed and r.gate.label == ""
        assert not r.c1_discriminating and not r.c2_discriminating  # d is 0.3 dB: no information
        assert r.lost == ()
    assert result.verdict == nh.VERDICT_INCOMPLETE  # C5 was not run: not a pass
    assert "consistent" not in result.verdict


def test_a_failed_primary_criterion_is_a_failure_with_the_criterion_and_the_rate(frozen, tmp_path):
    def too_noisy(task):
        p = stub_point(task)
        return nh.HoldoutPoint(
            False,
            "",
            p.ber,
            p.snr_db - (4.0 if task.rate == 100 and task.link_key == nh.NANF_LINK else 0.0),
            p.n_bits,
        )

    result, _ = run(frozen, tmp_path, runner=too_noisy)
    assert result.verdict.startswith("failed: ") and "C2@100" in result.verdict
    assert "(C5 not run)" in result.verdict and "C2@80" not in result.verdict


def test_a_lost_lock_point_is_listed_fails_what_needs_it_and_is_never_skipped(frozen, tmp_path):
    result, _ = run(frozen, tmp_path, runner=lose_nanf_at_minus_12)
    assert any("LOST LOCK NANF at -12 dBm" in line for line in result.lost)
    assert len(result.lost) == 3  # one per rate
    for r in result.rates.values():
        assert not r.c2.passed and r.c2.n_invalid == 1  # H3: no substitution
        assert r.d_snr is None  # d is undefined at a lost point
    assert result.verdict.startswith("failed: ") and "C2@80" in result.verdict


def test_the_b2b_gate_fails_and_is_labelled_when_the_model_b2b_is_off(frozen, tmp_path):
    def b2b_bad(task):
        p = stub_point(task)
        if task.label.startswith("B2B"):
            return nh.HoldoutPoint(False, "", p.ber, p.snr_db - 2.5, p.n_bits)
        return p

    result, _ = run(frozen, tmp_path, runner=b2b_bad)
    assert {r.gate.label for r in result.rates.values()} == {"B2B CALIBRATION POOR"}


def test_the_points_run_are_the_scored_ones_with_the_axis_index_and_a_declared_link(
    frozen, tmp_path
):
    seen = []

    def spy(task):
        seen.append(task)
        return stub_point(task)

    run(frozen, tmp_path, runner=spy)
    assert len(seen) == 3 * (6 + 8 + 6 + 8)  # NANF, SSMF (<= -5 dBm), no-fibre, B2B gate
    for t in seen:
        assert t.point_index in nc.DECLARED_POINT_INDICES and t.rop_dbm <= -5.0
        assert t.link_key is None or t.link_key in nc.DECLARED_LINKS
    nanf = [t for t in seen if t.link_key == nh.NANF_LINK and t.rate == 80]
    assert [t.point_index for t in nanf] == list(range(6))  # position on the published axis
    nofibre = [t for t in seen if t.label.startswith("no-fibre") and t.rate == 80]
    assert [t.point_index for t in nofibre] == list(range(6))  # the index of the NANF point
    gate = [(t.rop_dbm, t.point_index) for t in seen if t.label.startswith("B2B") and t.rate == 80]
    assert gate == [(-12.0 + k, k) for k in range(8)]
    assert {(t.rate, t.rop_dbm, t.point_index) for t in seen if t.label.startswith("B2B")} == (
        nc.DECLARED_CALIBRATION_POINTS
    )


# --- the report (D5) ------------------------------------------------------------------------------


def test_the_report_has_the_label_the_required_sentence_and_what_was_not_run(frozen, tmp_path):
    result, _ = run(frozen, tmp_path, runner=lose_nanf_at_minus_12)
    text = nh.build_report(result)
    assert "LITERATURE BENCHMARK / CALIBRATION ONLY" in text
    assert "The holdout is not fully blind" in text
    assert nh.C5_STATUS in text and "NOT RUN (links not declared)" in text
    assert "C6, C7, C8: NOT BUILT" in text and "expected FAIL at 2.0 GHz" in text
    assert "LOST LOCK NANF at -12 dBm" in text
    assert "B2B-copy comparator" in text and result.freeze_hash in text
    assert "validation" not in text.lower()
    assert "consistent with this one experiment" not in text


def test_the_report_of_an_incomplete_run_does_not_claim_a_pass(frozen, tmp_path):
    result, _ = run(frozen, tmp_path)
    text = nh.build_report(result)
    assert nh.VERDICT_INCOMPLETE in text
    assert (
        "consistent with one published experiment" in text
    )  # the only permitted wording, as a limit
    assert "validation" not in text.lower() and "C5" in text


# --- the real runner's plumbing, with no simulation --------------------------------------------


def test_the_real_runner_passes_the_declared_link_and_index_and_scores_under_the_record(
    frozen, monkeypatch
):
    seen = {}

    def fake_simulate(params, rate, rop, *, link=None, point_index=0, **kw):
        record = nfz.load_freeze_record()
        seen.update(link=link, index=point_index, params=params, kw=kw)
        return PointResult(
            reading=BerReading.from_counts(500, 1_294_016), snr_db=12.0, ser=0.0,
            n_scored_symbols=647_008, laser_power_w=1e-3, mean_received_dbm=rop, seconds={},
            dfe=None, frozen_record_hash=record.freeze_hash, rate_gbps=rate, rop_dbm=float(rop),
            point_index=point_index, link=nc.LinkSpec() if link is None else link,
        )  # fmt: skip  # type: ignore[arg-type]

    monkeypatch.setattr(nc, "simulate_point", fake_simulate)
    task = nh.HoldoutTask("NANF/80G/-9", nh.NANF_LINK, 80, -9.0, 3)
    point = nh.simulate_holdout_point(task)
    assert seen["link"] == nc.DECLARED_LINKS[nh.NANF_LINK] and seen["index"] == 3
    assert seen["params"] is None  # after a freeze the record's vector is used
    assert not point.lost and point.snr_db == 12.0 and point.ber == pytest.approx(500 / 1_294_016)
    back = nh.simulate_holdout_point(nh.HoldoutTask("B2B/80G/-9", None, 80, -9.0, 2))
    assert seen["link"] is None and seen["index"] == 2 and not back.lost


def test_the_real_runner_returns_a_lost_point_with_its_reason(frozen, monkeypatch):
    def lost(*args, **kwargs):
        raise nc.TraceCapActedError("stub")

    monkeypatch.setattr(nc, "simulate_point", lost)
    point = nh.simulate_holdout_point(nh.HoldoutTask("NANF/80G/-9", nh.NANF_LINK, 80, -9.0, 3))
    assert point.lost and "trace cap acted" in point.reason and math.isnan(point.ber)


def test_the_real_runner_refuses_an_undeclared_link_and_an_unscorable_result(frozen, monkeypatch):
    with pytest.raises(KeyError):
        nh.simulate_holdout_point(nh.HoldoutTask("x", "SSMF-5km", 80, -9.0, 3))

    def undeclared_index(params, rate, rop, *, link=None, point_index=0, **kw):
        return PointResult(
            reading=BerReading.from_counts(500, 1_294_016), snr_db=12.0, ser=0.0,
            n_scored_symbols=647_008, laser_power_w=1e-3, mean_received_dbm=rop, seconds={},
            dfe=None, unscorable_reasons=("point_index not declared (plan Amendment 8)",),
            rate_gbps=rate, rop_dbm=float(rop), point_index=point_index,
        )  # fmt: skip  # type: ignore[arg-type]

    monkeypatch.setattr(nc, "simulate_point", undeclared_index)
    with pytest.raises(nc.NotScorableError, match="cannot be scored"):
        nh.simulate_holdout_point(nh.HoldoutTask("x", None, 80, -9.0, 99))


# --- the freeze script (D4) -----------------------------------------------------------------------


def fresh_repo(tmp_path, name="repo"):
    return make_repo(tmp_path, name=name)


def test_the_freeze_script_writes_a_record_that_verifies(tmp_path):
    repo = fresh_repo(tmp_path)
    record = nh.write_freeze_record(
        ARTIFACT_REL, root=repo.root, plan_path=repo.plan, record_path=repo.record_path
    )
    assert record == repo.record and json.loads(repo.record_path.read_text()) == record
    loaded = nfz.load_freeze_record(
        record_path=repo.record_path, plan_path=repo.plan, root=repo.root
    )
    assert loaded.freeze_hash == record["freeze_hash"]


def test_the_freeze_script_refuses_a_second_freeze(tmp_path):
    repo = fresh_repo(tmp_path)
    kw = {"root": repo.root, "plan_path": repo.plan, "record_path": repo.record_path}
    nh.write_freeze_record(ARTIFACT_REL, **kw)
    before = repo.record_path.read_bytes()
    with pytest.raises(nh.FreezeRefusedError, match="one freeze only"):
        nh.write_freeze_record(ARTIFACT_REL, **kw)
    assert repo.record_path.read_bytes() == before


@pytest.mark.parametrize(
    "path",
    [
        "src/opticps/measurement/nanf_chain.py",
        "src/opticps/measurement/nanf_holdout.py",
        "src/opticps/receiver/dfe.py",
        "pyproject.toml",
        "uv.lock",
        "configs/fibers/NANF-HONG-2021-4P76KM.yaml",
        PLAN_REL,
        ARTIFACT_REL,
    ],
)
def test_the_freeze_script_refuses_a_dirty_path_of_the_identity_the_plan_or_the_artefact(
    tmp_path, path
):
    repo = fresh_repo(tmp_path)
    with (repo.root / path).open("a") as handle:
        handle.write("\n# edited after the commit\n")
    with pytest.raises(nh.FreezeRefusedError, match="differs from HEAD"):
        nh.write_freeze_record(
            ARTIFACT_REL, root=repo.root, plan_path=repo.plan, record_path=repo.record_path
        )
    assert not repo.record_path.exists()


def test_the_freeze_script_refuses_a_new_untracked_file_in_the_identity(tmp_path):
    repo = fresh_repo(tmp_path)
    (repo.root / "configs/fibers/NEW-PROFILE.yaml").write_text("fiber_profile_version: 1\n")
    with pytest.raises(nh.FreezeRefusedError, match="NEW-PROFILE"):
        nh.write_freeze_record(
            ARTIFACT_REL, root=repo.root, plan_path=repo.plan, record_path=repo.record_path
        )
    assert not repo.record_path.exists()


def test_the_freeze_script_refuses_an_artefact_that_is_not_committed_at_head(tmp_path):
    repo = fresh_repo(tmp_path)
    other = repo.root / "docs/benchmarks/OTHER_ARTEFACT.json"
    other.write_bytes((repo.root / ARTIFACT_REL).read_bytes())
    with pytest.raises((nfz.HoldoutLockedError, nh.FreezeRefusedError)):
        nh.write_freeze_record(
            "docs/benchmarks/OTHER_ARTEFACT.json",
            root=repo.root,
            plan_path=repo.plan,
            record_path=repo.record_path,
        )
    assert not repo.record_path.exists()


def test_the_freeze_script_refuses_when_git_cannot_run(tmp_path, monkeypatch):
    repo = fresh_repo(tmp_path)

    def broken(root, *args):
        return subprocess.CompletedProcess(args, 128, b"", b"fatal")

    monkeypatch.setattr(nfz, "_git", broken)
    with pytest.raises(nh.FreezeRefusedError, match="git could not report"):
        nh.write_freeze_record(
            ARTIFACT_REL, root=repo.root, plan_path=repo.plan, record_path=repo.record_path
        )
    assert not repo.record_path.exists()


def test_the_artefact_of_the_fit_driver_is_accepted_by_the_freeze_script(tmp_path):
    out = nfit.fit(
        objective(), log_path=tmp_path / "log.jsonl", plan_sha256="a" * 64, code_identity="b" * 64
    )
    assert out.artefact is not None
    root = tmp_path / "repo"
    root.mkdir()
    copy_tree(root)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    (root / ARTIFACT_REL).write_bytes(out.artefact)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the artefact of the fit driver, stub chain")
    target = tmp_path / "record.json"
    record = nh.write_freeze_record(
        ARTIFACT_REL, root=root, plan_path=root / PLAN_REL, record_path=target
    )
    assert record["unidentifiable"] == list(out.identifiability.flagged)
    assert nfz.load_freeze_record(record_path=target, plan_path=root / PLAN_REL, root=root)


def test_the_holdout_runner_is_part_of_the_code_identity(tmp_path):
    assert "opticps.measurement.nanf_holdout" in nfz.ENTRY_MODULES
    assert "src/opticps/measurement/nanf_holdout.py" in nfz.identity_files()
    repo = fresh_repo(tmp_path)
    before = nfz.code_identity(repo.root)
    with (repo.root / "src/opticps/measurement/nanf_holdout.py").open("a") as handle:
        handle.write("\n# an edit after the freeze\n")
    assert nfz.code_identity(repo.root) != before


def test_the_real_runner_refuses_a_result_that_did_not_run_under_the_record(frozen, monkeypatch):
    def unrecorded(params, rate, rop, *, link=None, point_index=0, **kw):
        return PointResult(
            reading=BerReading.from_counts(500, 1_294_016), snr_db=12.0, ser=0.0,
            n_scored_symbols=647_008, laser_power_w=1e-3, mean_received_dbm=rop, seconds={},
            dfe=None, frozen_record_hash=None, rate_gbps=rate, rop_dbm=float(rop),
            point_index=point_index,
        )  # fmt: skip  # type: ignore[arg-type]

    monkeypatch.setattr(nc, "simulate_point", unrecorded)
    with pytest.raises(nc.NotScorableError, match="freeze record"):
        nh.simulate_holdout_point(nh.HoldoutTask("B2B/80G/-9", None, 80, -9.0, 2))
