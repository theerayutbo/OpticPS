"""IM/DD link simulation with physical units (SI throughout, unless named otherwise).

Assumptions, kept deliberately simple:
- Single polarization, noiseless CW laser, no RIN, no optical amplifier, no Kerr effect.
- Sine-law Mach-Zehnder modulator with finite extinction.
- Linear fiber: attenuation plus chromatic dispersion as an all-pass phase, second order
  (D) and, when a dispersion slope is given, third order (S).
- Square-law photodiode; thermal noise plus level-dependent shot noise (Gaussian).

Electrical symbol energy is not optical power. Optical quantities are computed from
the field, never inferred from the centred PAM level energy.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.optical_channel.fiber import FiberParameters, ValueSource

FloatArray = NDArray[np.float64]
ELEMENTARY_CHARGE = 1.602176634e-19
SPEED_OF_LIGHT = 299_792_458.0


def dbm_to_watt(dbm: float) -> float:
    """Convert dBm to watts."""
    return 1e-3 * 10 ** (dbm / 10)


def watt_to_dbm(watt: float) -> float:
    """Convert watts to dBm."""
    if watt <= 0:
        raise ValueError(f"Power must be positive, got {watt}")
    return 10 * float(np.log10(watt / 1e-3))


@dataclass(frozen=True)
class LinkConfig:
    """Physical link parameters."""

    laser_power_w: float = 10e-3
    v_pi: float = 4.0
    drive_vpp: float = 2.0
    bias_fraction_of_vpi: float = 0.5
    extinction_db: float = 30.0
    insertion_loss_db: float = 4.0
    fiber_length_km: float = 0.0
    attenuation_db_per_km: float = 0.2
    dispersion_ps_per_nm_km: float = 17.0
    dispersion_slope_ps_per_nm2_km: float = 0.0
    wavelength_m: float = 1550e-9
    fiber: FiberParameters | None = None
    extra_attenuation_db: float = 0.0
    responsivity_a_per_w: float = 0.8
    thermal_noise_a_per_rthz: float = 20e-12
    receiver_bandwidth_hz: float = 30e9
    transmitter_bandwidth_hz: float | None = None
    include_shot_noise: bool = True
    adc_bits: int | None = None
    timing_offset_samples: float = 0.0
    predistort: bool = False

    def __post_init__(self) -> None:
        if self.fiber is not None:
            # The fiber description supplies these four values and overrides the fields above.
            fiber = self.fiber
            object.__setattr__(self, "wavelength_m", fiber.wavelength_nm * 1e-9)
            object.__setattr__(self, "attenuation_db_per_km", fiber.attenuation_db_per_km)
            object.__setattr__(self, "dispersion_ps_per_nm_km", fiber.dispersion_ps_per_nm_km)
            object.__setattr__(
                self, "dispersion_slope_ps_per_nm2_km", fiber.dispersion_slope_ps_per_nm2_km
            )
        if self.laser_power_w <= 0 or self.v_pi <= 0 or self.responsivity_a_per_w <= 0:
            raise ValueError("Laser power, V_pi and responsivity must be positive")
        if self.fiber_length_km < 0 or self.receiver_bandwidth_hz <= 0:
            raise ValueError("Fiber length must be non-negative and bandwidth positive")
        if self.drive_vpp > 2 * self.v_pi:
            raise ValueError("Drive exceeds the unambiguous range of the modulator")


def mzm_intensity(drive_v: FloatArray, config: LinkConfig) -> FloatArray:
    """Return power transmission of the modulator for a drive voltage."""
    phase = np.pi * (drive_v / config.v_pi + config.bias_fraction_of_vpi)
    visibility = 1 - 2 / (1 + 10 ** (config.extinction_db / 10))
    transmission = 0.5 * (1 - visibility * np.cos(phase))
    return transmission * 10 ** (-config.insertion_loss_db / 10)


def predistort(normalized: FloatArray, config: LinkConfig) -> FloatArray:
    """Return drive shaped by an arcsine so a quadrature MZM has equal optical spacing."""
    swing = np.sin(np.pi * config.drive_vpp / (2 * config.v_pi))
    return np.arcsin(np.clip(normalized, -1, 1) * swing) / np.pi * config.v_pi


def butterworth_magnitude(f: NDArray[np.floating], bandwidth_hz: float) -> FloatArray:
    """Return the fourth-order Butterworth magnitude response."""
    return 1 / np.sqrt(1 + (np.abs(f) / bandwidth_hz) ** 8)


def lowpass(signal: FloatArray, sample_rate: float, bandwidth_hz: float) -> FloatArray:
    """Apply a zero-phase Butterworth magnitude response, periodic in time."""
    f = np.fft.rfftfreq(signal.size, d=1 / sample_rate)
    response = butterworth_magnitude(f, bandwidth_hz)
    return np.fft.irfft(np.fft.rfft(signal) * response, n=signal.size)


def noise_power_gain(n: int, sample_rate: float, bandwidth_hz: float) -> float:
    """Return the fraction of white sampled-noise power that survives the filter."""
    f = np.fft.fftfreq(n, d=1 / sample_rate)
    return float(np.mean(butterworth_magnitude(f, bandwidth_hz) ** 2))


def beta3_s3_per_m(wavelength_m: float, dispersion_s_per_m2: float, slope_s_per_m3: float) -> float:
    """Return beta3 = (lambda^4 S + 2 lambda^3 D) / (4 pi^2 c^2) in s^3/m.

    D is in s/m^2 and S in s/m^3 (1 ps/(nm km) = 1e-6 s/m^2; 1 ps/(nm^2 km) = 1e3 s/m^3).
    """
    return (wavelength_m**4 * slope_s_per_m3 + 2 * wavelength_m**3 * dispersion_s_per_m2) / (
        4 * np.pi**2 * SPEED_OF_LIGHT**2
    )


def dispersive_field(field: NDArray[np.complex128], sample_rate: float, config: LinkConfig):
    """Apply chromatic dispersion as an all-pass phase on the optical field.

    The field is the envelope A of E = A exp(-i omega0 t), so a component with optical
    frequency offset omega acquires exp(i (beta2/2 omega^2 + beta3/6 omega^3) z). numpy's
    FFT kernel is exp(-i omega t), so numpy's frequency axis is the negative of that
    offset: the even beta2 term is unchanged and the odd beta3 term enters as
    exp(-i beta3 L omega_np^3 / 6). A zero slope selects the v1.0 second-order model
    exactly; a non-zero slope adds the full beta3, including its 2 lambda^3 D part.
    """
    d = config.dispersion_ps_per_nm_km * 1e-6  # s/m^2
    beta2 = -d * config.wavelength_m**2 / (2 * np.pi * SPEED_OF_LIGHT)
    omega = 2 * np.pi * np.fft.fftfreq(field.size, d=1 / sample_rate)
    length_m = config.fiber_length_km * 1e3
    phase = 0.5j * beta2 * length_m * omega**2
    if config.dispersion_slope_ps_per_nm2_km != 0.0:
        beta3 = beta3_s3_per_m(config.wavelength_m, d, config.dispersion_slope_ps_per_nm2_km * 1e3)
        phase = phase - 1j * beta3 * length_m * omega**3 / 6
    return np.fft.ifft(np.fft.fft(field) * np.exp(phase))


def cd_null_frequency_hz(config: LinkConfig) -> float:
    """Return the first intensity-response null of a dispersive DSB link.

    A link with no dispersion or no length has no null, so infinity is returned.
    """
    d = config.dispersion_ps_per_nm_km * 1e-6
    length_m = config.fiber_length_km * 1e3
    if d == 0 or length_m == 0:
        return math.inf
    return float(np.sqrt(SPEED_OF_LIGHT / (2 * config.wavelength_m**2 * abs(d) * length_m)))


def fiber_metadata(config: LinkConfig) -> dict[str, Any]:
    """Return the fiber description in force, with units, provenance and assumptions."""
    if config.fiber is not None:
        return config.fiber.to_metadata()
    return FiberParameters(
        "none (v1.0 defaults)",
        config.wavelength_m * 1e9,
        config.attenuation_db_per_km,
        config.dispersion_ps_per_nm_km,
        config.dispersion_slope_ps_per_nm2_km,
        ValueSource.DEFAULT,
        ValueSource.DEFAULT,
        "No fiber type selected. Simulation defaults, not a specific or standard fiber.",
        "OpticPS defaults",
    ).to_metadata()


@dataclass(frozen=True)
class LinkResult:
    """Received photocurrent and the optical quantities measured along the way."""

    current_a: FloatArray
    launch_power_w: float
    received_power_w: float
    oma_launch_w: float
    extinction_ratio_db: float
    noise_rms_a: float
    fiber: dict[str, Any] | None = None


def transmit(
    normalized: FloatArray,
    sample_rate: float,
    config: LinkConfig,
    rng: np.random.Generator,
) -> LinkResult:
    """Send a normalized [-1, 1] drive waveform through the link."""
    if normalized.size == 0 or np.abs(normalized).max() > 1 + 1e-12:
        raise ValueError("Waveform must be non-empty and normalized to [-1, 1]")
    if config.predistort:
        drive = predistort(normalized, config)
    else:
        drive = normalized * config.drive_vpp / 2
    if config.transmitter_bandwidth_hz is not None:
        drive = lowpass(drive, sample_rate, config.transmitter_bandwidth_hz)
    launched = config.laser_power_w * mzm_intensity(drive, config)
    launch_mean = float(launched.mean())
    p_max = float(config.laser_power_w * mzm_intensity(drive[np.argmax(drive)], config))
    p_min = float(config.laser_power_w * mzm_intensity(drive[np.argmin(drive)], config))

    span_db = config.fiber_length_km * config.attenuation_db_per_km + config.extra_attenuation_db
    field = np.sqrt(launched * 10 ** (-span_db / 10)) + 0j
    if config.fiber_length_km > 0:
        field = dispersive_field(field, sample_rate, config)
    optical = np.abs(field) ** 2

    current = config.responsivity_a_per_w * optical
    bandwidth = min(config.receiver_bandwidth_hz, sample_rate / 2)
    variance = np.full(current.size, config.thermal_noise_a_per_rthz**2 * sample_rate / 2)
    if config.include_shot_noise:
        variance = variance + 2 * ELEMENTARY_CHARGE * np.maximum(current, 0) * sample_rate / 2
    noisy = current + rng.normal(0.0, np.sqrt(variance))
    filtered = lowpass(noisy, sample_rate, bandwidth)

    if config.timing_offset_samples:
        f = np.fft.rfftfreq(filtered.size)
        delay = np.exp(-2j * np.pi * f * config.timing_offset_samples)
        filtered = np.fft.irfft(np.fft.rfft(filtered) * delay, n=filtered.size)
    if config.adc_bits is not None:
        low, high = float(filtered.min()), float(filtered.max())
        steps = 2**config.adc_bits - 1
        filtered = low + np.round((filtered - low) / (high - low) * steps) / steps * (high - low)

    return LinkResult(
        current_a=filtered,
        launch_power_w=launch_mean,
        received_power_w=float(optical.mean()),
        oma_launch_w=p_max - p_min,
        extinction_ratio_db=10 * float(np.log10(p_max / p_min)),
        noise_rms_a=float(
            np.sqrt(variance.mean() * noise_power_gain(current.size, sample_rate, bandwidth))
        ),
        fiber=fiber_metadata(config),
    )
