"""Keysight M8199B waveform file rules and a dry-run instrument adapter.

Limits come from the M8100 Series Programming Guide as supplied by the project owner.
See docs/HARDWARE_COMPATIBILITY.md for which of them have been verified. This module
never talks to an instrument: there is no real driver and no output-enable path.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field

GRANULARITY_SAMPLES = 512
MAX_SAMPLES = 1_048_576
MIN_SAMPLE_RATE = 200e9
MAX_SAMPLE_RATE = 256e9
DAC_BITS = 8
DATA_OUTPUTS = ("DataOut1", "DataOut2")


class M8199BConstraintError(ValueError):
    """A waveform or profile violates an M8199B rule."""


@dataclass(frozen=True)
class Profile:
    """One experiment profile."""

    name: str
    sample_rate: float
    symbol_rate: float
    symbols: int

    @property
    def sps(self) -> int:
        """Return integer samples per symbol, or raise."""
        ratio = self.sample_rate / self.symbol_rate
        if abs(ratio - round(ratio)) > 1e-9:
            raise M8199BConstraintError(
                f"{self.name}: sample rate / symbol rate = {ratio} is not an integer"
            )
        return int(round(ratio))

    @property
    def samples(self) -> int:
        return self.symbols * self.sps

    @property
    def duration_s(self) -> float:
        return self.samples / self.sample_rate

    def check(self) -> None:
        """Raise if the profile cannot be stored or played by the M8199B rules."""
        if not MIN_SAMPLE_RATE <= self.sample_rate <= MAX_SAMPLE_RATE:
            raise M8199BConstraintError(f"{self.name}: sample rate {self.sample_rate} out of range")
        if self.samples % GRANULARITY_SAMPLES:
            raise M8199BConstraintError(
                f"{self.name}: {self.samples} samples is not a multiple of {GRANULARITY_SAMPLES}"
            )
        if self.samples > MAX_SAMPLES:
            raise M8199BConstraintError(f"{self.name}: {self.samples} exceeds {MAX_SAMPLES}")


def import_command(module: str, data_out: str, segment: int, host_path: str) -> str:
    """Return the import command text for an operator to review. Never sent by this code."""
    if data_out not in DATA_OUTPUTS:
        raise ValueError(f"Unknown data output {data_out!r}")
    return f":TRAC:IMP '{module}.{data_out}', {segment}, \"{host_path}\", CSV"


@dataclass
class MockM8199BAdapter:
    """Dry-run adapter for tests. It records actions and cannot touch hardware."""

    log: list[str] = field(default_factory=list)
    output_enabled: bool = False

    def load(self, samples: int, sample_rate: float) -> None:
        Profile("mock", sample_rate, sample_rate, samples).check()
        self.log.append(f"load {samples} samples at {sample_rate} Sa/s")

    def enable_output(self, explicit_operator_confirmation: bool = False) -> None:
        if not explicit_operator_confirmation:
            raise PermissionError("Output is never enabled without explicit operator confirmation")
        self.output_enabled = True
        self.log.append("output enabled (mock)")
