"""Gate N3 part a: the holdout read is tied to the freeze record (plan D6, F8). Default deny.

Nothing here freezes anything: every record is built in a temporary directory, and the committed
record path is asserted to be absent.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest

from nanf_workbook_fixture import make_workbook
from opticps.measurement import nanf_freeze as nf
from opticps.measurement.nanf_chain import B4_NAMES, TxRxParameters
from opticps.measurement.nanf_import import (
    DataRole,
    NanfImportError,
    read_nanf_workbook,
)

PARAMS = TxRxParameters(
    tx_bandwidth_ghz=31.0, rx_bandwidth_ghz=42.0, thermal_noise_pa_per_rthz=21.5
)


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    return path, make_workbook(path)


@pytest.fixture
def record_file(tmp_path, monkeypatch):
    record = nf.build_freeze_record(PARAMS, unidentifiable=("bias_fraction",))
    path = tmp_path / "NANF_FREEZE_RECORD.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", path)
    return path, record


def holdout(workbook, **kw):
    path, digest = workbook
    return read_nanf_workbook(path, expected_sha256=digest, include_holdout=True, **kw)


def test_nothing_is_frozen_by_this_gate():
    assert not Path("docs/benchmarks/NANF_FREEZE_RECORD.json").exists()
    assert nf.FREEZE_RECORD_PATH.name == "NANF_FREEZE_RECORD.json"
    assert nf.FREEZE_RECORD_PATH.parent.name == "benchmarks"


def test_a_bare_include_holdout_true_is_an_error_and_no_file_is_opened(tmp_path):
    missing = tmp_path / "no-such-file.xlsx"
    with pytest.raises(NanfImportError) as err:
        read_nanf_workbook(missing, include_holdout=True)
    assert err.value.code == "HOLDOUT_LOCKED"  # not SOURCE_MISSING: the guard comes first
    assert "freeze" in str(err.value)
    assert err.value.__cause__ is None


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
    assert verified.parameters == PARAMS and verified.unidentifiable == ("bias_fraction",)


def test_a_wrong_hash_or_a_bare_flag_with_a_record_present_is_refused(workbook, record_file):
    _, record = record_file
    other = nf.build_freeze_record(TxRxParameters())["freeze_hash"]
    assert other != record["freeze_hash"]
    for h in (other, record["freeze_hash"][::-1], record["freeze_hash"].upper(), None):
        with pytest.raises(NanfImportError) as err:
            holdout(workbook, freeze_hash=h)
        assert err.value.code == "HOLDOUT_LOCKED"


def rewrite(path, edit):
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return data


def test_a_record_that_disagrees_with_its_own_hash_is_refused(workbook, record_file):
    path, record = record_file
    rewrite(path, lambda d: d["parameters"].update(tx_bandwidth_ghz=33.0))  # hash not updated
    with pytest.raises(NanfImportError, match="not consistent with its own hash"):
        holdout(workbook, freeze_hash=record["freeze_hash"])
    path.write_text(json.dumps(record))
    rewrite(path, lambda d: d.update(unidentifiable=[]))
    with pytest.raises(NanfImportError, match="own hash"):
        holdout(workbook, freeze_hash=record["freeze_hash"])


def test_a_consistent_record_with_a_changed_plan_is_refused(workbook, record_file, tmp_path):
    _, record = record_file
    plan = tmp_path / "plan.md"
    shutil.copy(nf.PLAN_PATH, plan)
    assert nf.require_freeze(record["freeze_hash"], plan_path=plan)  # an identical copy is fine
    plan.write_text(plan.read_text() + "\nAn amendment after the freeze.\n")
    with pytest.raises(nf.HoldoutLockedError, match="plan has changed"):
        nf.require_freeze(record["freeze_hash"], plan_path=plan)


def test_a_consistent_record_with_changed_code_is_refused(tmp_path):
    root = tmp_path / "repo"
    for name in nf.CODE_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(nf.ROOT / name, root / name)
    record = nf.build_freeze_record(PARAMS, root=root)
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(record))
    assert nf.require_freeze(record["freeze_hash"], record_path=path, root=root)
    changed = root / nf.CODE_FILES[1]
    changed.write_text(changed.read_text() + "\n# edited after the freeze\n")
    with pytest.raises(nf.HoldoutLockedError, match="code has changed"):
        nf.require_freeze(record["freeze_hash"], record_path=path, root=root)
    # the identity depends on every declared file and on their order
    ids = {nf.code_identity(root, nf.CODE_FILES[:k]) for k in range(1, 5)}
    assert len(ids) == 4
    assert nf.code_identity(root, nf.CODE_FILES[:2]) != nf.code_identity(root, nf.CODE_FILES[1::-1])


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


def test_a_symlinked_or_directory_record_is_refused(workbook, tmp_path, monkeypatch):
    record = nf.build_freeze_record(PARAMS)
    real = tmp_path / "real.json"
    real.write_text(json.dumps(record))
    link = tmp_path / "link.json"
    link.symlink_to(real)
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", link)
    with pytest.raises(NanfImportError, match="no freeze record"):
        holdout(workbook, freeze_hash=record["freeze_hash"])
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", tmp_path)  # a directory
    with pytest.raises(NanfImportError, match="no freeze record"):
        holdout(workbook, freeze_hash=record["freeze_hash"])


def test_the_freeze_hash_is_the_canonical_json_digest_of_the_four_content_fields():
    record = nf.build_freeze_record(PARAMS, unidentifiable=("tx_bandwidth_ghz", "bias_fraction"))
    body = {k: record[k] for k in ("plan_sha256", "code_identity", "parameters", "unidentifiable")}
    import hashlib

    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(raw).hexdigest() == record["freeze_hash"]
    assert set(record["parameters"]) == set(B4_NAMES) and len(record) == 5
    assert (
        record["plan_sha256"] == nf.plan_sha256() and record["code_identity"] == nf.code_identity()
    )
    # any change of a content field changes the hash
    for changed in (
        nf.build_freeze_record(
            TxRxParameters(
                tx_bandwidth_ghz=31.5, rx_bandwidth_ghz=42.0, thermal_noise_pa_per_rthz=21.5
            ),
            ("tx_bandwidth_ghz", "bias_fraction"),
        ),
        nf.build_freeze_record(PARAMS, ("bias_fraction", "tx_bandwidth_ghz")),  # order is content
        nf.build_freeze_record(PARAMS, ()),
    ):
        assert changed["freeze_hash"] != record["freeze_hash"]
    assert nf.compute_freeze_hash(
        "a" * 64, "b" * 64, PARAMS.as_dict(), []
    ) != nf.compute_freeze_hash("c" * 64, "b" * 64, PARAMS.as_dict(), [])
    assert nf.compute_freeze_hash(
        "a" * 64, "b" * 64, PARAMS.as_dict(), []
    ) != nf.compute_freeze_hash("a" * 64, "c" * 64, PARAMS.as_dict(), [])


def test_building_a_record_validates_the_vector_and_writes_nothing(tmp_path):
    before = sorted(p.name for p in Path("docs/benchmarks").iterdir())
    with pytest.raises(ValueError):
        nf.build_freeze_record({"tx_bandwidth_ghz": 30.0})
    with pytest.raises(ValueError):
        nf.build_freeze_record(PARAMS, unidentifiable=("chirp",))
    with pytest.raises(ValueError):
        nf.build_freeze_record(PARAMS, unidentifiable=("bias_fraction", "bias_fraction"))
    from_mapping = nf.build_freeze_record(PARAMS.as_dict())
    assert from_mapping["parameters"] == PARAMS.as_dict()
    assert sorted(p.name for p in Path("docs/benchmarks").iterdir()) == before
