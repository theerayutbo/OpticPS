import csv
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.instruments.m8199b import (
    M8199BConstraintError,
    MockM8199BAdapter,
    Profile,
    import_command,
)
from opticps.measurement.validate_export import validate_profile
from opticps.optimization.adaptive import (
    DataLeakageError,
    assert_disjoint,
    select_distribution,
    simulate_training_capture,
)
from opticps.shaping.distributions import PS70, UNIFORM
from opticps.transmitter.export import (
    dac_quantize,
    full_scale,
    generate_all,
    sha256_file,
    synthesize,
)
from opticps.transmitter.frame import build_frame
from opticps.transmitter.pulse import PulseConfig, peak_factor, shape

CONFIG = Path("configs/m8199b_profiles.yaml")


@pytest.fixture(scope="module")
def small_output(tmp_path_factory):
    """Generate the two real profiles once for the whole module."""
    root = tmp_path_factory.mktemp("out")
    config = yaml.safe_load(CONFIG.read_text())
    config["common"]["adaptive"]["training_samples"] = 50000
    config["common"]["adaptive"]["grid_step"] = 0.02
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    generate_all(path, root / "a")
    generate_all(path, root / "b")
    return root


def test_profile_arithmetic():
    a = Profile("a", 224e9, 8e9, 32768)
    b = Profile("b", 224e9, 56e9, 65536)
    assert (a.sps, a.samples) == (28, 917504)
    assert (b.sps, b.samples) == (4, 262144)
    assert a.samples % 512 == 0 and b.samples % 512 == 0
    assert a.duration_s == pytest.approx(4.096e-6)
    a.check()
    b.check()


@pytest.mark.parametrize(
    "profile",
    [
        Profile("low", 100e9, 25e9, 65536),
        Profile("gran", 224e9, 56e9, 65535),
        Profile("long", 224e9, 8e9, 65536),
    ],
)
def test_invalid_profiles_rejected(profile):
    with pytest.raises(M8199BConstraintError):
        profile.check()


def test_non_integer_sps_rejected():
    with pytest.raises(M8199BConstraintError):
        Profile("x", 224e9, 9e9, 32768).sps


def test_import_command_text_and_no_output_without_confirmation():
    assert import_command("M2", "DataOut1", 1, r"C:\OpticPS\a.csv") == (
        ":TRAC:IMP 'M2.DataOut1', 1, \"C:\\OpticPS\\a.csv\", CSV"
    )
    adapter = MockM8199BAdapter()
    adapter.load(262144, 224e9)
    with pytest.raises(PermissionError):
        adapter.enable_output()
    assert not adapter.output_enabled


def test_nrz_levels_are_exact():
    frame = build_frame("x", UNIFORM, 32768, 42, direct_uniform=True)
    samples = synthesize(frame, 4, PulseConfig(), 9)
    assert set(np.unique(samples)) == {-1.0, -0.333333333, 0.333333333, 1.0}


@pytest.mark.parametrize("roll_off", [0.2, 0.35, 1.0])
def test_rrc_stays_inside_full_scale(roll_off):
    pulse = PulseConfig("rrc", roll_off)
    frame = build_frame("x", PS70, 32768, 42)
    samples = synthesize(frame, 4, pulse, 9)
    assert samples.size == 32768 * 4
    assert 0.5 < np.abs(samples).max() <= 1.0
    assert full_scale(4, pulse) == pytest.approx(3 * peak_factor(4, pulse))


def test_rrc_circular_has_no_seam_and_matched_filter_is_nyquist():
    frame = build_frame("x", UNIFORM, 32768, 1, direct_uniform=True)
    levels = np.array([-3.0, -1, 1, 3])[frame.indices]
    pulse = PulseConfig("rrc", 0.35)
    wave = shape(levels, 8, pulse)
    twice = shape(np.concatenate([levels, levels]), 8, pulse)
    assert np.allclose(wave, twice[: wave.size], atol=1e-6)
    from opticps.transmitter.pulse import rrc_frequency_response

    filtered = np.fft.ifft(
        np.fft.fft(wave) * rrc_frequency_response(wave.size, 8, 0.35)
    ).real[::8]
    assert np.max(np.abs(filtered - levels)) < 1e-6


def test_dac_quantization_is_declared_and_bounded():
    quantized = dac_quantize(np.array([-1.0, 0.333333333, 1.0]))
    assert quantized[0] == -1 and quantized[2] == 1
    assert abs(quantized[1] - 1 / 3) <= 1 / 127


def test_generated_profiles_validate_and_reproduce(small_output):
    for profile, count in (("A_initial_8GBd", 917504), ("B_highspeed_56GBd", 262144)):
        folder = small_output / "a" / profile
        results = validate_profile(folder)
        assert results and all(r.passed for r in results), [r for r in results if not r.passed]
        waves = sorted(folder.glob("waveforms/**/*.csv"))
        assert len(waves) == 5
        for wave in waves:
            assert wave.open().readline() == "DataOut1\n"
            assert sum(1 for _ in wave.open()) == count + 1
            twin = small_output / "b" / wave.relative_to(small_output / "a")
            assert sha256_file(wave) == sha256_file(twin)


def _break(folder: Path, mutate) -> list:
    target = folder / "waveforms" / "PAM4_Uniform.csv"
    lines = target.read_text().split("\n")
    mutate(lines)
    target.write_text("\n".join(lines))
    return [r for r in validate_profile(folder) if not r.passed]


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda s: s.__setitem__(0, "Sample"), "header_exact"),
        (lambda s: s.__setitem__(5, "nan"), "all_finite"),
        (lambda s: s.__setitem__(5, "1.5"), "range_within_unit"),
        (lambda s: s.__delitem__(5), "sample_count"),
        (lambda s: s.__setitem__(5, "0.1,0.2"), "csv_parse"),
        (lambda s: s.__setitem__(600, "0.123456789"), "waveform_sha256"),
    ],
)
def test_validator_rejects_corruption(small_output, tmp_path, mutate, expected):
    folder = tmp_path / "p"
    shutil.copytree(small_output / "a" / "B_highspeed_56GBd", folder)
    failures = {r.check for r in _break(folder, mutate)}
    assert expected in failures


def test_manifest_records_lower_rate_for_shaping(small_output):
    with (small_output / "a" / "A_initial_8GBd" / "experiment_manifest.csv").open() as handle:
        rows = {Path(r["waveform_filename"]).stem: r for r in csv.DictReader(handle)}
    rate = {k: float(v["actual_net_payload_rate_bps"]) for k, v in rows.items()}
    assert rate["PAM4_Uniform"] > rate["PAM4_Fixed_PS70"] > rate["PAM4_Fixed_PS80"]
    assert rate["PAM4_Uniform"] == pytest.approx(2 * 31744 / 4.096e-6)
    assert rate["PAM4_Fixed_PS70"] == pytest.approx(rate["PAM4_Fixed_Outer70"])
    assert rows["PAM4_Adaptive"]["shaping_mode"] == "adaptive-simulation-optimized"
    assert rows["PAM4_Adaptive"]["measured_or_simulated_source"] == "simulated"


def test_all_waveforms_share_level_scale(small_output):
    with (small_output / "a" / "A_initial_8GBd" / "experiment_manifest.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len({r["amplitude_scale"] for r in rows}) == 1
    assert len({r["waveform_peak"] for r in rows}) == 1
    assert len({r["waveform_rms"] for r in rows}) == 5


def test_adaptive_prefers_outer_heavy_at_low_snr_and_uniform_at_high_snr():
    low = select_distribution(*simulate_training_capture(13.85, 200000, 3), "sim", grid_step=0.01)
    high = select_distribution(*simulate_training_capture(30.0, 200000, 3), "sim", grid_step=0.01)
    assert 0.33 <= low.p_outer <= 0.41
    assert high.p_outer == pytest.approx(0.25, abs=0.02)
    assert len(low.candidates) > 40


def test_leakage_guard():
    assert_disjoint(["train-1"], ["test-1"])
    with pytest.raises(DataLeakageError):
        assert_disjoint(["train-1", "shared"], ["shared"])
