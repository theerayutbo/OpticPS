import copy
import json
from pathlib import Path

import numpy as np
import pytest

from opticps.instruments.mock_receiver import capture_waveform
from opticps.measurement.capture import (
    Capture,
    CaptureValidationError,
    load_capture,
    load_reference,
    read_samples,
    validate_metadata,
)
from opticps.measurement.compare import (
    analyze_directory,
    fairness_audit,
    match_uniform_rate,
)
from opticps.optical_channel.link import LinkConfig
from opticps.optimization.adaptive import DataLeakageError

ROOT = Path("output/keysight_m8199b")
PROFILE = "B_highspeed_56GBd"


def good():
    return {
        "schema_version": "1.0",
        "capture_id": "c1",
        "related_transmit_experiment_id": "e",
        "run_id": "r1",
        "split": "test",
        "data_source": "measured",
        "capture_timestamp": "2026-11-01T10:00:00+00:00",
        "receiver_instrument_model": "unknown-model",
        "transmitter_instrument_model": "Keysight M8199B",
        "capture_sample_rate_Sa_per_s": 80e9,
        "symbol_rate_Bd": 8e9,
        "receiver_bandwidth_Hz": 30e9,
        "fiber_length_km": 0,
        "attenuation_dB": 10,
        "optical_received_power_dBm": -10,
        "symbol_probabilities": [0.25, 0.25, 0.25, 0.25],
        "units": {"time": "s", "voltage": "V"},
    }


def test_valid_metadata_accepted():
    validate_metadata(good())


@pytest.mark.parametrize(
    "field,value,word",
    [
        ("capture_id", None, "missing"),
        ("units", {"time": "ms", "voltage": "V"}, "units"),
        ("capture_sample_rate_Sa_per_s", 10e9, "two samples"),
        ("symbol_probabilities", [0.5, 0.6, 0.1, 0.1], "probabilities"),
        ("schema_version", "9.9", "version"),
        ("split", "both", "split"),
        ("data_source", "guessed", "data_source"),
        ("capture_timestamp", "yesterday", "ISO"),
        ("fiber_length_km", -1, "non-negative"),
        ("optical_received_power_dBm", 90, "plausible"),
        ("receiver_bandwidth_Hz", 900e9, "exceeds"),
        ("symbol_rate_Bd", "fast", "wrong type"),
    ],
)
def test_bad_metadata_rejected(field, value, word):
    metadata = good()
    metadata[field] = value
    with pytest.raises(CaptureValidationError, match=word):
        validate_metadata(metadata)


def test_contradictory_power_rejected():
    metadata = good()
    metadata["optical_launch_power_dBm"] = -20
    with pytest.raises(CaptureValidationError, match="exceeds launch"):
        validate_metadata(metadata)


def test_fuzzed_metadata_never_passes_silently():
    rng = np.random.default_rng(0)
    base = good()
    keys = list(base)
    for _ in range(200):
        metadata = copy.deepcopy(base)
        del metadata[keys[rng.integers(len(keys))]]
        with pytest.raises(CaptureValidationError):
            validate_metadata(metadata)


def test_time_axis_mismatch_rejected(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("received_time_s,received_voltage_v\n0,1\n1,2\n2,3\n")
    with pytest.raises(CaptureValidationError, match="Time axis"):
        read_samples(path, good())


def test_unknown_columns_and_nan_rejected(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("t,v\n0,1\n")
    with pytest.raises(CaptureValidationError, match="columns"):
        read_samples(path, good())
    path.write_text("sample_index,received_voltage_v\n0,nan\n")
    with pytest.raises(CaptureValidationError, match="non-finite"):
        read_samples(path, good())


def test_rate_matching_reports_baud_change():
    match = match_uniform_rate(14.9375e9, 8e9, 32768, 28)
    assert match.feasible
    assert match.uniform_symbol_rate == pytest.approx(7.46875e9)
    assert 200e9 <= match.sample_rate <= 256e9
    assert "lowered" in match.reason


def test_rate_matching_marks_infeasible():
    assert not match_uniform_rate(1e9, 8e9, 65535, 28).feasible


def test_fairness_audit_flags_uncontrolled_and_missing():
    a, b = good(), good()
    b["optical_received_power_dBm"] = -9
    rows = {
        r["variable"]: r["status"]
        for r in fairness_audit([Capture(a, np.zeros(1)), Capture(b, np.zeros(1))])
    }
    assert rows["Optical received power"] == "uncontrolled"
    assert rows["Symbol rate"] == "controlled"
    assert rows["Optical launch power"] == "not recorded"


@pytest.fixture(scope="module")
def manifest():
    import csv

    with (ROOT / PROFILE / "experiment_manifest.csv").open() as handle:
        return {Path(r["waveform_filename"]).stem: r for r in csv.DictReader(handle)}


def link():
    return LinkConfig(extra_attenuation_db=9.0, receiver_bandwidth_hz=42e9)


def make(manifest, name, run, split, folder, seed, **kwargs):
    row = manifest[name]
    probabilities = [
        float(row[f"realised_probability_{k}"]) for k in ("minus3", "minus1", "plus1", "plus3")
    ]
    return capture_waveform(
        ROOT / PROFILE / row["waveform_filename"],
        224e9,
        56e9,
        row["experiment_id"],
        probabilities,
        f"{name}-{run}-{split}",
        run,
        split,
        folder,
        link(),
        capture_sample_rate=160e9,
        seed=seed,
        **kwargs,
    )


@pytest.mark.slow
def test_mock_receiver_end_to_end(manifest, tmp_path):
    for seed, run in enumerate(("r1", "r2", "r3")):
        for name in ("PAM4_Uniform", "PAM4_Fixed_PS70"):
            make(manifest, name, run, "test", tmp_path, seed, time_axis=seed == 0)
    summary = analyze_directory(tmp_path, ROOT, PROFILE, tmp_path / "out")
    assert summary["data_sources"] == ["simulated"]
    assert summary["test_captures"] == 6
    assert summary["comparisons"][0]["runs"] == 3
    metrics = (tmp_path / "out" / "capture_metrics.csv").read_text().splitlines()
    assert len(metrics) == 7
    capture = load_capture(tmp_path / "PAM4_Uniform-r1-test.json")
    assert capture.samples.size == round(262144 * 160 / 224)
    frame = load_reference(ROOT / PROFILE / "references" / "PAM4_Fixed_PS70", "PAM4_Fixed_PS70")
    assert frame.indices.size == 65536 and frame.n_blocks == 63


def test_training_only_data_not_reported_as_test(manifest, tmp_path):
    make(manifest, "PAM4_Uniform", "r1", "training", tmp_path, 1)
    summary = analyze_directory(tmp_path, ROOT, PROFILE, tmp_path / "out")
    assert summary["test_captures"] == 0
    assert summary["training_captures"] == 1
    assert 0.05 <= summary["adaptive_from_training"]["p_outer"] <= 0.5


def test_same_capture_in_both_splits_rejected(manifest, tmp_path):
    first = make(manifest, "PAM4_Uniform", "r1", "training", tmp_path, 1)
    metadata = json.loads(first.metadata_path.read_text())
    metadata["split"] = "test"
    clone = tmp_path / "clone.json"
    clone.write_text(json.dumps(metadata))
    (tmp_path / "clone.csv").write_text(first.data_path.read_text())
    with pytest.raises(DataLeakageError):
        analyze_directory(tmp_path, ROOT, PROFILE, tmp_path / "out")
