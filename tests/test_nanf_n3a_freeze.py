"""Gate N3 part a: the holdout read is tied to the freeze record (plan D6, F8, Amendment 6 G4 to G6).
Default deny.

Nothing here freezes anything: every record is built in a temporary directory over a throw-away Git
repository, and the committed record path is asserted to be absent. All vectors are synthetic.
"""

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from nanf_freeze_support import (
    ARTIFACT_REL,
    FLAGS,
    GOOD_FIT,
    PARAMS,
    PLAN_REL,
    git,
    make_repo,
    patch_module_paths,
    write_artifact,
    write_record,
)
from nanf_workbook_fixture import make_workbook
from opticps.measurement import nanf_freeze as nf
from opticps.measurement.nanf_chain import B4_NAMES, TxRxParameters
from opticps.measurement.nanf_import import (
    DataRole,
    NanfImportError,
    calibration_partition_sha256,
    read_nanf_workbook,
)


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    return path, make_workbook(path)


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path)


@pytest.fixture
def record_file(repo, monkeypatch):
    patch_module_paths(monkeypatch, repo)
    return repo.record_path, repo.record


def holdout(workbook, **kw):
    path, digest = workbook
    return read_nanf_workbook(path, expected_sha256=digest, include_holdout=True, **kw)


def locked(**kw):
    return pytest.raises(nf.HoldoutLockedError, **kw)


def test_nothing_is_frozen_by_this_gate():
    assert not Path("docs/benchmarks/NANF_FREEZE_RECORD.json").exists()
    assert not Path("docs/benchmarks/NANF_CALIBRATION_RESULT.json").exists()
    assert nf.FREEZE_RECORD_PATH.name == "NANF_FREEZE_RECORD.json"
    assert nf.FREEZE_RECORD_PATH.parent.name == "benchmarks"
    assert nf.COMMITTED_RECORD_PATH == nf.FREEZE_RECORD_PATH
    assert not nf.freeze_record_present()


def test_a_bare_include_holdout_true_is_an_error_and_no_file_is_opened(tmp_path):
    missing = tmp_path / "no-such-file.xlsx"
    with pytest.raises(NanfImportError) as err:
        read_nanf_workbook(missing, include_holdout=True)
    assert err.value.code == "HOLDOUT_LOCKED"  # not SOURCE_MISSING: the guard comes first
    assert "freeze" in str(err.value)
    assert err.value.__cause__ is None


def test_a_truthy_include_holdout_that_is_not_true_is_still_guarded(workbook):
    # `if include_holdout is True` would let 1 through the proof while still returning the holdout
    path, digest = workbook
    for flag in (1, "yes", [0]):
        with pytest.raises(NanfImportError) as err:
            read_nanf_workbook(
                path, expected_sha256=digest, include_holdout=flag, freeze_hash="0" * 64
            )
        assert err.value.code == "HOLDOUT_LOCKED"


def test_with_no_freeze_record_nothing_unlocks_the_holdout(workbook):
    # the committed record does not exist: every hash, plausible or not, is refused
    for h in ("0" * 64, "a" * 64, None, "", 5, "not-a-hash", "A" * 64, "0" * 63):
        with pytest.raises(NanfImportError) as err:
            holdout(workbook, freeze_hash=h)
        assert err.value.code == "HOLDOUT_LOCKED"


def test_a_valid_proof_unlocks_the_holdout_and_the_default_read_still_withholds_it(
    workbook, record_file
):
    _, record = record_file
    wb = holdout(workbook, freeze_hash=record["freeze_hash"])
    assert sum(s.role is DataRole.HOLDOUT for s in wb.series.values()) == 48
    path, digest = workbook
    plain = read_nanf_workbook(path, expected_sha256=digest)  # no proof needed without holdout
    assert not any(s.role is DataRole.HOLDOUT for s in plain.series.values())
    again = read_nanf_workbook(path, expected_sha256=digest, freeze_hash="junk")  # ignored
    assert len(again.series) == 21
    verified = nf.require_freeze(record["freeze_hash"])
    assert verified.parameters == PARAMS and verified.unidentifiable == FLAGS
    assert verified.calibration_path == ARTIFACT_REL
    assert verified.calibration_commit == record["calibration"]["commit"]


def test_a_wrong_hash_or_a_bare_flag_with_a_record_present_is_refused(workbook, record_file):
    _, record = record_file
    other = "0" * 64
    for h in (other, record["freeze_hash"][::-1], record["freeze_hash"].upper(), None):
        with pytest.raises(NanfImportError) as err:
            holdout(workbook, freeze_hash=h)
        assert err.value.code == "HOLDOUT_LOCKED"


def test_a_test_only_record_cannot_unlock_a_file_with_the_real_workbooks_hash(
    workbook, record_file, monkeypatch
):
    # Amendment 6 G6: the real workbook is unlocked only by the record at the committed path
    path, digest = workbook
    _, record = record_file
    holdout(workbook, freeze_hash=record["freeze_hash"])  # a synthetic file: allowed
    monkeypatch.setattr("opticps.measurement.nanf_import.NANF_WORKBOOK_SHA256", digest)
    # now the same bytes count as the real workbook: the patched test record no longer helps
    with pytest.raises(NanfImportError) as err:
        read_nanf_workbook(
            path, expected_sha256=digest, include_holdout=True, freeze_hash=record["freeze_hash"]
        )
    assert err.value.code == "HOLDOUT_LOCKED"
    assert "no freeze record" in str(err.value)  # nothing exists at the committed path
    plain = read_nanf_workbook(path, expected_sha256=digest)  # the default read is unaffected
    assert len(plain.series) == 21


def rewrite(path, edit):
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return data


def rehash(record):
    """A forged record whose own hash is consistent, so only the other checks can refuse it."""
    out = copy.deepcopy(record)
    out["freeze_hash"] = nf.compute_freeze_hash(
        out["plan_sha256"],
        out["code_identity"],
        out["parameters"],
        out["unidentifiable"],
        out["calibration"],
        out["calibration_partition_sha256"],
    )
    return out


def test_a_record_that_disagrees_with_its_own_hash_is_refused(workbook, record_file):
    path, record = record_file
    rewrite(path, lambda d: d["parameters"].update(tx_bandwidth_ghz=33.0))  # hash not updated
    with pytest.raises(NanfImportError, match="not consistent with its own hash"):
        holdout(workbook, freeze_hash=record["freeze_hash"])
    path.write_text(json.dumps(record))
    rewrite(path, lambda d: d.update(unidentifiable=[]))
    with pytest.raises(NanfImportError, match="own hash"):
        holdout(workbook, freeze_hash=record["freeze_hash"])


def test_a_consistent_record_with_a_changed_plan_is_refused(repo):
    write_record(repo)
    kw = dict(record_path=repo.record_path, root=repo.root)
    assert nf.require_freeze(repo.hash, plan_path=repo.plan, **kw)
    repo.plan.write_text(repo.plan.read_text() + "\nAn amendment after the freeze.\n")
    with locked(match="plan has changed"):
        nf.require_freeze(repo.hash, plan_path=repo.plan, **kw)


def test_the_code_identity_is_computed_from_imports_and_covers_the_named_files(repo):
    files = set(nf.identity_files(repo.root))
    for name in (
        "src/opticps/optical_channel/link.py",
        "src/opticps/optical_channel/fiber.py",
        "src/opticps/measurement/nanf_import.py",
        "src/opticps/measurement/nanf_benchmark.py",
        "src/opticps/receiver/dfe.py",
        "src/opticps/measurement/nanf_chain.py",
        "src/opticps/measurement/nanf_scoring.py",
        "src/opticps/measurement/nanf_freeze.py",
        "src/opticps/transmitter/pulse.py",
        "src/opticps/modulation/pam.py",
        "src/opticps/__init__.py",
        "pyproject.toml",
        "uv.lock",
    ):
        assert name in files, name
    # a file that nothing in the scoring path imports is not part of it
    assert "src/opticps/cli/main.py" not in files
    assert "src/opticps/measurement/uxr_compare.py" not in files


def test_editing_any_file_of_the_identity_relocks(repo):
    write_record(repo)
    kw = dict(record_path=repo.record_path, plan_path=repo.plan, root=repo.root)
    assert nf.require_freeze(repo.hash, **kw)
    names = nf.identity_files(repo.root)
    assert len(names) >= 12
    for name in names:
        target = repo.root / name
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n")  # one byte
            with locked(match="code has changed"):
                nf.require_freeze(repo.hash, **kw)
        finally:
            target.write_bytes(original)
        assert nf.require_freeze(repo.hash, **kw)  # restored: unlocked again


def test_a_new_import_on_the_scoring_path_enters_the_identity(repo):
    write_record(repo)
    kw = dict(record_path=repo.record_path, plan_path=repo.plan, root=repo.root)
    extra = repo.root / "src/opticps/measurement/zz_new_helper.py"
    extra.write_text("VALUE = 1\n")
    chain = repo.root / "src/opticps/measurement/nanf_scoring.py"
    chain.write_text(
        chain.read_text().replace(
            "import math\n",
            "import math\nfrom opticps.measurement import zz_new_helper  # noqa: F401\n",
            1,
        )
    )
    assert "src/opticps/measurement/zz_new_helper.py" in nf.identity_files(repo.root)
    # the importing file changed, so the old record is refused; a new record covers the helper
    with locked(match="code has changed"):
        nf.require_freeze(repo.hash, **kw)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "scoring imports a helper")
    new = nf.build_freeze_record(ARTIFACT_REL, root=repo.root, plan_path=repo.plan)
    repo.record_path.write_text(json.dumps(new))
    assert nf.require_freeze(new["freeze_hash"], **kw)
    extra.write_text("VALUE = 2\n")
    with locked(match="code has changed"):
        nf.require_freeze(new["freeze_hash"], **kw)


def test_a_function_level_import_is_followed(repo):
    helper = repo.root / "src/opticps/measurement/zz_lazy.py"
    helper.write_text("X = 1\n")
    scoring = repo.root / "src/opticps/measurement/nanf_scoring.py"
    scoring.write_text(
        scoring.read_text() + "\n\ndef _lazy():\n    import opticps.measurement.zz_lazy\n"
    )
    assert "src/opticps/measurement/zz_lazy.py" in nf.identity_files(repo.root)


def test_malformed_records_are_refused(workbook, record_file):
    path, record = record_file
    h = record["freeze_hash"]

    def broken(raw: str, match: str):
        path.write_text(raw)
        with pytest.raises(NanfImportError, match=match) as err:
            holdout(workbook, freeze_hash=h)
        assert err.value.code == "HOLDOUT_LOCKED"

    good = json.dumps(record)
    broken("{", "not valid JSON")
    broken("[]", "exactly the declared fields")
    broken(good[:-1] + ', "extra": 1}', "exactly the declared fields")
    broken(
        json.dumps({k: v for k, v in record.items() if k != "unidentifiable"}), "declared fields"
    )
    dup = good.replace('"plan_sha256"', '"plan_sha256": "x", "plan_sha256"', 1)
    broken(dup, "unique keys")
    bad_hex = copy.deepcopy(record)
    bad_hex["plan_sha256"] = "G" * 64
    broken(json.dumps(bad_hex), "plan_sha256 is not a SHA-256")
    bad_hex = copy.deepcopy(record)
    bad_hex["code_identity"] = 5
    broken(json.dumps(bad_hex), "code_identity is not a SHA-256")
    bad_hex = copy.deepcopy(record)
    bad_hex["calibration_partition_sha256"] = "x"
    broken(json.dumps(bad_hex), "calibration_partition_sha256 is not a SHA-256")
    for edit, match in (
        (lambda p: p.update(tx_bandwidth_ghz=61.0), "not a valid B4 vector"),
        (lambda p: p.update(modulation_depth=float("nan")), "not a valid B4 vector"),
        (lambda p: p.pop("bias_fraction"), "not a valid B4 vector"),
        (lambda p: p.update(chirp=0.0), "not a valid B4 vector"),
        (lambda p: p.update(bias_fraction="0.5"), "not a valid B4 vector"),
    ):
        bad = copy.deepcopy(record)
        edit(bad["parameters"])
        broken(json.dumps(bad), match)
    for flags in ("bias_fraction", ["chirp"], ["bias_fraction", "bias_fraction"], [1]):
        bad = copy.deepcopy(record)
        bad["unidentifiable"] = flags
        broken(json.dumps(bad), "unidentifiable list")
    path.write_bytes(b"x" * (nf.MAX_RECORD_BYTES + 1))
    with pytest.raises(NanfImportError, match="too large"):
        holdout(workbook, freeze_hash=h)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(NanfImportError, match="not valid JSON"):
        holdout(workbook, freeze_hash=h)


def test_hostile_content_gives_holdout_locked_and_never_a_raw_exception(workbook, record_file):
    path, record = record_file
    h = record["freeze_hash"]
    huge = "9" * 400
    cases = {
        "a 400-digit integer": json.dumps(record).replace(
            '"tx_bandwidth_ghz":', f'"tx_bandwidth_ghz": {huge}, "x":', 1
        ),
        "deep nesting": "[" * 100_000 + "]" * 100_000,
        "deep nesting in a field": '{"plan_sha256": ' + "[" * 50_000 + "]" * 50_000 + "}",
    }
    bad = copy.deepcopy(record)
    bad["parameters"]["tx_bandwidth_ghz"] = int(huge)
    cases["a huge integer parameter"] = json.dumps(bad)
    bad = copy.deepcopy(record)
    bad["calibration"] = {"path": 5, "sha256": [], "commit": None}
    cases["wrong types in the calibration reference"] = json.dumps(bad)
    for label, raw in cases.items():
        path.write_text(raw)
        with pytest.raises(NanfImportError) as err:  # not OverflowError, not RecursionError
            holdout(workbook, freeze_hash=h)
        assert err.value.code == "HOLDOUT_LOCKED", label
    with locked():
        nf.require_freeze(h)  # direct call: also a HoldoutLockedError, nothing else


def test_a_symlinked_or_directory_record_is_refused(workbook, repo, tmp_path, monkeypatch):
    patch_module_paths(monkeypatch, repo)
    link = tmp_path / "link.json"
    link.symlink_to(repo.record_path)
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", link)
    with pytest.raises(NanfImportError, match="no freeze record"):
        holdout(workbook, freeze_hash=repo.hash)
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", tmp_path)  # a directory
    with pytest.raises(NanfImportError, match="no freeze record"):
        holdout(workbook, freeze_hash=repo.hash)


def test_the_freeze_hash_is_the_canonical_json_digest_of_the_content_fields(repo):
    record = repo.record
    keys = (
        "plan_sha256",
        "code_identity",
        "parameters",
        "unidentifiable",
        "calibration",
        "calibration_partition_sha256",
    )
    body = {k: record[k] for k in keys}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(raw).hexdigest() == record["freeze_hash"]
    assert set(record["parameters"]) == set(B4_NAMES) and len(record) == 7
    assert record["plan_sha256"] == nf.plan_sha256(repo.plan)
    assert record["code_identity"] == nf.code_identity(repo.root)
    assert record["calibration_partition_sha256"] == calibration_partition_sha256()
    assert set(record["calibration"]) == {"path", "sha256", "commit"}
    # any change of a content field changes the hash
    base = (
        "a" * 64,
        "b" * 64,
        PARAMS.as_dict(),
        [],
        {"path": ARTIFACT_REL, "sha256": "c" * 64, "commit": "d" * 40},
        "e" * 64,
    )
    reference = nf.compute_freeze_hash(*base)
    for index, changed in (
        (0, "f" * 64),
        (1, "f" * 64),
        (2, {**PARAMS.as_dict(), "tx_bandwidth_ghz": 31.5}),
        (3, ["bias_fraction"]),
        (4, {**base[4], "commit": "f" * 40}),
        (4, {**base[4], "sha256": "f" * 64}),
        (4, {**base[4], "path": "docs/benchmarks/other.json"}),
        (5, "f" * 64),
    ):
        edited = list(base)
        edited[index] = changed
        assert nf.compute_freeze_hash(*edited) != reference, (index, changed)


# --- the calibration artefact (Amendment 6 G4) ---------------------------------------------------


def test_the_record_binds_a_committed_artefact_and_its_vector(repo):
    ref = repo.record["calibration"]
    raw = (repo.root / ARTIFACT_REL).read_bytes()
    assert ref["path"] == ARTIFACT_REL and ref["sha256"] == hashlib.sha256(raw).hexdigest()
    assert ref["commit"] == git(repo.root, "rev-parse", "HEAD")
    assert json.loads(raw)["parameters"] == repo.record["parameters"] == PARAMS.as_dict()


def test_building_a_record_writes_nothing_and_needs_a_real_artefact(repo, tmp_path):
    before = sorted(p.name for p in Path("docs/benchmarks").iterdir())
    with locked(match="absent"):
        nf.build_freeze_record("docs/benchmarks/NO_SUCH.json", root=repo.root, plan_path=repo.plan)
    assert sorted(p.name for p in Path("docs/benchmarks").iterdir()) == before
    assert not repo.record_path.exists()


def refuse_with(repo, match, **kw):
    write_record(repo)
    with locked(match=match):
        nf.require_freeze(
            repo.hash, record_path=repo.record_path, plan_path=repo.plan, root=repo.root, **kw
        )


def test_an_absent_artefact_is_refused(repo):
    (repo.root / ARTIFACT_REL).unlink()
    refuse_with(repo, "artefact is absent")


def test_an_uncommitted_artefact_is_refused(repo):
    git(repo.root, "rm", "-q", "--cached", ARTIFACT_REL)  # present on disk, not tracked
    refuse_with(repo, "not committed")


def test_an_artefact_modified_after_its_commit_is_refused(repo):
    path = repo.root / ARTIFACT_REL
    body = json.loads(path.read_bytes())
    body["fit_result"]["cost"] = 0.5
    path.write_bytes(nf.canonical_json(body))
    refuse_with(repo, "does not match its recorded SHA-256")
    # the same file with its new hash recorded is caught as an uncommitted change
    forged = copy.deepcopy(repo.record)
    forged["calibration"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_record(repo, rehash(forged))
    with locked(match="uncommitted changes"):
        nf.require_freeze(
            rehash(forged)["freeze_hash"],
            record_path=repo.record_path,
            plan_path=repo.plan,
            root=repo.root,
        )


def test_an_artefact_that_is_not_the_recorded_file_is_refused(repo):
    forged = copy.deepcopy(repo.record)
    forged["calibration"]["sha256"] = "0" * 64
    write_record(repo, rehash(forged))
    with locked(match="recorded SHA-256"):
        nf.require_freeze(
            rehash(forged)["freeze_hash"],
            record_path=repo.record_path,
            plan_path=repo.plan,
            root=repo.root,
        )


def forged_commit(repo, commit, match):
    forged = rehash(
        {
            **copy.deepcopy(repo.record),
            "calibration": {**repo.record["calibration"], "commit": commit},
        }
    )
    write_record(repo, forged)
    with locked(match=match):
        nf.require_freeze(
            forged["freeze_hash"],
            record_path=repo.record_path,
            plan_path=repo.plan,
            root=repo.root,
        )


def test_a_commit_that_does_not_hold_the_artefact_is_refused(repo):
    forged_commit(repo, repo.base_commit, "does not hold the calibration artefact")
    forged_commit(repo, "0" * 40, "does not hold the calibration artefact")


def test_a_commit_that_is_not_an_ancestor_of_head_is_refused(repo):
    main = git(repo.root, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo.root, "checkout", "-q", "--orphan", "side")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "the same files on an unrelated branch")
    side = git(repo.root, "rev-parse", "HEAD")
    git(repo.root, "checkout", "-q", "-f", main)
    assert git(repo.root, "rev-parse", "HEAD") != side
    forged_commit(repo, side, "not an ancestor of HEAD")


def test_an_artefact_at_the_default_vector_with_no_fit_result_is_refused(tmp_path):
    for fit in (None, {}):
        with locked(match="default vector with no fit result"):
            make_repo(tmp_path, TxRxParameters(), (), fit_result=fit, name=f"defaults{fit}")


def test_an_artefact_with_no_fit_result_or_a_bad_one_is_refused(tmp_path):
    with locked(match="no fit result"):
        make_repo(tmp_path, PARAMS, FLAGS, fit_result=None, name="nofit")
    for k, bad in enumerate(
        (
            {**GOOD_FIT, "cost": float("nan")},
            {**GOOD_FIT, "cost": -1.0},
            {**GOOD_FIT, "n_evaluations": 0},
            {**GOOD_FIT, "converged": 1},
            {**GOOD_FIT, "method": ""},
            {k_: v for k_, v in GOOD_FIT.items() if k_ != "cost"},
            {**GOOD_FIT, "extra": 1},
        )
    ):
        with locked(match="fit result"):
            make_repo(tmp_path, PARAMS, FLAGS, fit_result=bad, name=f"badfit{k}")


def test_a_flagged_parameter_not_at_its_prior_is_refused(tmp_path, repo):
    off = TxRxParameters(tx_bandwidth_ghz=11.0)  # prior 35
    with locked(match="not at its prior"):
        make_repo(tmp_path, off, ("tx_bandwidth_ghz",), name="offprior")
    # a hand-forged record with a consistent hash is refused by the reader as well
    forged = copy.deepcopy(repo.record)
    forged["unidentifiable"] = ["bias_fraction", "tx_bandwidth_ghz"]  # PARAMS tx = 31.0, prior 35
    forged = rehash(forged)
    write_record(repo, forged)
    with locked(match="not at its prior"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, root=repo.root, plan_path=repo.plan
        )


def test_a_record_vector_that_is_not_the_vector_in_the_artefact_is_refused(repo):
    forged = copy.deepcopy(repo.record)
    forged["parameters"]["tx_bandwidth_ghz"] = 32.0
    forged = rehash(forged)
    write_record(repo, forged)
    with locked(match="not the vector inside"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, root=repo.root, plan_path=repo.plan
        )
    forged = copy.deepcopy(repo.record)
    forged["unidentifiable"] = []
    forged = rehash(forged)
    write_record(repo, forged)
    with locked(match="not the flags inside"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, root=repo.root, plan_path=repo.plan
        )


def test_the_calibration_partition_is_bound(tmp_path, repo):
    assert len(calibration_partition_sha256()) == 64
    forged = copy.deepcopy(repo.record)
    forged["calibration_partition_sha256"] = "1" * 64
    forged = rehash(forged)
    write_record(repo, forged)
    with locked(match="another calibration partition"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, root=repo.root, plan_path=repo.plan
        )
    # an artefact made on another partition cannot be bound at all
    with locked(match="another calibration partition"):
        other = tmp_path / "other"
        other.mkdir()
        from nanf_freeze_support import copy_tree

        copy_tree(other)
        git(other, "init", "-q")
        write_artifact(other, partition="2" * 64)
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "x")
        nf.build_freeze_record(ARTIFACT_REL, root=other, plan_path=other / PLAN_REL)


def test_the_partition_hash_follows_the_declared_roles():
    from opticps.measurement import nanf_import

    kept = [
        (layout.name, block.label, s.header)
        for layout in nanf_import.SHEET_LAYOUTS
        for block in layout.blocks
        for s in block.series
        if s.role is not DataRole.HOLDOUT
    ]
    assert len(kept) == 21  # Fig.1, Fig.5 and only the 6 B2B series of Fig.4
    assert sum(k[0] == "Fig.4" for k in kept) == 6


def test_a_bad_artefact_path_is_refused(repo):
    for bad in (
        "/etc/passwd",
        "docs/benchmarks/../../pyproject.toml",
        "docs\\benchmarks\\x.json",
        "src/opticps/__init__.py",
        "docs/benchmarks/x.txt",
        "docs/benchmarks//x.json",
    ):
        forged = copy.deepcopy(repo.record)
        forged["calibration"]["path"] = bad
        forged = rehash(forged)
        write_record(repo, forged)
        with locked(match="artefact must be|calibration reference"):
            nf.require_freeze(
                forged["freeze_hash"],
                record_path=repo.record_path,
                root=repo.root,
                plan_path=repo.plan,
            )


def test_a_symlinked_artefact_is_refused(repo, tmp_path):
    real = repo.root / ARTIFACT_REL
    moved = tmp_path / "moved.json"
    moved.write_bytes(real.read_bytes())
    real.unlink()
    real.symlink_to(moved)
    refuse_with(repo, "artefact is absent")


def test_git_that_cannot_run_is_a_refusal_not_a_pass(repo, monkeypatch):
    write_record(repo)

    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    with locked(match="Git could not be run"):
        nf.require_freeze(
            repo.hash, record_path=repo.record_path, plan_path=repo.plan, root=repo.root
        )


def test_a_root_that_is_not_a_repository_is_refused(repo, tmp_path):
    copy_root = tmp_path / "plain"
    import shutil

    shutil.copytree(repo.root, copy_root, ignore=shutil.ignore_patterns(".git"))
    write_record(repo)
    with locked():
        nf.require_freeze(
            repo.hash, record_path=repo.record_path, plan_path=copy_root / PLAN_REL, root=copy_root
        )


def test_the_record_is_valid_for_the_whole_chain_of_checks(repo):
    write_record(repo)
    got = nf.require_freeze(
        repo.hash, record_path=repo.record_path, plan_path=repo.plan, root=repo.root
    )
    assert got.freeze_hash == repo.hash and got.calibration_partition_sha256 == (
        calibration_partition_sha256()
    )
    assert got.plan_sha256 == nf.plan_sha256(repo.plan)


def test_the_record_size_limit_is_exactly_65536_bytes(repo):
    write_record(repo)
    raw = repo.record_path.read_bytes()
    kw = dict(record_path=repo.record_path, plan_path=repo.plan, root=repo.root)
    repo.record_path.write_bytes(raw + b" " * (nf.MAX_RECORD_BYTES - len(raw)))  # exactly the limit
    assert repo.record_path.stat().st_size == nf.MAX_RECORD_BYTES == 65_536
    assert nf.require_freeze(repo.hash, **kw)
    repo.record_path.write_bytes(raw + b" " * (nf.MAX_RECORD_BYTES + 1 - len(raw)))
    with locked(match="too large"):
        nf.require_freeze(repo.hash, **kw)


def test_the_artefact_size_limit_is_exactly_262144_bytes(repo):
    path = repo.root / ARTIFACT_REL
    raw = path.read_bytes()
    assert nf.MAX_ARTIFACT_BYTES == 262_144
    for size, ok in ((nf.MAX_ARTIFACT_BYTES, True), (nf.MAX_ARTIFACT_BYTES + 1, False)):
        path.write_bytes(raw + b" " * (size - len(raw)))
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-q", "-m", f"artefact padded to {size}")
        if ok:
            assert nf.build_freeze_record(ARTIFACT_REL, root=repo.root, plan_path=repo.plan)
        else:
            with locked(match="too large"):
                nf.build_freeze_record(ARTIFACT_REL, root=repo.root, plan_path=repo.plan)


def test_a_duplicate_key_in_the_artefact_is_refused_where_the_last_value_would_be_valid(repo):
    path = repo.root / ARTIFACT_REL
    raw = path.read_bytes().decode()
    path.write_text('{"fit_result":{},' + raw[1:])  # first fit_result empty, last one valid
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "duplicate key")
    with locked():
        nf.build_freeze_record(ARTIFACT_REL, root=repo.root, plan_path=repo.plan)
    forged = copy.deepcopy(repo.record)
    forged["calibration"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    forged["calibration"]["commit"] = git(repo.root, "rev-parse", "HEAD")
    forged = rehash(forged)
    write_record(repo, forged)
    with locked(match="malformed or cannot be verified"):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, plan_path=repo.plan, root=repo.root
        )


# --- guards reached only through a committed, hand-forged artefact (mutant survivors) ----------


def forge_with_artifact(
    repo, raw: bytes, rel: str = ARTIFACT_REL, partition=None, record_path=None
):
    """Commit `raw` at `rel`, and return a consistent record that names it (the artefact itself may
    be hostile). Only the checks of the reader can then refuse it."""
    target = repo.root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "--allow-empty", "-m", "forged artefact")
    forged = copy.deepcopy(repo.record)
    forged["calibration"] = {
        "path": record_path or rel,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "commit": git(repo.root, "rev-parse", "HEAD"),
    }
    if partition is not None:
        forged["calibration_partition_sha256"] = partition
    forged = rehash(forged)
    write_record(repo, forged)
    return forged


def read_forged(repo, forged, match):
    with locked(match=match):
        nf.require_freeze(
            forged["freeze_hash"], record_path=repo.record_path, plan_path=repo.plan, root=repo.root
        )


def good_artifact_body(repo):
    return json.loads((repo.root / ARTIFACT_REL).read_bytes())


def test_an_oversized_artefact_is_refused_by_the_reader(repo):
    raw = (repo.root / ARTIFACT_REL).read_bytes()
    forged = forge_with_artifact(repo, raw + b" " * (nf.MAX_ARTIFACT_BYTES + 1 - len(raw)))
    read_forged(repo, forged, "artefact is too large")


def test_a_partition_that_is_not_the_importers_current_one_is_refused(repo):
    body = good_artifact_body(repo)
    body["calibration_partition_sha256"] = "3" * 64
    forged = forge_with_artifact(repo, nf.canonical_json(body), partition="3" * 64)
    # record and artefact agree with each other; only the importer's partition disagrees
    read_forged(repo, forged, "partition of the importer has changed")


def test_an_artefact_outside_docs_benchmarks_or_with_dotdot_is_refused(repo):
    raw = (repo.root / ARTIFACT_REL).read_bytes()
    forged = forge_with_artifact(repo, raw, rel="elsewhere/NANF_CALIBRATION_RESULT.json")
    read_forged(repo, forged, "artefact must be")
    forged = forge_with_artifact(
        repo, raw, record_path="docs/benchmarks/../benchmarks/NANF_CALIBRATION_RESULT.json"
    )
    assert (repo.root / "docs/benchmarks/../benchmarks/NANF_CALIBRATION_RESULT.json").is_file()
    read_forged(repo, forged, "artefact must be")


def test_hostile_numbers_and_nesting_inside_the_artefact_give_holdout_locked(repo):
    body = good_artifact_body(repo)
    body["fit_result"]["cost"] = 10**400  # math.isfinite raises OverflowError on it
    forged = forge_with_artifact(repo, nf.canonical_json(body))
    read_forged(repo, forged, "malformed or cannot be verified")
    forged = forge_with_artifact(repo, b"[" * 100_000 + b"]" * 100_000)  # RecursionError
    read_forged(repo, forged, "malformed or cannot be verified")


def test_deep_nesting_in_the_record_is_reported_as_invalid_json(workbook, record_file):
    path, record = record_file
    path.write_text("[" * 30_000 + "]" * 30_000)
    with pytest.raises(NanfImportError, match="not valid JSON"):
        holdout(workbook, freeze_hash=record["freeze_hash"])
