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
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.optical_channel.fiber import (
    FiberParameters,
    FiberProfile,
    FiberProfileError,
    MissingFiberPropertyError,
    ResolvedFiber,
    SensitivityScenario,
    UnsupportedEffectError,
    ValueSource,
    resolve_profile,
)

FloatArray = NDArray[np.float64]
ELEMENTARY_CHARGE = 1.602176634e-19
SPEED_OF_LIGHT = 299_792_458.0
# The v1.0 link values, used for any fiber field left unset and no fiber description.
DEFAULT_WAVELENGTH_M = 1550e-9
DEFAULT_ATTENUATION_DB_PER_KM = 0.2
DEFAULT_DISPERSION_PS_PER_NM_KM = 17.0


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
    """Physical link parameters.

    The four fiber fields (wavelength_m, attenuation_db_per_km, dispersion_ps_per_nm_km and
    dispersion_slope_ps_per_nm2_km) hold what the caller gave, and None means unset. Use the
    effective_* properties for the value in force: the fiber description when there is one,
    else the given value, else the v1.0 default. A field that disagrees with the fiber
    description raises, so no value is silently dropped, and dataclasses.replace is safe
    because nothing resolved is written back into the fields. An unset slope is the v1.0
    second-order model; 0.0 is a true zero slope, whose beta3 still comes from D.
    """

    laser_power_w: float = 10e-3
    v_pi: float = 4.0
    drive_vpp: float = 2.0
    bias_fraction_of_vpi: float = 0.5
    extinction_db: float = 30.0
    insertion_loss_db: float = 4.0
    fiber_length_km: float = 0.0
    attenuation_db_per_km: float | None = None
    dispersion_ps_per_nm_km: float | None = None
    dispersion_slope_ps_per_nm2_km: float | None = None
    wavelength_m: float | None = None
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
            supplied = {
                "wavelength_m": self.fiber.wavelength_nm * 1e-9,
                "attenuation_db_per_km": self.fiber.attenuation_db_per_km,
                "dispersion_ps_per_nm_km": self.fiber.dispersion_ps_per_nm_km,
                "dispersion_slope_ps_per_nm2_km": self.fiber.dispersion_slope_ps_per_nm2_km,
            }
            for name, value in supplied.items():
                given = getattr(self, name)
                if given is not None and not math.isclose(given, value, rel_tol=1e-9):
                    raise ValueError(
                        f"{name}={given!r} conflicts with fiber {self.fiber.fiber_type!r} "
                        f"({value!r}); leave it unset or change the fiber description"
                    )
        if self.laser_power_w <= 0 or self.v_pi <= 0 or self.responsivity_a_per_w <= 0:
            raise ValueError("Laser power, V_pi and responsivity must be positive")
        if self.fiber_length_km < 0 or self.receiver_bandwidth_hz <= 0:
            raise ValueError("Fiber length must be non-negative and bandwidth positive")
        if self.drive_vpp > 2 * self.v_pi:
            raise ValueError("Drive exceeds the unambiguous range of the modulator")

    @property
    def effective_wavelength_m(self) -> float:
        """Return the laser wavelength in force, in metres."""
        if self.fiber is not None:
            return self.fiber.wavelength_nm * 1e-9
        return DEFAULT_WAVELENGTH_M if self.wavelength_m is None else self.wavelength_m

    @property
    def effective_attenuation_db_per_km(self) -> float:
        """Return the fiber attenuation in force, in dB/km."""
        if self.fiber is not None:
            return self.fiber.attenuation_db_per_km
        if self.attenuation_db_per_km is None:
            return DEFAULT_ATTENUATION_DB_PER_KM
        return self.attenuation_db_per_km

    @property
    def effective_dispersion_ps_per_nm_km(self) -> float:
        """Return D in force, in ps/(nm km)."""
        if self.fiber is not None:
            return self.fiber.dispersion_ps_per_nm_km
        if self.dispersion_ps_per_nm_km is None:
            return DEFAULT_DISPERSION_PS_PER_NM_KM
        return self.dispersion_ps_per_nm_km

    @property
    def effective_slope_ps_per_nm2_km(self) -> float | None:
        """Return S in force, in ps/(nm^2 km); None selects the second-order v1.0 model."""
        if self.fiber is not None:
            return self.fiber.dispersion_slope_ps_per_nm2_km
        return self.dispersion_slope_ps_per_nm2_km


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
    exp(-i beta3 L omega_np^3 / 6). An unset slope (None) selects the v1.0 second-order model
    exactly. Any given slope, including 0.0, adds the full beta3, including its
    2 lambda^3 D part, so 0.0 is a true zero slope and not the v1.0 path.
    """
    d = config.effective_dispersion_ps_per_nm_km * 1e-6  # s/m^2
    wavelength_m = config.effective_wavelength_m
    slope = config.effective_slope_ps_per_nm2_km
    beta2 = -d * wavelength_m**2 / (2 * np.pi * SPEED_OF_LIGHT)
    omega = 2 * np.pi * np.fft.fftfreq(field.size, d=1 / sample_rate)
    length_m = config.fiber_length_km * 1e3
    phase = 0.5j * beta2 * length_m * omega**2
    if slope is not None:
        beta3 = beta3_s3_per_m(wavelength_m, d, slope * 1e3)
        phase = phase - 1j * beta3 * length_m * omega**3 / 6
    return np.fft.ifft(np.fft.fft(field) * np.exp(phase))


def cd_null_frequency_hz(config: LinkConfig) -> float:
    """Return the first intensity-response null of a dispersive DSB link.

    A link with no dispersion or no length has no null, so infinity is returned.
    """
    d = config.effective_dispersion_ps_per_nm_km * 1e-6
    length_m = config.fiber_length_km * 1e3
    if d == 0 or length_m == 0:
        return math.inf
    return float(
        np.sqrt(SPEED_OF_LIGHT / (2 * config.effective_wavelength_m**2 * abs(d) * length_m))
    )


def fiber_metadata(config: LinkConfig) -> dict[str, Any]:
    """Return the fiber description in force, with units, provenance and assumptions.

    Without a fiber description each value is tagged by where it came from: the v1.0 default
    when unset, user-specified when the caller gave it. An unset slope is recorded as None,
    meaning the second-order model with no third-order term.
    """

    def source(given: float | None) -> ValueSource:
        return ValueSource.DEFAULT if given is None else ValueSource.USER_SPECIFIED

    if config.fiber is not None:
        record = config.fiber.to_metadata()
    else:
        given = (
            config.wavelength_m,
            config.attenuation_db_per_km,
            config.dispersion_ps_per_nm_km,
            config.dispersion_slope_ps_per_nm2_km,
        )
        all_default = all(v is None for v in given)
        slope = config.effective_slope_ps_per_nm2_km
        record = FiberParameters(
            "none (v1.0 defaults)" if all_default else "none (user-specified link values)",
            config.effective_wavelength_m * 1e9,
            config.effective_attenuation_db_per_km,
            config.effective_dispersion_ps_per_nm_km,
            0.0 if slope is None else slope,
            source(config.attenuation_db_per_km),
            source(config.dispersion_ps_per_nm_km),
            source(config.dispersion_slope_ps_per_nm2_km),
            "No fiber type selected. "
            + (
                "Simulation defaults, not a specific or standard fiber."
                if all_default
                else "Values not given by the caller are simulation defaults; the rest are "
                "user-specified. Neither is a specific or standard fiber."
            )
            + (" No dispersion slope: second-order dispersion only." if slope is None else ""),
            "OpticPS defaults" if all_default else "OpticPS defaults and user-specified values",
        ).to_metadata()
        if slope is None:
            record["dispersion_slope_ps_per_nm2_km"] = None
    record["fiber_length_km"] = config.fiber_length_km
    return record


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

    span_db = (
        config.fiber_length_km * config.effective_attenuation_db_per_km
        + config.extra_attenuation_db
    )
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


# ---------------------------------------------------------------------------------------------
# Profile-driven propagation (NANF workstream, Gate N1)
#
# The validated functions above are unchanged and are the ones that run. A resolved profile is
# turned into an ordinary LinkConfig, so the coherent field, the all-pass dispersion and the
# square-law detection are the same code as for G.652.D.
#
# Governing equations (derived here from the wave equation, not taken from a simulator):
#   envelope A(z, t) with E = A exp(-i omega0 t); a component at optical offset omega obeys
#   dA/dz = -(alpha/2) A + i (beta2/2 omega^2 + beta3/6 omega^3) A, alpha the power
#   attenuation coefficient. Over a length L: amplitude factor 10^(-alpha_dB L / 20) and phase
#   exp(i (beta2/2 omega^2 + beta3/6 omega^3) L). Power falls as 10^(-alpha_dB L / 10).
#   D = d(1/v_g)/d(lambda) = -(2 pi c / lambda^2) beta2  =>  beta2 = -D lambda^2 / (2 pi c).
#   S = dD/d(lambda). With beta2(omega) = -D(lambda) lambda^2 / (2 pi c), lambda = 2 pi c / omega,
#   d lambda / d omega = -lambda^2 / (2 pi c), beta3 = d beta2 / d omega gives
#   beta3 = (lambda^4 S + 2 lambda^3 D) / (4 pi^2 c^2).
#   Group delay of the carrier: tau = n_g L / c.
# Lumped losses (connector, pigtail, splice) are summed once and applied as a power loss.
# ---------------------------------------------------------------------------------------------


def beta2_s2_per_m(wavelength_m: float, dispersion_s_per_m2: float) -> float:
    """Return beta2 = -D lambda^2 / (2 pi c) in s^2/m, D in s/m^2 (1 ps/(nm km) = 1e-6 s/m^2)."""
    return -dispersion_s_per_m2 * wavelength_m**2 / (2 * np.pi * SPEED_OF_LIGHT)


class PowerProtocol(StrEnum):
    """How the optical power is set when a link is simulated."""

    FIXED_LAUNCH = "fixed-launch-power"
    MATCHED_RECEIVED = "matched-received-power"


def profile_link_config(resolved: ResolvedFiber, base: LinkConfig | None = None) -> LinkConfig:
    """Return a LinkConfig carrying a resolved profile; lumped losses are added exactly once.

    The base config must not carry a G.652.D fiber description or fiber fields of its own, so
    nothing of the profile is overridden or doubled. Its extra_attenuation_db (for example a
    deliberate attenuator) is kept and the profile's lumped losses are added to it.
    """
    base = LinkConfig() if base is None else base
    if (
        base.fiber is not None
        or base.fiber_length_km != 0.0
        or any(
            v is not None
            for v in (
                base.attenuation_db_per_km,
                base.dispersion_ps_per_nm_km,
                base.dispersion_slope_ps_per_nm2_km,
                base.wavelength_m,
            )
        )
    ):
        raise FiberProfileError(
            "the base LinkConfig already describes a fiber; leave fiber, length and fiber "
            "fields unset"
        )
    return replace(
        base,
        fiber_length_km=resolved.length_km,
        attenuation_db_per_km=resolved.attenuation_db_per_km,
        dispersion_ps_per_nm_km=resolved.dispersion_ps_per_nm_km,
        dispersion_slope_ps_per_nm2_km=resolved.dispersion_slope_ps_per_nm2_km,
        wavelength_m=resolved.wavelength_nm * 1e-9,
        extra_attenuation_db=base.extra_attenuation_db + resolved.lumped_loss_db,
    )


def span_loss_db(config: LinkConfig) -> float:
    """Return the optical loss of the span in dB: distributed attenuation plus lumped extra."""
    return (
        config.fiber_length_km * config.effective_attenuation_db_per_km
        + config.extra_attenuation_db
    )


def propagate_profile_field(
    field: NDArray[np.complex128], sample_rate: float, resolved: ResolvedFiber
) -> NDArray[np.complex128]:
    """Propagate a complex optical envelope through a resolved profile.

    Power is attenuated by 10^(-total/10), that is the amplitude by 10^(-total/20), then the
    all-pass dispersion of `dispersive_field` is applied. Square-law detection is the caller's
    step, so the coherent field is kept until then.
    """
    config = profile_link_config(resolved)
    out = field * 10 ** (-span_loss_db(config) / 20)
    if config.fiber_length_km > 0:
        out = dispersive_field(out, sample_rate, config)
    return np.asarray(out, dtype=np.complex128)


def group_delay_s(resolved: ResolvedFiber) -> float:
    """Return the carrier group delay n_g L / c in seconds; the group index must be known."""
    if resolved.group_index is None:
        raise MissingFiberPropertyError(
            f"profile {resolved.profile_id!r} has no group index; none is assumed"
        )
    return resolved.group_index * resolved.length_km * 1e3 / SPEED_OF_LIGHT


def launch_mean_per_watt(normalized: FloatArray, sample_rate: float, config: LinkConfig) -> float:
    """Return mean launched optical power for 1 W laser power (modulator and filters only).

    Same drive path as `transmit`: optional predistortion, optional transmitter filter, then
    the modulator law.
    """
    if config.predistort:
        drive = predistort(normalized, config)
    else:
        drive = normalized * config.drive_vpp / 2
    if config.transmitter_bandwidth_hz is not None:
        drive = lowpass(drive, sample_rate, config.transmitter_bandwidth_hz)
    return float(mzm_intensity(drive, config).mean())


@dataclass(frozen=True)
class ProfileLinkResult:
    """A link result with the resolved profile, protocol and the config that produced it."""

    link: LinkResult
    resolved: ResolvedFiber
    protocol: PowerProtocol
    config: LinkConfig


def transmit_profile(
    normalized: FloatArray,
    sample_rate: float,
    profile: FiberProfile,
    wavelength_nm: float,
    rng: np.random.Generator,
    *,
    base: LinkConfig | None = None,
    protocol: PowerProtocol = PowerProtocol.FIXED_LAUNCH,
    received_power_dbm: float | None = None,
    scenario: SensitivityScenario | None = None,
    allow_extrapolation: bool = False,
    effects: tuple[str, ...] = (),
) -> ProfileLinkResult:
    """Send a waveform through a profiled fiber with one of two power protocols.

    fixed-launch-power: the base config's laser power is used; the received power follows from
    the loss. matched-received-power: the laser power is set so the mean received optical power
    equals `received_power_dbm` whatever the loss (the compensation is a pure gain, so the
    waveform and noise statistics match a variable attenuator at the receiver). Effects the model
    does not implement raise, as do unknown profile values (unless a labelled scenario fills them).
    """
    if effects:
        raise UnsupportedEffectError(f"effects {tuple(effects)} are not implemented")
    resolved = resolve_profile(
        profile, wavelength_nm, scenario=scenario, allow_extrapolation=allow_extrapolation
    )
    config = profile_link_config(resolved, base)
    protocol = PowerProtocol(protocol)
    if protocol is PowerProtocol.MATCHED_RECEIVED:
        if received_power_dbm is None:
            raise ValueError("matched-received-power needs received_power_dbm")
        mean_unit = launch_mean_per_watt(normalized, sample_rate, config)
        target_w = dbm_to_watt(received_power_dbm)
        laser_w = target_w / (mean_unit * 10 ** (-span_loss_db(config) / 10))
        config = replace(config, laser_power_w=laser_w)
    elif received_power_dbm is not None:
        raise ValueError("received_power_dbm is only used by matched-received-power")
    result = transmit(normalized, sample_rate, config, rng)
    record = resolved.to_record()
    record["power_protocol"] = protocol.value
    return ProfileLinkResult(replace(result, fiber=record), resolved, protocol, config)
