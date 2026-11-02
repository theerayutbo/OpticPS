"""NANF benchmark, Gate N3 part a: the simulation chain, on synthetic data only (LITERATURE
BENCHMARK / CALIBRATION ONLY).

One function, `simulate_point`, maps PAM4 symbols to a BER and an SNR for one operating point:

    PAM4 symbols -> SRRC shaping (roll-off 0.1, plan F4) on the 70 GSa/s AWG grid -> 8-bit DAC ->
    ideal band-limited up-sampling to the 280 GSa/s analogue grid -> Tx low-pass -> existing
    sine-law Mach-Zehnder modulator -> existing profile propagation (all-pass dispersion and
    loss) -> square-law detection -> shot and thermal noise -> Rx low-pass -> ideal band-limited
    resampling to the 80 GSa/s scope -> white electrical SNR ceiling -> exact rational resampling to
    2 samples per symbol -> SRRC matched filter -> T/2 (17, 7) RLS DFE -> bit-error counting.

Every choice that the paper does not state is declared in plan Amendment 5 (F1, F4, F6) with a
label; this module follows that text. Nothing here is fitted, and no holdout series is read: the
module takes no workbook. Governing equations are the textbook ones named in
`docs/ALGORITHM_PROVENANCE.md`; no simulator code was consulted.

The symbol count must be a multiple of 140 (F1) so that every resampling step has an exact integer
output length; a length that is not is refused, never rounded.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from opticps.modulation.pam import label_bits, pam_levels
from opticps.optical_channel.fiber import FiberProfile, ResolvedFiber, resolve_profile
from opticps.optical_channel.link import (
    ELEMENTARY_CHARGE,
    MAX_MATCHED_LASER_POWER_W,
    LinkConfig,
    check_matched_received_power_dbm,
    dbm_to_watt,
    lowpass,
    mzm_intensity,
    profile_link_config,
    propagate_profile_field,
    span_loss_db,
    watt_to_dbm,
)
from opticps.receiver.dfe import (
    PINNED_P_TRACE_CAP,
    DfeResult,
    RlsDfeConfig,
    RlsInstabilityError,
    rls_equalize,
)
from opticps.transmitter.pulse import rrc_frequency_response

if TYPE_CHECKING:  # nanf_freeze imports this module, so it is imported lazily at run time
    from opticps.measurement.nanf_freeze import FreezeRecord

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

SYMBOL_SEED = 20261101
NOISE_SEED_TAG = 7919
AWG_RATE_HZ = 70_000_000_000
ANALOGUE_RATE_HZ = 280_000_000_000
SCOPE_RATE_HZ = 80_000_000_000
# paper Sec. III-B (manuscript p.4): "The roll-off factor of the SRRC filter was 0.1"
SRRC_ROLL_OFF = 0.1
DAC_BITS = 8
TRAINING_SYMBOLS = 8192
GRID_MULTIPLE = 140  # lcm(4, 5, 7), plan F1
CAPTURE_SYMBOLS = 655_200  # 140 x 4680, plan F1
BER_CENSOR_FLOOR = 1e-5  # plan A3
BER_REPORT_FLOOR = 1e-4  # plan F2: a simulated BER below this is reported as "below 1e-4"
RESPONSIVITY_A_PER_W = 0.8  # plan D2, passed explicitly
EXTINCTION_DB = 30.0  # plan F4.5 (repository default)
V_PI = 4.0  # volts; modulation depth and bias are relative to it
# bit rate (Gb/s) -> symbol rate (GBd): PAM4 carries 2 bits per symbol
BAUD_GBD = {80: 40, 100: 50, 112: 56}


class ChainGridError(ValueError):
    """The sample grid does not give an exact integer length at some step (never rounded)."""


# --- the six free Tx/Rx parameters of plan B4 ----------------------------------------------------


@dataclass(frozen=True)
class ParameterSpec:
    """One free parameter: name, allowed range, and the prior used when it is flagged."""

    name: str
    low: float
    high: float
    prior: float


B4_PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("tx_bandwidth_ghz", 10.0, 60.0, 35.0),
    ParameterSpec("rx_bandwidth_ghz", 10.0, 60.0, 35.0),
    ParameterSpec("thermal_noise_pa_per_rthz", 5.0, 60.0, 32.5),
    ParameterSpec("modulation_depth", 0.2, 1.0, 0.6),
    ParameterSpec("bias_fraction", 0.4, 0.6, 0.5),
    ParameterSpec("electrical_snr_ceiling_db", 15.0, 35.0, 25.0),
)
B4_NAMES = tuple(p.name for p in B4_PARAMETERS)


@dataclass(frozen=True)
class TxRxParameters:
    """The Tx/Rx vector of plan B4. Out-of-range or non-finite values are refused, never clipped."""

    tx_bandwidth_ghz: float = 35.0
    rx_bandwidth_ghz: float = 35.0
    thermal_noise_pa_per_rthz: float = 32.5
    modulation_depth: float = 0.6
    bias_fraction: float = 0.5
    electrical_snr_ceiling_db: float = 25.0

    def __post_init__(self) -> None:
        for spec in B4_PARAMETERS:
            value = getattr(self, spec.name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{spec.name} must be a number, got {value!r}")
            if not math.isfinite(value) or not spec.low <= value <= spec.high:
                raise ValueError(
                    f"{spec.name}={value!r} is outside its allowed range [{spec.low}, {spec.high}]"
                )

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in B4_NAMES}

    @classmethod
    def from_mapping(cls, values: Any) -> TxRxParameters:
        """Exactly the six names of B4: a missing or extra name is an error."""
        if not isinstance(values, dict) or set(values) != set(B4_NAMES):
            raise ValueError(f"parameters must have exactly the keys {B4_NAMES}")
        return cls(**values)


@dataclass(frozen=True)
class ChainConfig:
    """Fixed, declared settings (plan F1, F4, F6). Not free parameters."""

    n_symbols: int = CAPTURE_SYMBOLS
    training_symbols: int = TRAINING_SYMBOLS
    responsivity_a_per_w: float = RESPONSIVITY_A_PER_W
    extinction_db: float = EXTINCTION_DB
    roll_off: float = SRRC_ROLL_OFF
    dac_bits: int = DAC_BITS

    def __post_init__(self) -> None:
        if self.n_symbols % GRID_MULTIPLE != 0 or self.n_symbols <= 0:
            raise ChainGridError(
                f"n_symbols={self.n_symbols} must be a positive multiple of {GRID_MULTIPLE} "
                "(plan F1); 655360 is refused"
            )
        if not 0 <= self.training_symbols < self.n_symbols:
            raise ValueError("training_symbols must be below n_symbols")
        if self.dac_bits < 2:
            raise ValueError("dac_bits must be at least 2")


# --- the sample grid -----------------------------------------------------------------------------


def _rate_ratio(fs_in_hz: int, fs_out_hz: int) -> Fraction:
    if int(fs_in_hz) != fs_in_hz or int(fs_out_hz) != fs_out_hz or fs_in_hz <= 0 or fs_out_hz <= 0:
        raise ChainGridError("sample rates must be positive whole numbers of Hz")
    return Fraction(int(fs_out_hz), int(fs_in_hz))


def exact_length(n_in: int, ratio: Fraction) -> int:
    """n_in x ratio, which must be an integer; otherwise ChainGridError (no rounding)."""
    out = n_in * ratio
    if out.denominator != 1:
        raise ChainGridError(f"{n_in} samples at ratio {ratio} give {float(out)}, not an integer")
    return int(out)


def sample_counts(n_symbols: int, baud_gbd: float) -> dict[str, int]:
    """Samples of one capture on the AWG, analogue, scope and 2-sps grids (each must be whole)."""
    baud = Fraction(baud_gbd).limit_denominator(1000)
    if baud <= 0:
        raise ChainGridError("baud rate must be positive")
    counts: dict[str, int] = {}
    for name, fs_hz in (
        ("awg", AWG_RATE_HZ),
        ("analogue", ANALOGUE_RATE_HZ),
        ("scope", SCOPE_RATE_HZ),
    ):
        value = n_symbols * Fraction(fs_hz, 1) / (baud * 10**9)
        if value.denominator != 1:
            raise ChainGridError(
                f"{n_symbols} symbols at {baud_gbd} GBd give {float(value)} samples at {fs_hz} Hz"
            )
        counts[name] = int(value)
    counts["t2"] = 2 * n_symbols
    if n_symbols % GRID_MULTIPLE != 0:
        raise ChainGridError(f"n_symbols={n_symbols} is not a multiple of {GRID_MULTIPLE}")
    return counts


def resample_exact(x: FloatArray, fs_in_hz: int, fs_out_hz: int) -> FloatArray:
    """Ideal band-limited resampling of one period by an exact rational factor.

    Spectral zero-padding (up) or truncation (down) of the periodic signal, so there is no
    transient and no seam. The output length is x.size x fs_out / fs_in and must be an integer.
    A bin at the input Nyquist is split in two on the way up; on the way down every bin at or
    above the output Nyquist is dropped (a brick wall: no aliasing). DC and every in-band tone are
    preserved to rounding.
    """
    ratio = _rate_ratio(fs_in_hz, fs_out_hz)
    n_in = x.size
    n_out = exact_length(n_in, ratio)
    if n_out == n_in:
        return np.asarray(x, dtype=float).copy()
    spectrum = np.fft.rfft(x)
    out = np.zeros(n_out // 2 + 1, dtype=complex)
    if n_out > n_in:
        out[: spectrum.size] = spectrum
        if n_in % 2 == 0:
            out[n_in // 2] *= 0.5
    else:
        keep = (n_out + 1) // 2 if n_out % 2 == 0 else n_out // 2 + 1  # bins strictly below Nyquist
        out[:keep] = spectrum[:keep]
    return np.asarray(np.fft.irfft(out, n=n_out) * (n_out / n_in), dtype=float)


# --- transmitter ---------------------------------------------------------------------------------


def symbol_indices(n_symbols: int, seed: int = SYMBOL_SEED) -> IntArray:
    """Independent uniform PAM4 symbol indices (plan F4.1): PCG64 via `default_rng(seed)`."""
    return np.asarray(np.random.default_rng(seed).integers(0, 4, size=n_symbols), dtype=np.int64)


def _rrc_response(n: int, sps: float, roll_off: float) -> FloatArray:
    """`rrc_frequency_response` for a non-integer samples-per-symbol (it only uses fftfreq)."""
    return rrc_frequency_response(n, sps, roll_off)  # type: ignore[arg-type]


def shape_srrc(levels: FloatArray, n_out: int, roll_off: float = SRRC_ROLL_OFF) -> FloatArray:
    """SRRC-shaped periodic waveform of N symbols on an n_out-point grid, directly at the DAC rate.

    This equals up-sampling by 70, SRRC filtering at 70 samples per symbol and ideal decimation to
    the target grid (the chain the paper describes), because the filter removes everything above
    (1 + roll_off) / 2 symbol rates. The spectrum of a symbol-spaced sequence is periodic in
    frequency with period one symbol rate, and the SRRC reaches past half a symbol rate for a
    non-zero roll-off, so the periodic extension of the symbol spectrum is used. Unit DC gain.
    """
    n = levels.size
    spectrum = np.fft.fft(levels)
    k = np.arange(n_out // 2 + 1)
    response = _rrc_response(n_out, n_out / n, roll_off)[: k.size]
    shaped = spectrum[k % n] * response
    return np.asarray(np.fft.irfft(shaped, n=n_out) * (n_out / n), dtype=float)


def dac_quantise(x: FloatArray, bits: int = DAC_BITS) -> FloatArray:
    """Uniform quantiser with full scale at the signal peak, returned in [-1, 1] (plan D2)."""
    peak = float(np.max(np.abs(x)))
    if peak == 0.0:
        raise ValueError("an all-zero waveform cannot be scaled to full scale")
    steps = 2**bits - 1
    return np.asarray(np.round((x / peak + 1.0) / 2.0 * steps) / steps * 2.0 - 1.0, dtype=float)


# --- the analogue path (shared by the PAM chain and the tone test) -------------------------------


@dataclass(frozen=True)
class LinkSpec:
    """A fibre to propagate through, or None for back-to-back (no fibre, no link loss)."""

    profile: FiberProfile | None = None
    wavelength_nm: float = 1550.0


@dataclass(frozen=True)
class AnalogueOutput:
    """The photocurrent after the Rx filter, split into signal and noise (linear, so additive)."""

    signal: FloatArray
    noise: FloatArray | None
    laser_power_w: float
    mean_received_w: float
    resolved: ResolvedFiber | None


def analogue_path(
    drive_norm: FloatArray,
    fs_hz: float,
    *,
    tx_bandwidth_hz: float | None,
    rx_bandwidth_hz: float | None,
    modulation_depth: float,
    bias_fraction: float,
    thermal_a_per_rthz: float,
    link: LinkSpec,
    rop_dbm: float,
    config: ChainConfig,
    z_shot: FloatArray | None = None,
    z_thermal: FloatArray | None = None,
) -> AnalogueOutput:
    """Tx filter, MZM, propagation, square law, noise and Rx filter at the analogue rate.

    Matched received power: the CW laser power is set so the mean received optical power is the
    ROP, whatever the loss (the same rule as `transmit_profile`, compensation as a pure gain).
    `z_shot` and `z_thermal` are standard-normal arrays (or None for a noise-free run).
    """
    if drive_norm.size == 0 or float(np.max(np.abs(drive_norm))) > 1 + 1e-12:
        raise ValueError("the drive waveform must be non-empty and normalised to [-1, 1]")
    check_matched_received_power_dbm(rop_dbm)
    base = LinkConfig(
        v_pi=V_PI,
        drive_vpp=modulation_depth * V_PI,
        bias_fraction_of_vpi=bias_fraction,
        extinction_db=config.extinction_db,
        responsivity_a_per_w=config.responsivity_a_per_w,
        transmitter_bandwidth_hz=tx_bandwidth_hz,
        receiver_bandwidth_hz=rx_bandwidth_hz if rx_bandwidth_hz else 1e12,
    )
    resolved: ResolvedFiber | None = None
    link_cfg = base
    if link.profile is not None:
        resolved = resolve_profile(link.profile, link.wavelength_nm)
        link_cfg = profile_link_config(resolved, base)
    drive = drive_norm * link_cfg.drive_vpp / 2
    if tx_bandwidth_hz is not None:
        drive = lowpass(drive, fs_hz, tx_bandwidth_hz)
    transmission = mzm_intensity(drive, link_cfg)
    loss_db = span_loss_db(link_cfg) if resolved is not None else 0.0
    mean_unit = float(transmission.mean()) * 10 ** (-loss_db / 10)
    laser_w = dbm_to_watt(rop_dbm) / mean_unit if mean_unit > 0 else math.inf
    if not math.isfinite(laser_w) or laser_w > MAX_MATCHED_LASER_POWER_W:
        raise ValueError(
            f"matched received power needs a laser of {laser_w:g} W, above the sanity limit "
            f"{MAX_MATCHED_LASER_POWER_W:g} W"
        )
    field_in = np.sqrt(laser_w * transmission) + 0j
    if resolved is not None:
        field_out = propagate_profile_field(field_in, fs_hz, resolved).field
    else:
        field_out = field_in
    optical = np.abs(field_out) ** 2
    current = config.responsivity_a_per_w * optical
    noise: FloatArray | None = None
    if z_shot is not None or z_thermal is not None:
        if z_shot is None or z_thermal is None or z_shot.size != current.size:
            raise ValueError("z_shot and z_thermal must both be given, one value per sample")
        if z_thermal.size != current.size:
            raise ValueError("z_thermal must have one value per sample")
        shot = z_shot * np.sqrt(2 * ELEMENTARY_CHARGE * np.maximum(current, 0.0) * fs_hz / 2)
        thermal = z_thermal * (thermal_a_per_rthz * math.sqrt(fs_hz / 2))
        noise = shot + thermal
    if rx_bandwidth_hz is not None:
        bandwidth = min(rx_bandwidth_hz, fs_hz / 2)
        current = lowpass(current, fs_hz, bandwidth)
        if noise is not None:
            noise = lowpass(noise, fs_hz, bandwidth)
    return AnalogueOutput(current, noise, laser_w, float(optical.mean()), resolved)


# --- first null through the chain (tone mode) ----------------------------------------------------


def tone_amplitude(
    frequency_hz: float,
    link: LinkSpec,
    *,
    n_samples: int = 14_000,
    amplitude: float = 1e-3,
    modulation_depth: float = 0.6,
    rop_dbm: float = -5.0,
    config: ChainConfig | None = None,
) -> float:
    """Photocurrent amplitude at the tone through the chain's analogue path, noise-free, no filters.

    The tone must lie on an FFT bin (frequency a whole multiple of fs / n_samples = 20 MHz).
    """
    cfg = ChainConfig() if config is None else config
    cycles = frequency_hz * n_samples / ANALOGUE_RATE_HZ
    if abs(cycles - round(cycles)) > 1e-6 or cycles <= 0:
        raise ChainGridError("the tone frequency must be a whole multiple of fs / n_samples")
    t = np.arange(n_samples) / ANALOGUE_RATE_HZ
    drive = amplitude * np.cos(2 * np.pi * frequency_hz * t)
    out = analogue_path(
        drive,
        ANALOGUE_RATE_HZ,
        tx_bandwidth_hz=None,
        rx_bandwidth_hz=None,
        modulation_depth=modulation_depth,
        bias_fraction=0.5,
        thermal_a_per_rthz=0.0,
        link=link,
        rop_dbm=rop_dbm,
        config=cfg,
    )
    spectrum = np.fft.rfft(out.signal)
    return float(2 * abs(spectrum[round(cycles)]) / n_samples / amplitude)


def first_null_ghz(
    link: LinkSpec, search_ghz: tuple[float, float], *, step_ghz: float = 0.02, **kwargs: Any
) -> float:
    """Frequency of the lowest tone response in a window, on a 20 MHz grid, through the chain.

    The window must bracket a null (the caller passes a window around the closed form); an end
    point being the minimum raises, because then no null lies inside the window.
    """
    lo, hi = search_ghz
    step = round(step_ghz * 1e9 / (ANALOGUE_RATE_HZ / 14_000))
    if step < 1:
        raise ValueError("step_ghz is finer than the 20 MHz tone grid")
    first, last = round(lo * 1e9 / 20e6), round(hi * 1e9 / 20e6)
    bins = np.arange(first, last + 1, step)
    values = np.array([tone_amplitude(b * 20e6, link, **kwargs) for b in bins])
    i = int(np.argmin(values))
    if i in (0, bins.size - 1):
        raise ValueError("no interior null in the search window")
    return float(bins[i] * 20e6 / 1e9)


# --- receiver, metrics ---------------------------------------------------------------------------


def count_bit_errors(tx_indices: IntArray, rx_indices: IntArray) -> int:
    """Gray-mapped bit errors between two PAM4 index sequences."""
    table = label_bits(4)
    return int(np.count_nonzero(table[tx_indices] != table[rx_indices]))


def snr_db_b6(levels: FloatArray, output: FloatArray) -> float:
    """Plan B6: 10 log10(mean |s|^2 / mean |s_hat - s|^2) over the given symbols; inf at zero."""
    error = float(np.mean((output - levels) ** 2))
    power = float(np.mean(levels**2))
    return math.inf if error == 0.0 else 10.0 * math.log10(power / error)


@dataclass(frozen=True)
class BerReading:
    """A BER by error counting, with the plan's censoring (A3, F2)."""

    errors: int
    n_bits: int
    ber: float
    censored: bool  # zero errors, or BER below 1e-5
    text: str

    @classmethod
    def from_counts(cls, errors: int, n_bits: int) -> BerReading:
        if n_bits <= 0 or not 0 <= errors <= n_bits:
            raise ValueError(f"invalid counts: {errors} errors in {n_bits} bits")
        ber = errors / n_bits
        if errors == 0:
            return cls(errors, n_bits, 0.0, True, f"below 1/N_b (N_b = {n_bits}, {1 / n_bits:.2g})")
        if ber < BER_CENSOR_FLOOR:
            return cls(errors, n_bits, ber, True, f"{ber:.3g} (censored: below 1e-5)")
        if ber < BER_REPORT_FLOOR:
            return cls(errors, n_bits, ber, False, "below 1e-4")  # plan F2: no count is quoted
        return cls(errors, n_bits, ber, False, f"{ber:.3g}")


class TraceCapActedError(ArithmeticError):
    """The trace cap of the RLS equaliser acted, so the run is not the declared lambda 0.998 RLS.

    Plan Amendment 6: the cap is pinned at 1e10 where it never acts on this chain. A run in which it
    acted is invalid and can never be scored; it is not repaired by changing the cap.
    """


class NotScorableError(ValueError):
    """A point that is not a run of the declared chain was offered for scoring."""


class FrozenOverrideError(ValueError):
    """After a freeze, parameters, chain configuration or equaliser may not be overridden."""


@dataclass(frozen=True)
class PointResult:
    """One operating point: error counts, SNR, and what ran.

    `scorable` is True only for a run of the declared chain: the default chain configuration, the
    default equaliser with the pinned trace cap, noise on, the trace cap never acted, and not a
    diagnostic run. Anything else carries the reasons in `unscorable_reasons` and must not enter a
    score (`require_scorable`).
    """

    reading: BerReading
    snr_db: float
    ser: float
    n_scored_symbols: int
    laser_power_w: float
    mean_received_dbm: float
    seconds: dict[str, float]
    dfe: DfeResult = field(repr=False)
    unscorable_reasons: tuple[str, ...] = ()

    @property
    def ber(self) -> float:
        return self.reading.ber

    @property
    def scorable(self) -> bool:
        return not self.unscorable_reasons


def require_scorable(points: Iterable[PointResult]) -> None:
    """Raise `NotScorableError` unless every point is a scorable run of the declared chain."""
    for k, point in enumerate(points):
        if not isinstance(point, PointResult) or not point.scorable:
            why = ", ".join(point.unscorable_reasons) if isinstance(point, PointResult) else "type"
            raise NotScorableError(f"point {k} cannot be scored: {why}")


def ceiling_noise_std(scope_signal: FloatArray, ceiling_db: float) -> float:
    """Std of the white ceiling noise: signal variance over 10^(ceiling/10) (plan F4.7)."""
    return math.sqrt(float(np.var(scope_signal)) / 10 ** (ceiling_db / 10))


def matched_filter_t2(ac: FloatArray, roll_off: float = SRRC_ROLL_OFF) -> FloatArray:
    """Zero-phase SRRC matched filter on the 2-samples-per-symbol grid (plan F4.8)."""
    response = rrc_frequency_response(ac.size, 2, roll_off)[: ac.size // 2 + 1]
    return np.asarray(np.fft.irfft(np.fft.rfft(ac) * response, n=ac.size), dtype=float)


def noise_generator(baud_gbd: int, point_index: int) -> np.random.Generator:
    """The per-point noise stream of plan F4.2: independent of the link (common random numbers)."""
    seq = np.random.SeedSequence([SYMBOL_SEED, NOISE_SEED_TAG, int(baud_gbd), int(point_index)])
    return np.random.default_rng(seq)


def simulate_point(
    params: TxRxParameters | None,
    rate_gbps: int,
    rop_dbm: float,
    *,
    link: LinkSpec | None = None,
    point_index: int = 0,
    config: ChainConfig | None = None,
    equalizer: RlsDfeConfig | None = None,
    noise: bool = True,
    diagnostic: bool = False,
) -> PointResult:
    """Simulate one operating point of one rate and link; see the module docstring for the chain.

    `link=None` is back-to-back (also the "no-fibre output" of plan B3.1). With `noise=False` no
    noise is added anywhere (analogue noise and the ceiling), for noise-free checks.

    Scoring runs (plan Amendment 6). Before a freeze the vector, configuration and equaliser may
    be given freely (calibration), but a result is `scorable` only for the declared chain. After a
    freeze (a record exists at the committed path) the verified record is loaded and used: `params`
    must be None or equal to the record's vector, and `config`, `equalizer` and `noise=False` are
    refused (`FrozenOverrideError`), unless `diagnostic=True`, whose results are never scorable. If
    the trace cap acts the run raises `TraceCapActedError` (diagnostic runs excepted).
    """
    from opticps.measurement import nanf_freeze  # lazy: nanf_freeze imports this module

    cfg = ChainConfig() if config is None else config
    if rate_gbps not in BAUD_GBD:
        raise ValueError(f"rate_gbps must be one of {sorted(BAUD_GBD)}")
    baud = BAUD_GBD[rate_gbps]
    counts = sample_counts(cfg.n_symbols, baud)  # refuses a grid that is not exact
    spec = LinkSpec() if link is None else link
    declared_eq = RlsDfeConfig(
        training_symbols=cfg.training_symbols, p_trace_cap=PINNED_P_TRACE_CAP
    )
    eq = declared_eq if equalizer is None else equalizer
    if eq.samples_per_symbol != 2 or eq.training_symbols != cfg.training_symbols:
        raise ValueError("the chain feeds a T/2 equaliser with the declared training length")
    reasons: list[str] = []
    if diagnostic:
        reasons.append("diagnostic run")
    if cfg != ChainConfig():
        reasons.append("chain configuration overridden")
    if eq != declared_eq:
        reasons.append("equaliser overridden")
    if not noise:
        reasons.append("noise off")
    if nanf_freeze.freeze_record_present() and not diagnostic:
        if reasons:
            raise FrozenOverrideError(
                "after a freeze the configuration, equaliser and noise cannot be overridden: "
                + ", ".join(reasons)
            )
        record: FreezeRecord = nanf_freeze.load_freeze_record()
        if params is not None and params != record.parameters:
            raise FrozenOverrideError("after a freeze the parameters are those of the record")
        params = record.parameters
    if params is None:
        raise ValueError("params is required until a freeze record exists")
    seconds: dict[str, float] = {}
    tick = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal tick
        now = time.perf_counter()
        seconds[name] = now - tick
        tick = now

    idx = symbol_indices(cfg.n_symbols)
    levels = pam_levels(4)[idx]
    awg = shape_srrc(levels, counts["awg"], cfg.roll_off)
    dac = dac_quantise(awg, cfg.dac_bits)
    drive = np.clip(resample_exact(dac, AWG_RATE_HZ, ANALOGUE_RATE_HZ), -1.0, 1.0)
    lap("transmitter")

    rng = noise_generator(baud, point_index)
    n_a = counts["analogue"]
    z_shot = rng.standard_normal(n_a) if noise else None
    z_thermal = rng.standard_normal(n_a) if noise else None
    z_ceiling = rng.standard_normal(counts["scope"]) if noise else None
    lap("noise draws")

    out = analogue_path(
        drive,
        float(ANALOGUE_RATE_HZ),
        tx_bandwidth_hz=params.tx_bandwidth_ghz * 1e9,
        rx_bandwidth_hz=params.rx_bandwidth_ghz * 1e9,
        modulation_depth=params.modulation_depth,
        bias_fraction=params.bias_fraction,
        thermal_a_per_rthz=params.thermal_noise_pa_per_rthz * 1e-12,
        link=spec,
        rop_dbm=rop_dbm,
        config=cfg,
        z_shot=z_shot,
        z_thermal=z_thermal,
    )
    lap("analogue")

    scope_signal = resample_exact(out.signal, ANALOGUE_RATE_HZ, SCOPE_RATE_HZ)
    scope = scope_signal
    if noise and out.noise is not None and z_ceiling is not None:
        scope_noise = resample_exact(out.noise, ANALOGUE_RATE_HZ, SCOPE_RATE_HZ)
        sigma_c = ceiling_noise_std(scope_signal, params.electrical_snr_ceiling_db)
        scope = scope_signal + scope_noise + sigma_c * z_ceiling
    lap("scope")

    two_sps = resample_exact(scope, SCOPE_RATE_HZ, 2 * baud * 10**9)
    ac = two_sps - two_sps.mean()
    rms = float(np.sqrt(np.mean(ac**2)))
    if rms == 0.0:
        raise ValueError("the received waveform has no AC power")
    matched = matched_filter_t2(ac / rms, cfg.roll_off)
    lap("front end")

    result = rls_equalize(matched, levels, eq)
    lap("equaliser")
    if result.n_trace_caps > 0:
        reasons.append(f"trace cap acted {result.n_trace_caps} times")
        if not diagnostic:
            raise TraceCapActedError(
                f"the trace cap ({eq.p_trace_cap:g}) acted {result.n_trace_caps} times: the run is "
                "not the declared RLS and cannot be scored (plan Amendment 6)"
            )

    scored = slice(cfg.training_symbols, None)
    errors = count_bit_errors(idx[scored], result.decision_indices[scored])
    n_scored = cfg.n_symbols - cfg.training_symbols
    reading = BerReading.from_counts(errors, 2 * n_scored)
    ser = float(np.mean(idx[scored] != result.decision_indices[scored]))
    snr = snr_db_b6(levels[scored], result.output[scored])
    lap("metrics")
    return PointResult(
        reading=reading,
        snr_db=snr,
        ser=ser,
        n_scored_symbols=n_scored,
        laser_power_w=out.laser_power_w,
        mean_received_dbm=watt_to_dbm(out.mean_received_w),
        seconds=seconds,
        dfe=result,
        unscorable_reasons=tuple(reasons),
    )


# --- lost-lock runs (plan Amendment 7) -----------------------------------------------------------


@dataclass(frozen=True)
class PointOutcome:
    """One sweep point: a scorable result, or a lost-lock run with its point and reason.

    A lost-lock run (the trace cap acted, `RlsInstabilityError`, or both) is invalid: it is never
    scored and never silently skipped. It stays in the sweep with `result` None and `reason` set,
    and `lost_report` lists it.
    """

    label: str  # for example "100G/NANF/-9.0"
    rop_dbm: float
    result: PointResult | None
    reason: str = ""

    @property
    def lost(self) -> bool:
        return self.result is None


def run_point(
    label: str,
    params: TxRxParameters | None,
    rate_gbps: int,
    rop_dbm: float,
    **kwargs: Any,
) -> PointOutcome:
    """`simulate_point`, with a lost-lock run returned as an invalid outcome instead of raised.

    Only `TraceCapActedError` and `RlsInstabilityError` are caught; any other error, such as a
    refused override or a bad grid, still raises. A result that is not scorable is refused here too
    (`NotScorableError`), so an outcome with a result is always a scorable run.
    """
    try:
        result = simulate_point(params, rate_gbps, rop_dbm, **kwargs)
    except TraceCapActedError as err:
        return PointOutcome(label, rop_dbm, None, f"trace cap acted: {err}")
    except RlsInstabilityError as err:
        return PointOutcome(label, rop_dbm, None, f"RlsInstabilityError: {err}")
    require_scorable([result])
    return PointOutcome(label, rop_dbm, result)


def lost_report(outcomes: Iterable[PointOutcome]) -> list[str]:
    """One line per lost-lock point, with its point and reason. Empty when none was lost."""
    return [f"LOST LOCK {o.label} at {o.rop_dbm:g} dBm: {o.reason}" for o in outcomes if o.lost]


@dataclass(frozen=True)
class CurveArrays:
    """The arrays of a swept curve for scoring. Lost points stay in, flagged by `valid`."""

    rop_dbm: FloatArray
    ber: FloatArray  # NaN where lost: the scoring functions ignore a value whose `valid` is False
    snr_db: FloatArray
    valid: NDArray[np.bool_]
    n_lost: int


def curve_arrays(outcomes: Sequence[PointOutcome]) -> CurveArrays:
    """Arrays for the scoring functions; a lost point keeps its place and is marked invalid."""
    rop = np.array([o.rop_dbm for o in outcomes], dtype=float)
    ber = np.array([math.nan if o.result is None else o.result.ber for o in outcomes])
    snr = np.array([math.nan if o.result is None else o.result.snr_db for o in outcomes])
    valid = np.array([not o.lost for o in outcomes], dtype=bool)
    return CurveArrays(rop, ber, snr, valid, int(np.count_nonzero(~valid)))
