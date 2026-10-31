"""M-PAM profile configuration (config_schema_version 2) and frame-length checks.

`load_mpam_config` is the only way a run obtains the profiles and the best-fixed menu. The
menu and its entropy deficits are declared in the YAML before any test data is seen; the
loader refuses a file whose deficits differ from the values pinned in code, and
`MpamConfig.reported_fixed_menu` builds the baseline only from them, so a reported baseline
cannot be changed by an argument at run time. The export enforces it: a BestFixed that is not
`reportable`, or not exactly a member of the pinned menu, is refused
(`export.require_reportable_baseline`), and the manifest carries the flag.

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
PROTOCOLS = ("A", "B")
CONSTRAINT_PROTOCOLS = (
    "fixed_peak",
    "fixed_average_optical_power",
    "fixed_OMA",
    "equal_realized_user_rate",
)
METRICS = ("smd", "bmd")
_TOP_KEYS = {
    "config_schema_version",
    "common",
    "fixed_menu",
    "adaptive",
    "protocol_A",
    "protocol_B",
}
_COMMON_KEYS = {
    "seed",
    "block_length",
    "pulse",
    "data_out",
    "decimals",
    "sample_rate_Sa_per_s",
    "constraint_protocol",
}
_PULSE_KEYS = {"shape", "roll_off", "boundary"}
_MENU_KEYS = {"members", "entropy_deficits_bits"}
_ADAPTIVE_KEYS = {"metric", "training_samples", "training_acquisitions", "design_rate_bpcu"}
_PROFILE_KEYS = {"name", "symbol_rate_Bd", "symbols"}
_PROTOCOL_B_KEYS = {"nominal_bit_rate_bps", "samples_per_symbol", "symbols"}
_DESIGN_ORDERS = (8, 16)
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
    """The validated contents of configs/mpam_profiles.yaml.

    There is no evidence label: the generator writes synthetic waveforms only and labels them
    "simulated" itself (`export.EVIDENCE`), so the label is not a file setting.
    """

    sha256: str
    seed: int
    block_length: int
    pulse: PulseConfig
    data_out: str
    decimals: int
    sample_rate: float
    constraint_protocol: str
    fixed_deficits: tuple[float, ...]
    adaptive: Mapping[str, Any]
    profiles: tuple[MpamProfile, ...]

    def reported_fixed_menu(self, order: int) -> dict[str, tuple[float, ...]]:
        """The best-fixed menu of this config: the only one a report may call the baseline."""
        return fixed_menu(order, self.fixed_deficits)

    def profiles_for(self, order: int) -> list[MpamProfile]:
        return [p for p in self.profiles if p.order == order]


def _mapping(value: Any, where: str, keys: set[str]) -> Mapping[str, Any]:
    """`value` must be a mapping with exactly `keys`: a missing or an unknown key is refused."""
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where}: must be a mapping, got {type(value).__name__}")
    missing = sorted(keys - set(value))
    if missing:
        raise ConfigError(f"{where}: missing keys {missing}")
    unknown = sorted(set(value) - keys, key=str)
    if unknown:
        raise ConfigError(f"{where}: unknown keys {unknown}")
    return value


def _number(value: Any, where: str, *, integer: bool = False, positive: bool = True) -> Any:
    """A finite number (an int if `integer`), positive unless `positive` is False.

    PyYAML reads `224.0e9` (no sign in the exponent) as a string, so a numeral string that
    `float` accepts is taken as the number it spells.
    """
    kind = "integer" if integer else "number"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{where}: must be a finite {kind}, got {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise ConfigError(f"{where}: must be a finite {kind}, got {value!r}") from None
    if not np.isfinite(number) or (integer and not number.is_integer()):
        raise ConfigError(f"{where}: must be a finite {kind}, got {value!r}")
    if positive and not number > 0:
        raise ConfigError(f"{where}: must be positive, got {value!r}")
    return int(number) if integer else number


def _by_order(value: Any, where: str, orders: tuple[int, ...], *, integer: bool) -> dict[int, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where}: must be a mapping from order to a number")
    if set(value) != set(orders):
        raise ConfigError(f"{where}: keys must be exactly {list(orders)}, got {list(value)}")
    return {o: _number(value[o], f"{where}[{o}]", integer=integer) for o in orders}


def load_mpam_config(path: Path) -> MpamConfig:
    """Read and validate the M-PAM profile YAML.

    Default-deny at every nesting level: an unknown version, an unknown or missing key
    anywhere, an enum value outside its set (`data_out`, `constraint_protocol`, `metric`,
    pulse settings) and the removed `evidence` key are all refused with a `ConfigError`.
    """
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
    common = _mapping(_require(config, "common", "config"), "common", _COMMON_KEYS)
    if common["data_out"] not in DATA_OUTPUTS:
        raise ConfigError(f"data_out must be one of {DATA_OUTPUTS}")
    if common["constraint_protocol"] not in CONSTRAINT_PROTOCOLS:
        raise ConfigError(f"constraint_protocol must be one of {CONSTRAINT_PROTOCOLS}")
    pulse = _mapping(common["pulse"], "common.pulse", _PULSE_KEYS)
    try:
        pulse_config = PulseConfig(**pulse)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"common.pulse: {error}") from error
    seed = _number(common["seed"], "common.seed", integer=True, positive=False)
    block_length = _number(common["block_length"], "common.block_length", integer=True)
    decimals = _number(common["decimals"], "common.decimals", integer=True)
    sample_rate = _number(common["sample_rate_Sa_per_s"], "common.sample_rate_Sa_per_s")
    menu = _mapping(_require(config, "fixed_menu", "config"), "fixed_menu", _MENU_KEYS)
    raw_deficits = menu["entropy_deficits_bits"]
    if not isinstance(raw_deficits, list):
        raise ConfigError("fixed_menu.entropy_deficits_bits: must be a list")
    deficits = tuple(
        _number(x, "fixed_menu.entropy_deficits_bits", positive=False) for x in raw_deficits
    )
    if menu["members"] != _MENU_MEMBERS or deficits != DEFAULT_FIXED_DEFICITS:
        raise BaselineOverrideError(
            f"the pinned best-fixed menu is {_MENU_MEMBERS} at deficits "
            f"{DEFAULT_FIXED_DEFICITS} bit; the file declares {menu['members']} at {deficits}. "
            "A reported baseline cannot be changed by configuration or argument"
        )
    adaptive = _mapping(_require(config, "adaptive", "config"), "adaptive", _ADAPTIVE_KEYS)
    if adaptive["metric"] not in METRICS:
        raise ConfigError(f"adaptive.metric must be one of {METRICS}")
    _number(adaptive["training_samples"], "adaptive.training_samples", integer=True)
    _number(adaptive["training_acquisitions"], "adaptive.training_acquisitions", integer=True)
    _by_order(
        adaptive["design_rate_bpcu"], "adaptive.design_rate_bpcu", _DESIGN_ORDERS, integer=False
    )
    profiles: list[MpamProfile] = []
    protocol_a = _mapping(_require(config, "protocol_A", "config"), "protocol_A", {"profiles"})
    entries = protocol_a["profiles"]
    if not isinstance(entries, list) or not entries:
        raise ConfigError("protocol_A.profiles: must be a non-empty list")
    for entry in entries:
        entry = _mapping(entry, "protocol_A.profiles[]", _PROFILE_KEYS)
        for order in SUPPORTED_ORDERS:
            profiles.append(
                MpamProfile(
                    "A",
                    f"{entry['name']}_PAM{order}",
                    order,
                    sample_rate,
                    _number(entry["symbol_rate_Bd"], "protocol_A.symbol_rate_Bd"),
                    _number(entry["symbols"], "protocol_A.symbols", integer=True),
                )
            )
    b = _mapping(_require(config, "protocol_B", "config"), "protocol_B", _PROTOCOL_B_KEYS)
    nominal = _number(b["nominal_bit_rate_bps"], "protocol_B.nominal_bit_rate_bps")
    sps_by_order = _by_order(
        b["samples_per_symbol"], "protocol_B.samples_per_symbol", SUPPORTED_ORDERS, integer=True
    )
    symbols_by_order = _by_order(b["symbols"], "protocol_B.symbols", SUPPORTED_ORDERS, integer=True)
    for order in SUPPORTED_ORDERS:
        sps = sps_by_order[order]
        baud = nominal / ModulationSpec(order).bits_per_symbol
        if abs(sample_rate / baud - sps) > 1e-9:
            raise ConfigError(
                f"protocol B PAM{order}: {nominal / 1e9:g} Gb/s needs {sample_rate / baud:g} "
                f"samples per symbol at {sample_rate / 1e9:g} GSa/s, not {sps}"
            )
        profiles.append(
            MpamProfile(
                "B", f"B_112G_PAM{order}", order, sample_rate, baud, symbols_by_order[order]
            )
        )
    return MpamConfig(
        sha256=hashlib.sha256(raw).hexdigest(),
        seed=seed,
        block_length=block_length,
        pulse=pulse_config,
        data_out=common["data_out"],
        decimals=decimals,
        sample_rate=sample_rate,
        constraint_protocol=str(common["constraint_protocol"]),
        fixed_deficits=deficits,
        adaptive=adaptive,
        profiles=tuple(profiles),
    )


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}: missing key {key!r}")
    return mapping[key]


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
    target_bps: float | None = None,
) -> list[dict[str, Any]]:
    """Report, per menu member, the sample rate that would equalise its realised user rate.

    By default the target is the direct uniform of the same order (log2 M bits per symbol, no
    matcher): a same-order comparison. Pass `target_bps` for a common target across orders
    (see `pam4_uniform_rate_bps`). Each row is evaluated as if the adjustment were declared; it
    is only REPORTED here (`applied` is always False): no waveform is resampled or re-clocked.
    A member whose required rate leaves 200 to 256 GSa/s is INFEASIBLE.
    """
    spec = ModulationSpec(order)
    payload = symbols - spec.head_symbols
    uniform_bits = spec.bits_per_symbol * block_length
    target = (
        FrameAccounting(spec.head_symbols, payload, block_length, uniform_bits, sps).user_rate_bps(
            nominal_sample_rate
        )
        if target_bps is None
        else target_bps
    )
    constraint = EqualRealizedUserRate(
        target, nominal_sample_rate_hz=nominal_sample_rate, allow_sample_rate_adjustment=True
    )
    rows = []
    for name, p in menu.items():
        pmf = np.asarray(p, dtype=float)
        direct = bool(np.max(np.abs(pmf - 1.0 / order)) <= 1e-12)
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


def pam4_uniform_rate_bps(config: MpamConfig, profile: MpamProfile) -> float:
    """Realised user rate of the PAM4 direct uniform of the same protocol and symbol rate.

    The common target of the cross-order comparison (Protocol B matches realised rate including
    the head overhead): 2 bit per symbol, head 1024, no matcher loss. `profile` is any profile
    of the stem (for example `B_112G_PAM8`); its PAM4 sibling is read from the config.
    """
    stem = profile.name.rsplit("_PAM", 1)[0]
    sibling = next(p for p in config.profiles if p.name == f"{stem}_PAM4")
    spec = ModulationSpec(4)
    accounting = FrameAccounting(
        spec.head_symbols,
        sibling.symbols - spec.head_symbols,
        config.block_length,
        spec.bits_per_symbol * config.block_length,
        sibling.sps,
    )
    return accounting.user_rate_bps(sibling.sample_rate)


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
    "CONSTRAINT_PROTOCOLS",
    "METRICS",
    "BaselineOverrideError",
    "ConfigError",
    "MpamConfig",
    "MpamProfile",
    "check_frame_fit",
    "dac_codes_per_level_step",
    "frame_length_rows",
    "head_symbols",
    "load_mpam_config",
    "pam4_uniform_rate_bps",
    "rate_equalisation",
]
