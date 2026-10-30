import math

import numpy as np
import pytest

from opticps.measurement.capture import CaptureValidationError, validate_metadata
from opticps.optical_channel.fiber import (
    FIBER_PRESETS,
    ValueSource,
    apply_measurements,
    g652d_preset,
    select_fiber,
)
from opticps.optical_channel.link import (
    SPEED_OF_LIGHT,
    LinkConfig,
    beta3_s3_per_m,
    cd_null_frequency_hz,
    dispersive_field,
    fiber_metadata,
    transmit,
)


def _v10_dispersive_field(field, sample_rate, config):
    """The v1.0 implementation, kept verbatim as the reference for the default path."""
    d = config.dispersion_ps_per_nm_km * 1e-6
    beta2 = -d * config.wavelength_m**2 / (2 * np.pi * SPEED_OF_LIGHT)
    omega = 2 * np.pi * np.fft.fftfreq(field.size, d=1 / sample_rate)
    length_m = config.fiber_length_km * 1e3
    return np.fft.ifft(np.fft.fft(field) * np.exp(0.5j * beta2 * length_m * omega**2))


def _waveform():
    levels = np.array([-1, -1 / 3, 1 / 3, 1])
    return np.repeat(levels[np.random.default_rng(3).integers(0, 4, 256)], 8)


def _reference_config(**extra):
    return LinkConfig(
        fiber_length_km=20.0,
        extra_attenuation_db=10.0,
        transmitter_bandwidth_hz=12e9,
        receiver_bandwidth_hz=8e9,
        **extra,
    )


def test_default_path_matches_stored_v10_values():
    result = transmit(_waveform(), 64e9, _reference_config(), np.random.default_rng(7))
    assert result.current_a[:3] == pytest.approx(
        [8.492392738284138e-05, 9.954183253669009e-05, 0.00010996508743544548], rel=1e-12
    )
    assert result.current_a.sum() == pytest.approx(0.13032645785934457, rel=1e-12)
    assert result.received_power_w == pytest.approx(7.973542069222782e-05, rel=1e-12)
    assert result.noise_rms_a == pytest.approx(1.857827099566356e-06, rel=1e-12)


def test_default_path_equals_v10_code_bit_for_bit():
    rng = np.random.default_rng(1)
    field = rng.normal(size=4096) + 1j * rng.normal(size=4096)
    config = _reference_config()
    assert config.dispersion_slope_ps_per_nm2_km == 0.0 and config.fiber is None
    assert np.array_equal(
        dispersive_field(field, 64e9, config), _v10_dispersive_field(field, 64e9, config)
    )


def test_beta3_matches_numerical_derivative_of_beta2():
    wavelength, d0, s0 = 1550e-9, 17e-6, 56.0  # s/m^2 and s/m^3

    def beta2(omega):
        lam = 2 * np.pi * SPEED_OF_LIGHT / omega
        return -(d0 + s0 * (lam - wavelength)) * lam**2 / (2 * np.pi * SPEED_OF_LIGHT)

    omega0 = 2 * np.pi * SPEED_OF_LIGHT / wavelength
    h = omega0 * 1e-6
    numeric = (beta2(omega0 + h) - beta2(omega0 - h)) / (2 * h)
    assert beta3_s3_per_m(wavelength, d0, s0) == pytest.approx(numeric, rel=1e-6)
    # 0.127 ps^3/km, the usual order for standard single-mode fiber at 1550 nm.
    assert beta3_s3_per_m(wavelength, d0, s0) * 1e3 / 1e-36 == pytest.approx(0.1268, rel=1e-3)


def test_beta3_term_delays_a_pulse_by_half_beta3_delta_squared_l():
    """Sign check against numpy's FFT: group delay is +beta3 omega^2 L / 2 either side."""
    fs, n = 1.6e12, 1 << 15
    t = (np.arange(n) - n // 2) / fs
    delta = 2 * np.pi * 150e9
    config = LinkConfig(
        fiber_length_km=200.0,
        dispersion_ps_per_nm_km=0.0,
        dispersion_slope_ps_per_nm2_km=0.1,
        wavelength_m=1550e-9,
    )
    beta3 = beta3_s3_per_m(1550e-9, 0.0, 0.1e3)
    expected = beta3 * delta**2 * 200e3 / 2
    for sign in (+1, -1):
        pulse = np.exp(-((t / 20e-12) ** 2)) * np.exp(1j * sign * delta * t)
        out = dispersive_field(pulse, fs, config)
        power = np.abs(out) ** 2
        shift = (power * t).sum() / power.sum() - (np.abs(pulse) ** 2 * t).sum() / (
            np.abs(pulse) ** 2
        ).sum()
        assert shift == pytest.approx(expected, rel=0.02)
        assert shift > 0


def test_slope_leaves_small_signal_intensity_response_unchanged():
    n, fs = 1 << 14, 256e9
    t = np.arange(n) / fs
    f = 40 * fs / n
    field = np.sqrt(1 + 0.02 * np.cos(2 * np.pi * f * t)) + 0j
    flat = LinkConfig(fiber_length_km=5.0)
    sloped = LinkConfig(fiber_length_km=5.0, dispersion_slope_ps_per_nm2_km=0.056)

    def modulation(config):
        return np.abs(np.fft.rfft(np.abs(dispersive_field(field, fs, config)) ** 2)[40])

    assert modulation(sloped) == pytest.approx(modulation(flat), rel=2e-3)


def test_fiber_supplies_wavelength_attenuation_dispersion_and_slope():
    fiber = g652d_preset(1310)
    config = LinkConfig(fiber=fiber, attenuation_db_per_km=9.0, wavelength_m=1550e-9)
    assert config.wavelength_m == pytest.approx(1310e-9)
    assert config.attenuation_db_per_km == fiber.attenuation_db_per_km
    assert config.dispersion_ps_per_nm_km == fiber.dispersion_ps_per_nm_km
    assert config.dispersion_slope_ps_per_nm2_km == fiber.dispersion_slope_ps_per_nm2_km


def test_fiber_changes_received_power_by_its_attenuation():
    base = LinkConfig(fiber_length_km=10.0)
    fiber = LinkConfig(fiber_length_km=10.0, fiber=g652d_preset(1550))
    wave = _waveform()
    a = transmit(wave, 64e9, base, np.random.default_rng(0))
    b = transmit(wave, 64e9, fiber, np.random.default_rng(0))
    loss_db = 10 * math.log10(a.received_power_w / b.received_power_w)
    assert loss_db == pytest.approx(10 * (0.275 - 0.2), abs=0.05)


def test_null_frequency_guard_for_zero_dispersion_or_length():
    assert cd_null_frequency_hz(LinkConfig(fiber_length_km=10.0, dispersion_ps_per_nm_km=0.0)) == (
        math.inf
    )
    assert cd_null_frequency_hz(LinkConfig(fiber_length_km=0.0)) == math.inf
    finite = cd_null_frequency_hz(LinkConfig(fiber_length_km=10.0))
    assert 15e9 < finite < 25e9
    negative = cd_null_frequency_hz(LinkConfig(fiber_length_km=10.0, dispersion_ps_per_nm_km=-17.0))
    assert negative == pytest.approx(finite)


def test_zero_dispersion_with_slope_still_runs():
    config = LinkConfig(
        fiber_length_km=10.0, dispersion_ps_per_nm_km=0.0, dispersion_slope_ps_per_nm2_km=0.08
    )
    result = transmit(_waveform(), 64e9, config, np.random.default_rng(0))
    assert np.all(np.isfinite(result.current_a))


def test_link_result_records_fiber_metadata():
    config = LinkConfig(fiber_length_km=1.0, fiber=g652d_preset(1550))
    record = transmit(_waveform(), 64e9, config, np.random.default_rng(0)).fiber
    assert record is not None
    assert record["fiber_type"] == "ITU-T G.652.D"
    assert record["attenuation_source"] == "representative-simulation-value"
    assert record["units"]["attenuation"] == "dB/km"
    assert "08/2024" in record["reference"] and record["assumptions"]


def test_no_fiber_is_recorded_as_defaults_not_as_a_fiber_type():
    record = fiber_metadata(LinkConfig())
    assert record["fiber_type"].startswith("none")
    assert record["attenuation_db_per_km"] == 0.2 and record["dispersion_ps_per_nm_km"] == 17.0
    assert record["dispersion_source"] == ValueSource.DEFAULT.value


def test_measurements_override_flows_through_to_the_link():
    measured = apply_measurements(g652d_preset(1550), "Southampton log", 0.21, 16.5, 0.05)
    config = LinkConfig(fiber=measured)
    assert (config.attenuation_db_per_km, config.dispersion_ps_per_nm_km) == (0.21, 16.5)
    assert fiber_metadata(config)["attenuation_source"] == "laboratory-measured"


def test_presets_are_selectable_and_unforced():
    assert select_fiber("none") is None
    assert select_fiber("g652d-representative", 1310).wavelength_nm == 1310
    low = select_fiber("g652d-limit-low", 1550)
    high = select_fiber("g652d-limit-high", 1550)
    assert low.dispersion_ps_per_nm_km < 17.0 < high.dispersion_ps_per_nm_km
    other = select_fiber(
        "custom",
        1550,
        fiber_type="G.654.E example",
        attenuation_db_per_km=0.17,
        dispersion_ps_per_nm_km=21.0,
        dispersion_slope_ps_per_nm2_km=0.06,
        source=ValueSource.MANUFACTURER,
        reference="data sheet",
    )
    assert other.fiber_type == "G.654.E example"
    assert set(FIBER_PRESETS) == {
        "none",
        "g652d-representative",
        "g652d-limit-low",
        "g652d-limit-high",
        "custom",
    }


@pytest.mark.parametrize("name", ["g652d-typical", "g655", "G652D"])
def test_unknown_preset_rejected(name):
    with pytest.raises(ValueError):
        select_fiber(name)


@pytest.mark.parametrize("variant", ["representative", "limit-low", "limit-high"])
@pytest.mark.parametrize("wavelength", [1200.0, 1700.0])
def test_presets_refuse_wavelengths_outside_the_g652d_band(variant, wavelength):
    with pytest.raises(ValueError, match="outside"):
        select_fiber(f"g652d-{variant}", wavelength)


def _capture_metadata(**extra):
    return {
        "schema_version": "1.0",
        "capture_id": "c",
        "related_transmit_experiment_id": "e",
        "run_id": "r1",
        "split": "test",
        "data_source": "simulated",
        "capture_timestamp": "2026-01-01T00:00:00+00:00",
        "receiver_instrument_model": "x",
        "transmitter_instrument_model": "y",
        "capture_sample_rate_Sa_per_s": 64e9,
        "symbol_rate_Bd": 8e9,
        "receiver_bandwidth_Hz": 8e9,
        "fiber_length_km": 10.0,
        "attenuation_dB": 5.0,
        "optical_received_power_dBm": -10.0,
        "symbol_probabilities": [0.25] * 4,
        "units": {"time": "s", "voltage": "V"},
        **extra,
    }


def test_capture_fiber_metadata_is_optional_and_checked():
    validate_metadata(_capture_metadata())
    validate_metadata(_capture_metadata(fiber=None))
    validate_metadata(_capture_metadata(fiber=g652d_preset(1550).to_metadata()))
    with pytest.raises(CaptureValidationError, match="fiber is missing wavelength_nm"):
        validate_metadata(_capture_metadata(fiber={"fiber_type": "x"}))
    with pytest.raises(CaptureValidationError, match="fiber must be an object"):
        validate_metadata(_capture_metadata(fiber="G.652.D"))
