"""M-PAM profile configuration (config_schema_version 2) and frame-length checks.

`load_mpam_config` is the only way a run obtains the profiles and the best-fixed menu. The
menu and its entropy deficits are declared in the YAML before any test data is seen; the
loader refuses a file whose deficits differ from the values pinned in code, and
`MpamConfig.reported_fixed_menu` builds the baseline only from them, so a reported baseline
cannot be changed by an argument at run time.

Nothing here talks to an instrument. The M8199B limits applied are the ones already enforced
in `instruments.m8199b` (sample rate range, multiple of 512 samples, maximum length).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from opticps.instruments.m8199b import (
    DATA_OUTPUTS,
    GRANULARITY_SAMPLES,
    MAX_SAMPLE_RATE,
    MAX_SAMPLES,
    MIN_SAMPLE_RATE,
    M8199BConstraintError,
    Profile,
)
from opticps.modulation.pam import FRAME_ALIGNMENT, SUPPORTED_ORDERS, ModulationSpec
from opticps.optimization.adaptive import (
    DEFAULT_FIXED_DEFICITS,
    BaselineOverrideError,
    fixed_menu,
)
from opticps.optimization.constraints import (
    EqualRealizedUserRate,
    Feasibility,
    FeasibilityStatus,
    FrameAccounting,
)
from opticps.transmitter.frame import make_matcher
from opticps.transmitter.pulse import PulseConfig

CONFIG_SCHEMA_VERSION = 2
EVIDENCE_LABELS = ("simulated", "mock", "measured", "analytical")
PROTOCOLS = ("A", "B")
_TOP_KEYS = {
    "config_schema_version",
    "common",
    "fixed_menu",
    "adaptive",
    "protocol_A",
    "protocol_B",
}
_MENU_MEMBERS = ["Uniform", "Inner", "Outer"]


class ConfigError(ValueError):
    """The M-PAM configuration is not one this code accepts (default-deny)."""


@dataclass(frozen=True)
class MpamProfile:
    """One (protocol, symbol rate, order) experiment profile."""

    protocol: str
    name: str
    order: int
    sample_rate: float
    symbol_rate: float
    symbols: int

    def to_profile(self) -> Profile:
        return Profile(self.name, self.sample_rate, self.symbol_rate, self.symbols)

    @property
    def sps(self) -> int:
        return self.to_profile().sps


@dataclass(frozen=True)
class MpamConfig:
    """The validated contents of configs/mpam_profiles.yaml."""

    sha256: str
    seed: int
    block_length: int
    pulse: PulseConfig
    data_out: str
    decimals: int
    sample_rate: float
    constraint_protocol: str
    evidence: str
    fixed_deficits: tuple[float, ...]
    adaptive: Mapping[str, Any]
    profiles: tuple[MpamProfile, ...]

    def reported_fixed_menu(self, order: int) -> dict[str, tuple[float, ...]]:
        """The best-fixed menu of this config: the only one a report may call the baseline."""
        return fixed_menu(order, self.fixed_deficits)

    def profiles_for(self, order: int) -> list[MpamProfile]:
        return [p for p in self.profiles if p.order == order]


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}: missing key {key!r}")
    return mapping[key]


def load_mpam_config(path: Path) -> MpamConfig:
    """Read and validate the M-PAM profile YAML. Unknown versions and keys are refused."""
    raw = Path(path).read_bytes()
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ConfigError("the configuration must be a mapping")
    version = config.get("config_schema_version")
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"config_schema_version {version!r} is not supported (expected {CONFIG_SCHEMA_VERSION})"
        )
    unknown = set(config) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level keys {sorted(unknown)}")
    common = _require(config, "common", "config")
    if common["data_out"] not in DATA_OUTPUTS:
        raise ConfigError(f"data_out must be one of {DATA_OUTPUTS}")
    if common["evidence"] not in EVIDENCE_LABELS:
        raise ConfigError(f"evidence must be one of {EVIDENCE_LABELS}")
    menu = _require(config, "fixed_menu", "config")
    deficits = tuple(float(x) for x in menu["entropy_deficits_bits"])
    if list(menu["members"]) != _MENU_MEMBERS or deficits != DEFAULT_FIXED_DEFICITS:
        raise BaselineOverrideError(
            f"the pinned best-fixed menu is {_MENU_MEMBERS} at deficits "
            f"{DEFAULT_FIXED_DEFICITS} bit; the file declares {menu['members']} at {deficits}. "
            "A reported baseline cannot be changed by configuration or argument"
        )
    sample_rate = float(common["sample_rate_Sa_per_s"])
    profiles: list[MpamProfile] = []
    for entry in _require(config["protocol_A"], "profiles", "protocol_A"):
        for order in SUPPORTED_ORDERS:
            profiles.append(
                MpamProfile(
                    "A",
                    f"{entry['name']}_PAM{order}",
                    order,
                    sample_rate,
                    float(entry["symbol_rate_Bd"]),
                    int(entry["symbols"]),
                )
            )
    b = config["protocol_B"]
    nominal = float(b["nominal_bit_rate_bps"])
    for order in SUPPORTED_ORDERS:
        sps = int(b["samples_per_symbol"][order])
        baud = nominal / ModulationSpec(order).bits_per_symbol
        if abs(sample_rate / baud - sps) > 1e-9:
            raise ConfigError(
                f"protocol B PAM{order}: {nominal / 1e9:g} Gb/s needs {sample_rate / baud:g} "
                f"samples per symbol at {sample_rate / 1e9:g} GSa/s, not {sps}"
            )
        profiles.append(
            MpamProfile(
                "B", f"B_112G_PAM{order}", order, sample_rate, baud, int(b["symbols"][order])
            )
        )
    return MpamConfig(
        sha256=hashlib.sha256(raw).hexdigest(),
        seed=int(common["seed"]),
        block_length=int(common["block_length"]),
        pulse=PulseConfig(**common["pulse"]),
        data_out=common["data_out"],
        decimals=int(common["decimals"]),
        sample_rate=sample_rate,
        constraint_protocol=str(common["constraint_protocol"]),
        evidence=str(common["evidence"]),
        fixed_deficits=deficits,
        adaptive=_require(config, "adaptive", "config"),
        profiles=tuple(profiles),
    )


# ------------------------------------------------------------------ frame length and fit


def head_symbols(order: int) -> int:
    return ModulationSpec(order).head_symbols


def check_frame_fit(order: int, profile: MpamProfile, block_length: int = 1024) -> Feasibility:
    """FEASIBLE if the frame obeys every M8199B rule enforced here, else INFEASIBLE with why.

    Rules: sample rate 200 to 256 GSa/s, integer samples per symbol, head a multiple of 1024,
    payload a positive multiple of the matcher block, total samples a multiple of 512 and at
    most 1,048,576. A profile that fails is reported, never trimmed or padded.
    """
    spec = ModulationSpec(order)
    head = spec.head_symbols
    problems: list[str] = []
    if head % FRAME_ALIGNMENT:
        problems.append(f"head {head} is not a multiple of {FRAME_ALIGNMENT}")
    payload = profile.symbols - head
    if payload <= 0 or payload % block_length:
        problems.append(
            f"payload {payload} (= {profile.symbols} - head {head}) is not a positive "
            f"multiple of {block_length}"
        )
    try:
        sps = profile.sps
    except M8199BConstraintError as error:
        problems.append(str(error))
        sps = 0
    if not MIN_SAMPLE_RATE <= profile.sample_rate <= MAX_SAMPLE_RATE:
        problems.append(f"sample rate {profile.sample_rate / 1e9:g} GSa/s outside 200 to 256")
    if sps:
        samples = profile.symbols * sps
        if samples % GRANULARITY_SAMPLES:
            problems.append(f"{samples} samples is not a multiple of {GRANULARITY_SAMPLES}")
        if samples > MAX_SAMPLES:
            problems.append(f"{samples} samples exceed the maximum {MAX_SAMPLES}")
    if problems:
        return Feasibility(FeasibilityStatus.INFEASIBLE, f"{profile.name}: " + "; ".join(problems))
    return Feasibility(
        FeasibilityStatus.FEASIBLE,
        f"{profile.name}: {profile.symbols} symbols x {sps} sps = {profile.symbols * sps} samples "
        f"(head {head}, payload {payload})",
    )


def frame_length_rows(config: MpamConfig) -> list[dict[str, Any]]:
    """One row per profile: lengths, samples, duration and the fit status."""
    rows = []
    for p in config.profiles:
        fit = check_frame_fit(p.order, p, config.block_length)
        try:
            sps: int | None = p.sps
        except M8199BConstraintError:
            sps = None
        rows.append(
            {
                "protocol": p.protocol,
                "profile": p.name,
                "order": p.order,
                "symbol_rate_Bd": p.symbol_rate,
                "samples_per_symbol": sps,
                "head_symbols": head_symbols(p.order),
                "payload_symbols": p.symbols - head_symbols(p.order),
                "symbols": p.symbols,
                "samples": None if sps is None else p.symbols * sps,
                "status": fit.status.value,
                "reason": fit.reason,
            }
        )
    return rows


# ------------------------------------------------------------------ realised-rate equalisation


def rate_equalisation(
    order: int,
    menu: Mapping[str, Sequence[float]],
    symbols: int,
    sps: int,
    block_length: int = 1024,
    nominal_sample_rate: float = 224e9,
) -> list[dict[str, Any]]:
    """Report, per menu member, the sample rate that would equalise its realised user rate.

    The target is the direct uniform of the same order (log2 M bits per symbol, no matcher).
    Each row is evaluated as if the adjustment were declared; it is only REPORTED here
    (`applied` is always False): no waveform is resampled or re-clocked. A member whose
    required rate leaves 200 to 256 GSa/s is INFEASIBLE.
    """
    spec = ModulationSpec(order)
    payload = symbols - spec.head_symbols
    uniform_bits = spec.bits_per_symbol * block_length
    target = FrameAccounting(
        spec.head_symbols, payload, block_length, uniform_bits, sps
    ).user_rate_bps(nominal_sample_rate)
    constraint = EqualRealizedUserRate(
        target, nominal_sample_rate_hz=nominal_sample_rate, allow_sample_rate_adjustment=True
    )
    rows = []
    for name, p in menu.items():
        pmf = np.asarray(p, dtype=float)
        direct = bool(np.allclose(pmf, 1.0 / order, atol=1e-12))
        bits = uniform_bits if direct else make_matcher(pmf, block_length, order).k
        accounting = FrameAccounting(spec.head_symbols, payload, block_length, bits, sps)
        result = constraint.check(accounting)
        needed = result.adjustments.get("sample_rate_hz")
        rows.append(
            {
                "name": name,
                "bits_per_block": bits,
                "user_rate_bps": accounting.user_rate_bps(nominal_sample_rate),
                "required_sample_rate_hz": needed,
                "required_increase": None if needed is None else needed / nominal_sample_rate - 1,
                "status": result.status.value,
                "reason": result.reason,
                "applied": False,
            }
        )
    return rows


def dac_codes_per_level_step(order: int, full_scale_levels: float, bits: int = 8) -> float:
    """DAC codes between adjacent levels under the mid-tread map `export.dac_quantize` assumes.

    A diagnostic, not an instrument fact (the real code map is unverified, docs/engineering_log/
    VERIFICATION.md). Adjacent levels differ by 2 level units, i.e. 2 / full_scale_levels of
    the normalised range [-1, 1]; one unit of that range is 2**(bits-1) - 1 codes.
    """
    ModulationSpec(order)
    return (2.0 / full_scale_levels) * (2 ** (bits - 1) - 1)


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "EVIDENCE_LABELS",
    "BaselineOverrideError",
    "ConfigError",
    "MpamConfig",
    "MpamProfile",
    "check_frame_fit",
    "dac_codes_per_level_step",
    "frame_length_rows",
    "head_symbols",
    "load_mpam_config",
    "rate_equalisation",
]
