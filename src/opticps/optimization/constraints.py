"""Distribution-search constraints, derived from the repository's Mach-Zehnder model.

Each constraint has `.check(...)` and returns a `Feasibility`: FEASIBLE, INACTIVE or
INFEASIBLE, with a reason and the adjustments that would be needed. Nothing here ever changes
a physical set-point. A constraint that can only be met by changing the laser power, the drive
swing or the sample rate reports that change in `adjustments`, and reports FEASIBLE with it
only when the caller declared in advance (a constructor flag) that this adjustment is part of
the protocol and it is within the declared limit. Otherwise the status is INFEASIBLE.

The model (`optical_channel.link.mzm_intensity`): launched power of a level with drive v is
P_laser T(v), T(v) = L (1 - V cos(pi (v / V_pi + b))) / 2, with L the insertion loss, V the
extinction visibility and b the bias as a fraction of V_pi. Level i of PAM-M has the
normalised amplitude a_i = (2 i - (M - 1)) / (M - 1) and drive v_i = a_i V_pp / 2, or the
arcsine pre-distorted drive when `predistort` is set. Three consequences, checked in tests:

1. Mean optical power. At quadrature (b = 1/2) T(v) = L (1 + V sin(pi v / V_pi)) / 2, and the
   drive map is odd, so for a symmetric PMF E[sin(pi v / V_pi)] = 0 and the mean launched power
   is L P_laser / 2 whatever the PMF. A fixed average-optical-power constraint is then INACTIVE:
   it cannot discriminate between symmetric PMFs. Off quadrature, or with an asymmetric PMF,
   the mean depends on the PMF, the constraint is active, and meeting it means scaling the
   laser power by target / mean (reported as an adjustment).
2. Peak and OMA. Fixed peak keeps the drive alphabet, so the peak drive is V_pp / 2 whenever
   the outer levels carry mass. OMA is the launched-power difference between the extreme levels
   in use (as `transmit` measures it). With all extreme levels in use it is the same number at
   fixed bias and laser power, so fixed OMA is INACTIVE (it equals fixed peak). It differs
   when the outer levels have zero mass: the used extremes are inner levels, OMA falls, and
   restoring it needs a larger drive swing (an adjustment).
3. Realised user rate. User rate = f_s / sps x (information bits per frame) / (frame symbols),
   with frame symbols = head + payload and information bits = (payload / n) k for blocks of n
   symbols carrying k bits. Rate scales linearly with f_s at fixed sps, so equalising rates
   needs f_s' = f_s x target / rate, which must lie in the instrument range (200 to 256 GSa/s).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq

from opticps.modulation.pam import pam_levels
from opticps.optical_channel.link import LinkConfig, mzm_intensity, predistort
from opticps.shaping.distributions import validate_probabilities

_REL_TOL = 1e-9


class FeasibilityStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    INACTIVE = "INACTIVE"
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True)
class Feasibility:
    """Outcome of a constraint check.

    `adjustments` lists set-point changes the constraint would need (name -> new value, plus
    `<name>_factor` where a ratio is meaningful). It can be non-empty with INFEASIBLE: those
    are the changes that were not allowed or not reachable.
    """

    status: FeasibilityStatus
    reason: str
    adjustments: dict[str, float] = field(default_factory=dict)


def drive_voltages(config: LinkConfig, order: int) -> NDArray[np.float64]:
    """Drive voltage of every symbol index, lowest level first (as `link.transmit` forms it)."""
    amplitude = pam_levels(order) / (order - 1)
    if config.predistort:
        return np.asarray(predistort(amplitude, config), dtype=float)
    return np.asarray(amplitude * config.drive_vpp / 2, dtype=float)


def level_powers_w(config: LinkConfig, order: int) -> NDArray[np.float64]:
    """Launched optical power of every symbol index, in watts."""
    return np.asarray(config.laser_power_w * mzm_intensity(drive_voltages(config, order), config))


def mean_power_w(config: LinkConfig, probabilities: object) -> float:
    """E[launched power] of a PMF, in watts."""
    p = validate_probabilities(probabilities)
    return float(p @ level_powers_w(config, p.size))


def oma_w(config: LinkConfig, probabilities: object) -> float:
    """Launched OMA: power of the highest used level minus that of the lowest used level."""
    p = validate_probabilities(probabilities)
    drive = drive_voltages(config, p.size)
    powers = level_powers_w(config, p.size)
    used = np.flatnonzero(p > 0)
    return float(powers[used[np.argmax(drive[used])]] - powers[used[np.argmin(drive[used])]])


def _at_quadrature(config: LinkConfig) -> bool:
    return abs(config.bias_fraction_of_vpi - 0.5) < 1e-12


def _symmetric(p: NDArray[np.float64]) -> bool:
    return bool(np.max(np.abs(p - p[::-1])) < 1e-12)


@dataclass(frozen=True)
class FixedPeak:
    """Peak drive amplitude fixed at `peak_v` (default: the configured V_pp / 2).

    The drive alphabet does not depend on the PMF, so any PMF is FEASIBLE with no adjustment;
    if its outer levels have zero mass the realised peak is lower and the reason says so.
    A declared `peak_v` that differs from the configured alphabet peak needs a different V_pp:
    reported as an adjustment, FEASIBLE only with `allow_drive_rescale`.
    """

    peak_v: float | None = None
    allow_drive_rescale: bool = False

    def check(self, config: LinkConfig, probabilities: object) -> Feasibility:
        p = validate_probabilities(probabilities)
        alphabet_peak = (
            config.drive_vpp / 2
            if not config.predistort
            else float(np.abs(drive_voltages(config, p.size)).max())
        )
        target = alphabet_peak if self.peak_v is None else float(self.peak_v)
        if target <= 0:
            raise ValueError("peak_v must be positive")
        if abs(alphabet_peak - target) > _REL_TOL * target:
            needed = {"drive_vpp": 2 * target, "drive_vpp_factor": target / alphabet_peak}
            if config.predistort:
                return Feasibility(
                    FeasibilityStatus.INFEASIBLE,
                    "peak differs from the configured drive and rescaling a pre-distorted "
                    "drive is not modelled here",
                    needed,
                )
            if self.allow_drive_rescale and 2 * target <= 2 * config.v_pi:
                return Feasibility(
                    FeasibilityStatus.FEASIBLE,
                    f"drive_vpp must change to {2 * target:g} V (declared rescale)",
                    needed,
                )
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"configured peak {alphabet_peak:g} V differs from the fixed peak {target:g} V "
                "and a drive rescale is not declared or exceeds 2 V_pi",
                needed,
            )
        realised = float(np.abs(drive_voltages(config, p.size)[p > 0]).max())
        if realised < alphabet_peak * (1 - _REL_TOL):
            return Feasibility(
                FeasibilityStatus.FEASIBLE,
                f"outer levels carry no mass: realised peak {realised:g} V is below the fixed "
                f"{alphabet_peak:g} V; the drive is not rescaled",
            )
        return Feasibility(FeasibilityStatus.FEASIBLE, "peak equals the fixed peak")


@dataclass(frozen=True)
class FixedAverageOpticalPower:
    """Mean launched optical power fixed at `target_w` (default: that of the uniform PMF).

    INACTIVE when the PMF already meets the target to 1e-9 relative: at quadrature with a
    symmetric PMF this is structural (mean power does not depend on the PMF). Otherwise the
    constraint is active and needs the laser power scaled by target / mean, reported in
    `adjustments["laser_power_w"]`. That is FEASIBLE only with `allow_laser_adjustment` and
    within `max_laser_power_w` (if given); otherwise INFEASIBLE. The laser is never rescaled
    silently.
    """

    target_w: float | None = None
    allow_laser_adjustment: bool = False
    max_laser_power_w: float | None = None

    def check(self, config: LinkConfig, probabilities: object) -> Feasibility:
        p = validate_probabilities(probabilities)
        mean = mean_power_w(config, p)
        target = (
            mean_power_w(config, np.full(p.size, 1.0 / p.size))
            if self.target_w is None
            else float(self.target_w)
        )
        if target <= 0:
            raise ValueError("target_w must be positive")
        if abs(mean - target) <= _REL_TOL * target:
            structural = _at_quadrature(config) and _symmetric(p)
            reason = (
                "at quadrature a symmetric PMF has a mean optical power independent of the "
                "PMF (E[sin] = 0), so this constraint does not discriminate between PMFs"
                if structural
                else "the PMF already has the target mean optical power; no adjustment needed"
            )
            return Feasibility(FeasibilityStatus.INACTIVE, reason)
        factor = target / mean
        needed = {"laser_power_w": config.laser_power_w * factor, "laser_power_w_factor": factor}
        cause = (
            "asymmetric PMF"
            if not _symmetric(p)
            else "bias off quadrature"
            if not _at_quadrature(config)
            else "target differs from the mean power at this set-point"
        )
        if not self.allow_laser_adjustment:
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"mean optical power {mean:.4g} W differs from the fixed {target:.4g} W "
                f"({cause}); meeting it needs laser power x{factor:.4g}, which was not declared",
                needed,
            )
        if self.max_laser_power_w is not None and needed["laser_power_w"] > self.max_laser_power_w:
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"laser power {needed['laser_power_w']:.4g} W needed ({cause}) exceeds the "
                f"limit {self.max_laser_power_w:.4g} W",
                needed,
            )
        return Feasibility(
            FeasibilityStatus.FEASIBLE,
            f"laser power must change to {needed['laser_power_w']:.4g} W ({cause}; declared)",
            needed,
        )


@dataclass(frozen=True)
class FixedOMA:
    """Launched OMA fixed at `target_oma_w` (default: OMA of the full alphabet at this set-point).

    With all extreme levels in use the OMA is the fixed-peak value, so this is INACTIVE (the
    same protocol as FixedPeak, no separate comparison). It differs when the outer levels have
    zero mass: the OMA is smaller and restoring it needs a larger drive swing. A declared
    target can also be below the current OMA, which needs a smaller swing. The swing is
    reported in `adjustments["drive_vpp"]` and is the smallest one on the first rising branch of
    OMA against swing (OMA folds over beyond its first maximum). FEASIBLE only with
    `allow_drive_rescale` and a reachable target (swing up to 2 V_pi); INFEASIBLE otherwise.
    The drive is never rescaled silently.
    """

    target_oma_w: float | None = None
    allow_drive_rescale: bool = False

    def check(self, config: LinkConfig, probabilities: object) -> Feasibility:
        p = validate_probabilities(probabilities)
        full = np.full(p.size, 1.0 / p.size)
        target = oma_w(config, full) if self.target_oma_w is None else float(self.target_oma_w)
        if target <= 0:
            raise ValueError("target_oma_w must be positive")
        oma = oma_w(config, p)
        if abs(oma - target) <= _REL_TOL * target:
            return Feasibility(
                FeasibilityStatus.INACTIVE,
                "the extreme levels are in use: OMA equals the fixed-peak value at this bias "
                "and laser power, so fixed OMA is not a separate protocol here",
            )
        if config.predistort:
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                "OMA differs from the target and rescaling a pre-distorted drive is not modelled",
            )

        def gap(vpp: float) -> float:
            return oma_w(_with_drive(config, vpp), p) - target

        # OMA rises from 0 with the swing up to a first maximum and then folds over. The swing
        # wanted is the smallest one, on that first rising branch, whether the target is above
        # or below the current OMA (a search that only went upward from the current swing
        # reached the fold-over branch for a lower target).
        grid = np.linspace(0.0, 2 * config.v_pi, 8001)[1:]
        values = np.array([gap(v) for v in grid])
        crossing = np.flatnonzero((values[:-1] < 0) & (values[1:] >= 0))
        direction = "below" if oma < target else "above"
        if crossing.size == 0:
            best = float(values.max() + target)
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"OMA {oma:.4g} W is {direction} the fixed {target:.4g} W and no drive swing up "
                f"to 2 V_pi = {2 * config.v_pi:g} V reaches it (largest reachable OMA "
                f"{best:.4g} W)",
            )
        i = int(crossing[0])
        vpp = float(brentq(gap, grid[i], grid[i + 1], xtol=1e-12))
        needed = {"drive_vpp": vpp, "drive_vpp_factor": vpp / config.drive_vpp}
        step = "increased" if vpp > config.drive_vpp else "reduced"
        cause = (
            "outer levels carry no mass"
            if self.target_oma_w is None
            else "the declared target differs from the OMA at this set-point"
        )
        if not self.allow_drive_rescale:
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"OMA {oma:.4g} W is {direction} the fixed {target:.4g} W ({cause}); the swing "
                f"would be {step} to drive_vpp {vpp:.4g} V, which was not declared",
                needed,
            )
        return Feasibility(
            FeasibilityStatus.FEASIBLE,
            f"drive_vpp must be {step} to {vpp:.4g} V ({cause}; declared)",
            needed,
        )


def _with_drive(config: LinkConfig, vpp: float) -> LinkConfig:
    return replace(config, drive_vpp=vpp)


@dataclass(frozen=True)
class FrameAccounting:
    """Frame overhead for the realised user rate (no FEC).

    `head_symbols` (preamble plus training) carry no payload bits. Each of the
    `payload_symbols / block_symbols` blocks carries `block_bits` bits.
    """

    head_symbols: int
    payload_symbols: int
    block_symbols: int
    block_bits: int
    samples_per_symbol: int

    def __post_init__(self) -> None:
        if self.head_symbols < 0 or self.payload_symbols <= 0:
            raise ValueError("head_symbols must be >= 0 and payload_symbols > 0")
        if self.block_symbols <= 0 or self.payload_symbols % self.block_symbols:
            raise ValueError("payload_symbols must be a positive multiple of block_symbols")
        if self.block_bits < 0 or self.samples_per_symbol < 1:
            raise ValueError("block_bits must be >= 0 and samples_per_symbol >= 1")

    @property
    def information_bits(self) -> int:
        return (self.payload_symbols // self.block_symbols) * self.block_bits

    @property
    def frame_symbols(self) -> int:
        return self.head_symbols + self.payload_symbols

    def user_rate_bps(self, sample_rate_hz: float) -> float:
        """Realised user rate: f_s / sps x information bits / frame symbols."""
        return sample_rate_hz / self.samples_per_symbol * self.information_bits / self.frame_symbols


@dataclass(frozen=True)
class EqualRealizedUserRate:
    """Equal realised user rate across waveforms, by adjusting the sample rate at fixed sps.

    The target is `target_rate_bps`. At the nominal sample rate a waveform realises
    `FrameAccounting.user_rate_bps(nominal)`; matching the target needs
    f_s' = nominal x target / rate, which must lie in [min, max] (default 200 to 256 GSa/s,
    nominal 224 GSa/s). A ratio of 1 (to 1e-9) is FEASIBLE with no adjustment. Otherwise the
    sample-rate change is reported in `adjustments["sample_rate_hz"]`; it is FEASIBLE only with
    `allow_sample_rate_adjustment` and inside the range, and INFEASIBLE, with the reason, if
    the ratio is out of range or the adjustment was not declared. Nothing is rescaled per
    waveform on its own.
    """

    target_rate_bps: float
    nominal_sample_rate_hz: float = 224e9
    min_sample_rate_hz: float = 200e9
    max_sample_rate_hz: float = 256e9
    allow_sample_rate_adjustment: bool = False

    def check(self, accounting: FrameAccounting) -> Feasibility:
        if self.target_rate_bps <= 0:
            raise ValueError("target_rate_bps must be positive")
        rate = accounting.user_rate_bps(self.nominal_sample_rate_hz)
        if rate <= 0:
            return Feasibility(FeasibilityStatus.INFEASIBLE, "the waveform carries no user bits")
        ratio = self.target_rate_bps / rate
        if abs(ratio - 1.0) <= _REL_TOL:
            return Feasibility(FeasibilityStatus.FEASIBLE, "realised user rate equals the target")
        needed_rate = self.nominal_sample_rate_hz * ratio
        needed = {"sample_rate_hz": needed_rate, "sample_rate_hz_factor": ratio}
        low, high = self.min_sample_rate_hz, self.max_sample_rate_hz
        if not (low * (1 - _REL_TOL) <= needed_rate <= high * (1 + _REL_TOL)):
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"matching {self.target_rate_bps / 1e9:.4g} Gb/s needs {needed_rate / 1e9:.4g} "
                f"GSa/s (x{ratio:.4f}) at {accounting.samples_per_symbol} samples per symbol, "
                f"outside {low / 1e9:g} to {high / 1e9:g} GSa/s",
                needed,
            )
        if not self.allow_sample_rate_adjustment:
            return Feasibility(
                FeasibilityStatus.INFEASIBLE,
                f"the realised rate is {rate / 1e9:.4g} Gb/s, not "
                f"{self.target_rate_bps / 1e9:.4g}; "
                f"matching it needs {needed_rate / 1e9:.4g} GSa/s, which was not declared",
                needed,
            )
        return Feasibility(
            FeasibilityStatus.FEASIBLE,
            f"sample rate must change to {needed_rate / 1e9:.4g} GSa/s (declared)",
            needed,
        )
