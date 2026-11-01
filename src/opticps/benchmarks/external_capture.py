"""Read-only reader for external oscilloscope captures (Stage 3A, gate E1). Offline.

What this module does and does not promise.

* It never writes, moves or fetches anything. A capture is mapped read-only (`numpy.memmap`, mode
  "r"), the original bytes stay where they are, and `ExternalCapture.raw_bytes` returns slices of
  those same bytes. Samples are handed out block by block as float64 copies, so a 164 MB file is
  never duplicated in memory.
* The format is never assumed. `parse_keysight_bin_header` checks the documented Keysight BIN
  layout field by field against the actual file size, and refuses with `FORMAT_UNKNOWN` unless every
  structural redundancy agrees (cookie, file size, header sizes, buffer size against point count,
  no bytes before or after the structure). `evaluate_hypotheses` decodes the same bytes under many
  independent hypotheses (dtype, byte order, header offset) and applies physical checks (finite,
  bounded, smooth, band-limited, not clipped). A hypothesis is accepted only if it is the single
  survivor. A pleasing plot is not a check.
* The vertical scale is always `normalized`. The header of a Keysight file names a unit (Volt); this
  module records that claim as a header field and never reports volts, millivolts, dBm or optical
  power. No sample is converted to any physical unit.
* This module has no BER, SER or post-FEC code; those are in `capture_stats` and refuse without a
  published reference sequence.
* `ExternalCapture.open_keysight_bin` and `open_raw` are generic: they check structure (and, for a
  raw layout, the physical checks on slices), hash the file, and know nothing about which file is a
  holdout. The holdout rule lives in `opticps.benchmarks.teriphic.gate_sample_read`, which every
  sample-reading route of the CLI and the TERIPHIC adapter passes first. Calling an `open_*`
  constructor or `opticps.measurement.uxr_import.read_bin` directly on a holdout is not refused here
  (listed in `docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md`). Structure alone is never a verdict:
  `ExternalCapture.coverage_scan` (every block of the whole record) gives the physical pass,
  reported separately; `full_scan` and the three-slice `physical_checks` are narrower tools.

The Keysight layout used here is the one `opticps.measurement.uxr_import.read_bin` cites (UXR
Programmer's Guide, BIN file format). The parser below is written separately from `read_bin` on
purpose: it reads only the 164 header bytes and maps the rest instead of loading the file.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.benchmarks.provenance import (
    BenchmarkError,
    Checksum,
    ErrorCode,
    Md5State,
    verify_local_asset,
)

FloatArray = NDArray[np.float64]

SCALE_NORMALIZED = "normalized"
DEFAULT_BLOCK_SAMPLES = 1 << 20
MAX_BLOCK_SAMPLES = 1 << 24

# Keysight BIN, documented layout (little-endian, structs packed to 4 bytes).
_FILE_HEADER = struct.Struct("<2s2sii")  # cookie, version, file size, waveform count
_WAVE_HEADER = struct.Struct("<iiiiifdddii16s16s24s16sdI")
_DATA_HEADER = struct.Struct("<ihhi")  # header size, buffer type, bytes per point, buffer size
KEYSIGHT_HEADER_BYTES = _FILE_HEADER.size + _WAVE_HEADER.size + _DATA_HEADER.size  # 164
_X_INCREMENT_RANGE_S = (1e-14, 1e-3)  # sample rates from 1 kHz to 100 THz
SCALE_ABS_MAX = 1e6  # file units: a header that says Volt cannot hold a megavolt waveform
SCALE_STD_MIN = 1e-12  # file units: a spread below a picovolt is not a waveform
_ALLOWED_DTYPES = frozenset(
    {
        "|i1",
        "|u1",
        "<i2",
        ">i2",
        "<u2",
        ">u2",
        "<i4",
        ">i4",
        "<u4",
        ">u4",
        "<f4",
        ">f4",
        "<f8",
        ">f8",
    }
)


COVERAGE_BLOCK_SAMPLES = 1 << 16
MIN_BLOCK_SAMPLES = 4096
BLOCK_CHECK_NAMES = (
    "finite",
    "plausible_scale",
    "spike_vs_record_scale",
    "spread_vs_record_scale",
    "smooth",
    "band_limited",
    "continuous",
    "not_clipped",
    "non_degenerate",
)
# Block thresholds, set on the B2B file only (plan Revision 7 states the B2B values and margins).
BLOCK_LAG1_MIN = 0.5
BLOCK_BAND_DB_MAX = -20.0
BLOCK_JUMP_MAX = 1.5
BLOCK_RAIL_MAX = 1e-3
BLOCK_DISTINCT_MIN = 16
BLOCK_SPIKE_MAX = 8.0  # largest deviation from the block median over the record scale
BLOCK_SPREAD_MIN = 0.5  # block robust spread over the record scale
BLOCK_SPREAD_MAX = 2.0


class FormatStatus(StrEnum):
    """Outcome of a format verification. There is no state between these two."""

    FORMAT_UNKNOWN = "FORMAT_UNKNOWN"  # reported as BLOCKED: FORMAT_UNVERIFIED
    SUPPORTED_BY_EVIDENCE = "SUPPORTED_BY_EVIDENCE"


@dataclass(frozen=True)
class FormatCheck:
    """One named check with its outcome. `fatal` checks refuse the file when they fail."""

    name: str
    passed: bool
    detail: str
    fatal: bool = True


def format_unknown(message: str) -> BenchmarkError:
    return BenchmarkError(message, ErrorCode.FORMAT_UNKNOWN)


@dataclass(frozen=True)
class SampleLayout:
    """Where the samples are and how to decode them. Scale is always `normalized`."""

    container: str  # "keysight_bin" or "raw"
    dtype: str  # numpy type string with an explicit byte order
    data_offset: int
    count: int
    x_increment_s: float | None
    x_origin_s: float | None
    scale: str = SCALE_NORMALIZED
    header_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.dtype not in _ALLOWED_DTYPES:
            raise format_unknown(f"dtype {self.dtype!r} is not one of {sorted(_ALLOWED_DTYPES)}")
        if self.scale != SCALE_NORMALIZED:
            raise format_unknown(
                f"scale {self.scale!r} is not accepted: samples are `normalized` unless a "
                "document states a calibration, and none is implemented"
            )
        if type(self.data_offset) is not int or self.data_offset < 0:
            raise format_unknown(f"data offset {self.data_offset!r} is not a non-negative integer")
        if type(self.count) is not int or self.count < 2:
            raise format_unknown(f"sample count {self.count!r} is not an integer of at least 2")
        for name in ("x_increment_s", "x_origin_s"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise format_unknown(f"{name} is not finite: {value!r}")
        if self.x_increment_s is not None:
            low, high = _X_INCREMENT_RANGE_S
            if not low <= self.x_increment_s <= high:
                raise format_unknown(
                    f"time increment {self.x_increment_s!r} s is outside the plausible range "
                    f"{low} to {high} s"
                )
        object.__setattr__(self, "header_fields", MappingProxyType(dict(self.header_fields)))

    @property
    def itemsize(self) -> int:
        return int(np.dtype(self.dtype).itemsize)

    @property
    def end_offset(self) -> int:
        return self.data_offset + self.count * self.itemsize

    @property
    def sample_rate_hz(self) -> float | None:
        return None if self.x_increment_s is None else 1.0 / self.x_increment_s


def _text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _frame_model_claim(raw: bytes) -> str:
    """The model part of the header frame string (text before the first colon).

    Whatever follows the colon (an instrument serial in the file this was written for) is neither
    kept in the layout nor printed: the model is a claim made by the file header about the
    exporting instrument, not evidence of an instrument.
    """
    return _text(raw).split(":", 1)[0].strip()


def parse_keysight_bin_header(
    head: bytes, file_size: int
) -> tuple[SampleLayout, tuple[FormatCheck, ...]]:
    """Check the first 164 bytes against the documented layout and the real file size.

    Returns the layout and every check. Any failed fatal check raises FORMAT_UNKNOWN naming it:
    wrong cookie or version, a size field that is not the file size, more or fewer than one
    waveform, header or data-header sizes other than the documented 140 and 12, a buffer that is not
    4-byte float, a buffer size that is not 4 times the point count, bytes before or after the
    structure, units other than Volt and Second, an implausible time increment, and a display range
    that disagrees with points times increment by more than 0.1 % (a header inconsistent with
    itself). This is structure only; the physical pass is separate.
    """
    if len(head) < KEYSIGHT_HEADER_BYTES or file_size < KEYSIGHT_HEADER_BYTES:
        raise format_unknown(
            f"file has {file_size} bytes; a Keysight BIN header alone is {KEYSIGHT_HEADER_BYTES}"
        )
    cookie, version, size_field, waveforms = _FILE_HEADER.unpack_from(head, 0)
    fields = _WAVE_HEADER.unpack_from(head, _FILE_HEADER.size)
    (
        header_size,
        wave_type,
        buffers,
        points,
        averages,
        x_range,
        x_display,
        x_inc,
        x_org,
        x_units,
        y_units,
        date,
        clock,
        frame,
        label,
        time_tag,
        segment,
    ) = fields
    data_header_size, buffer_type, width, buffer_size = _DATA_HEADER.unpack_from(
        head, _FILE_HEADER.size + _WAVE_HEADER.size
    )
    start = KEYSIGHT_HEADER_BYTES
    low, high = _X_INCREMENT_RANGE_S
    span = points * x_inc if points > 0 else float("nan")
    checks = (
        FormatCheck("cookie", cookie == b"AG", f"cookie {cookie!r}, documented b'AG'"),
        FormatCheck("version", version == b"10", f"version {version!r}, documented b'10'"),
        FormatCheck(
            "file_size_field", size_field == file_size, f"field {size_field}, file {file_size}"
        ),
        FormatCheck(
            "one_waveform", waveforms == 1, f"{waveforms} waveforms declared; only 1 is read"
        ),
        FormatCheck(
            "waveform_header_size",
            header_size == _WAVE_HEADER.size,
            f"{header_size}, documented 140",
        ),
        FormatCheck(
            "waveform_type", wave_type in (1, 3), f"type {wave_type}; 1 (normal) or 3 (average)"
        ),
        FormatCheck("one_buffer", buffers == 1, f"{buffers} buffers"),
        FormatCheck(
            "data_header_size",
            data_header_size == _DATA_HEADER.size,
            f"{data_header_size}, documented 12",
        ),
        FormatCheck(
            "buffer_type_float32",
            buffer_type == 1,
            f"buffer type {buffer_type}, documented 1 = float",
        ),
        FormatCheck("bytes_per_point", width == 4, f"{width} bytes per point"),
        FormatCheck(
            "buffer_size_is_4_points",
            points > 0 and buffer_size == 4 * points,
            f"buffer {buffer_size} bytes, points {points}",
        ),
        FormatCheck(
            "no_bytes_outside_structure",
            start + buffer_size == file_size,
            f"header+data end at {start + buffer_size}, file ends at {file_size}",
        ),
        FormatCheck(
            "units_volt_second",
            y_units == 1 and x_units == 2,
            f"Y unit code {y_units}, X unit code {x_units}",
        ),
        FormatCheck(
            "time_increment_plausible",
            math.isfinite(x_inc) and low <= x_inc <= high,
            f"{x_inc!r} s, accepted {low} to {high}",
        ),
        FormatCheck("time_origin_finite", math.isfinite(x_org), f"{x_org!r}"),
        FormatCheck(
            "display_range_matches_record",
            math.isfinite(span) and x_range > 0 and abs(span / x_range - 1) < 1e-3,
            f"points*increment {span!r} s, display range {x_range!r} s",
        ),
        FormatCheck(
            "header_strings_ascii",
            all(r.split(b"\x00", 1)[0].isascii() for r in (date, clock, frame, label)),
            f"date {_text(date)!r}, time {_text(clock)!r}, frame model claim "
            f"{_frame_model_claim(frame)!r}, label {_text(label)!r}",
            fatal=False,
        ),
    )
    failed = [c for c in checks if c.fatal and not c.passed]
    if failed:
        raise format_unknown(
            "not a Keysight BIN this reader accepts: "
            + "; ".join(f"{c.name} ({c.detail})" for c in failed)
        )
    layout = SampleLayout(
        container="keysight_bin",
        dtype="<f4",
        data_offset=start,
        count=int(points),
        x_increment_s=float(x_inc),
        x_origin_s=float(x_org),
        header_fields={
            "cookie": cookie.decode("ascii"),
            "version": version.decode("ascii"),
            "waveform_type": wave_type,
            "average_count": averages,
            "x_display_range_s": x_range,
            "x_display_origin_s": x_display,
            "header_y_unit": "Volt (header claim; not a calibration, samples stay normalized)",
            "date": _text(date),
            "time": _text(clock),
            "frame_model_claim": _frame_model_claim(frame),
            "frame_model_claim_note": (
                "text before the colon of the header frame string: a header claim about the "
                "exporting model, not instrument evidence; the remainder is not recorded"
            ),
            "label": _text(label),
            "time_tag": time_tag,
            "segment_index": segment,
        },
    )
    return layout, checks


def waveform_checks(x: FloatArray) -> tuple[FormatCheck, ...]:
    """Physical plausibility of decoded samples; each check is independent of the layout.

    finite, bounded (no wild outliers relative to the spread), smooth (lag-1 autocorrelation of an
    oversampled band-limited waveform is high), band-limited (the top 40 % of the spectrum is 20 dB
    below the peak), continuous (a sampled band-limited waveform does not jump by more than a
    standard deviation between neighbours; the bit pattern of a float read as an integer jumps at
    every sign change), not clipped (at most 0.1 % of samples at the extremes), and
    non-degenerate (at
    least 16 distinct values), and of plausible scale (largest magnitude at most 1e6 and spread at
    least 1e-12 in file units: an absurdly scaled but smooth signal is not a measurement). Random
    bytes, a wrong byte order or a wrong width fail at least one.
    """
    with np.errstate(all="ignore"):
        return _waveform_checks(x)


def _upper_band_db(centred: FloatArray) -> float:
    """Mean density of the top 40 % of the spectrum relative to the peak, in dB (Hann, 1024)."""
    nseg = 1024
    count = centred.size // nseg
    segments = centred[: count * nseg].reshape(count, nseg) * np.hanning(nseg + 1)[:nseg]
    psd = (np.abs(np.fft.rfft(segments, axis=1)) ** 2).mean(axis=0)
    upper = float(psd[int(0.6 * psd.size) :].mean())
    return 10.0 * math.log10(max(upper, 1e-300) / float(psd.max()))


def _waveform_checks(x: FloatArray) -> tuple[FormatCheck, ...]:
    if x.size < 4096:
        return (FormatCheck("enough_samples", False, f"{x.size} samples; at least 4096 needed"),)
    finite = bool(np.all(np.isfinite(x)))
    if not finite:
        return (FormatCheck("finite", False, f"{int((~np.isfinite(x)).sum())} non-finite values"),)
    centred = x - x.mean()
    std = float(centred.std())
    distinct = int(np.unique(x).size)
    if not std > 0:
        return (
            FormatCheck("finite", True, "all finite"),
            FormatCheck("non_degenerate", False, "zero spread"),
        )
    outlier = float(np.abs(x - np.median(x)).max() / std)
    lag1 = float(np.dot(centred[:-1], centred[1:]) / np.dot(centred, centred))
    ratio_db = _upper_band_db(centred)
    rail = float(((x == x.max()).sum() + (x == x.min()).sum()) / x.size)
    jump = float(np.quantile(np.abs(np.diff(x)), 0.999) / std)
    peak = float(np.abs(x).max())
    return (
        FormatCheck("finite", True, "all finite"),
        FormatCheck(
            "plausible_scale",
            peak <= SCALE_ABS_MAX and std >= SCALE_STD_MIN,
            f"largest magnitude {peak:.3g}, spread {std:.3g} file units "
            f"(limits {SCALE_ABS_MAX:g} and {SCALE_STD_MIN:g})",
        ),
        FormatCheck(
            "bounded",
            outlier <= 20.0,
            f"largest deviation {outlier:.3g} standard deviations (limit 20)",
        ),
        FormatCheck("smooth", lag1 >= 0.5, f"lag-1 autocorrelation {lag1:.4f} (limit 0.5)"),
        FormatCheck(
            "band_limited",
            ratio_db <= -20.0,
            f"top 40% of band {ratio_db:.1f} dB below the peak (limit -20)",
        ),
        FormatCheck(
            "continuous",
            jump <= 1.5,
            f"99.9th percentile of |first difference| {jump:.3g} standard deviations (limit 1.5)",
        ),
        FormatCheck(
            "not_clipped", rail <= 1e-3, f"{rail:.2e} of samples at the extremes (limit 1e-3)"
        ),
        FormatCheck("non_degenerate", distinct >= 16, f"{distinct} distinct values (limit 16)"),
    )


@dataclass(frozen=True)
class Hypothesis:
    """One independent byte-level reading of a file."""

    dtype: str
    data_offset: int
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or f"{self.dtype}@{self.data_offset}"


@dataclass(frozen=True)
class HypothesisResult:
    hypothesis: Hypothesis
    checks: tuple[FormatCheck, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.checks if not c.passed)


def default_hypotheses(declared: SampleLayout | None = None) -> tuple[Hypothesis, ...]:
    """dtype x byte order x header offset, including the sizes the file size suggests.

    The offsets are 0, the 136 bytes that the file size alone suggests for 4-byte samples, the
    structurally declared offset (when a header was parsed) and one-to-three-byte misalignments of
    the declared offset.
    """
    offsets = [0, 136]
    if declared is not None:
        offsets += [declared.data_offset + k for k in (0, 1, 2, 3)]
    out = []
    for dtype in sorted(_ALLOWED_DTYPES):
        for offset in dict.fromkeys(offsets):
            out.append(Hypothesis(dtype, offset))
    return tuple(out)


def evaluate_hypotheses(
    path: Path,
    hypotheses: Sequence[Hypothesis],
    *,
    declared: SampleLayout | None = None,
    window_bytes: int = 1 << 21,
    windows: int = 3,
) -> tuple[HypothesisResult, ...]:
    """Decode up to `windows` slices of the file under each hypothesis and run the checks.

    The slices are taken at the start, the middle and the end of the data region (so a header-only
    structure cannot pass for the whole record). When `declared` is given, one more check,
    `matches_declared_structure`, requires the hypothesis to equal the structurally declared dtype
    and offset: the statistical checks cannot tell a 136-byte offset from a 164-byte one for 4-byte
    samples (28 bytes are seven samples), so only structure decides between them.
    """
    size = path.stat().st_size
    results = []
    with path.open("rb") as handle:
        for hypothesis in hypotheses:
            itemsize = int(np.dtype(hypothesis.dtype).itemsize)
            usable = size - hypothesis.data_offset
            checks: list[FormatCheck] = []
            parts: list[FloatArray] = []
            if usable < 4096 * itemsize:
                checks.append(FormatCheck("enough_samples", False, "file too short"))
            else:
                span = min(window_bytes, usable) // itemsize * itemsize
                starts = np.linspace(0, usable - span, windows).astype(np.int64)
                starts -= starts % itemsize
                for begin in starts:
                    handle.seek(hypothesis.data_offset + int(begin))
                    raw = handle.read(span)
                    with np.errstate(all="ignore"):
                        parts.append(np.frombuffer(raw, dtype=hypothesis.dtype).astype(np.float64))
                for index, part in enumerate(parts):
                    for check in waveform_checks(part):
                        if not check.passed:
                            checks.append(
                                FormatCheck(check.name, False, f"window {index}: {check.detail}")
                            )
                if not checks:
                    checks.append(FormatCheck("physical_checks", True, "all windows pass"))
            if declared is not None:
                same = (hypothesis.dtype, hypothesis.data_offset) == (
                    declared.dtype,
                    declared.data_offset,
                )
                checks.append(
                    FormatCheck(
                        "matches_declared_structure",
                        same,
                        f"declared {declared.dtype}@{declared.data_offset}",
                    )
                )
            results.append(HypothesisResult(hypothesis, tuple(checks)))
    return tuple(results)


def unique_survivor(results: Sequence[HypothesisResult]) -> Hypothesis:
    """The single hypothesis passing every check, else FORMAT_UNKNOWN (none, or ambiguous)."""
    passing = [r for r in results if r.passed]
    if not passing:
        raise format_unknown("no byte-level hypothesis passes the physical checks")
    if len(passing) > 1:
        names = ", ".join(r.hypothesis.name for r in passing)
        raise format_unknown(f"ambiguous format: {len(passing)} hypotheses pass ({names})")
    return passing[0].hypothesis


@dataclass(frozen=True)
class RawSpec:
    """Layout of a non-Keysight file, from a sidecar JSON or built in code. Scale: normalized."""

    dtype: str
    data_offset: int = 0
    count: int | None = None
    x_increment_s: float | None = None
    scale: str = SCALE_NORMALIZED

    _KEYS = frozenset({"dtype", "data_offset", "count", "x_increment_s", "scale"})

    @classmethod
    def from_sidecar(cls, path: Path) -> RawSpec:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:  # its message would quote a byte value of the file
            raise format_unknown(f"{path.name}: sidecar is not UTF-8 text") from None
        except (OSError, ValueError) as error:
            raise format_unknown(f"{path.name}: sidecar cannot be read as JSON: {error}") from error
        if not isinstance(document, dict) or not document or set(document) - cls._KEYS:
            extra = (
                sorted(map(str, set(document) - cls._KEYS))
                if isinstance(document, dict)
                else f"a JSON {type(document).__name__}, not an object"
            )
            raise format_unknown(
                f"{path.name}: sidecar keys must be among {sorted(cls._KEYS)}: {extra}"
            )
        if "dtype" not in document:
            raise format_unknown(f"{path.name}: sidecar has no dtype")
        if type(document["dtype"]) is not str:
            raise format_unknown(f"{path.name}: dtype must be a string")
        if "scale" in document and type(document["scale"]) is not str:
            raise format_unknown(f"{path.name}: scale must be a string")
        for key in ("data_offset", "count"):
            if key in document and (type(document[key]) is not int):
                raise format_unknown(f"{path.name}: {key} must be an integer")
        for key in ("x_increment_s",):
            if key in document and (
                isinstance(document[key], bool) or not isinstance(document[key], (int, float))
            ):
                raise format_unknown(f"{path.name}: {key} must be a number")
        return cls(**document)


class ExternalCapture:
    """A read-only view of one capture file. Build it with the `open_*` constructors.

    "Verified" would overstate it: `open_keysight_bin` checks the header structure against the file
    size and hashes the file, and runs no physical check on the samples; `open_raw` runs the
    three-slice checks only. The physical pass is `coverage_scan`, called separately.
    """

    def __init__(self, path: Path, layout: SampleLayout, checksum: Checksum | None) -> None:
        self.path = path
        self.layout = layout
        self.checksum = checksum
        size = path.stat().st_size
        if layout.end_offset > size:
            raise format_unknown(f"layout ends at byte {layout.end_offset}, file has {size}")
        self._bytes = np.memmap(path, dtype=np.uint8, mode="r")
        self._samples = np.ndarray(
            (layout.count,), dtype=layout.dtype, buffer=self._bytes, offset=layout.data_offset
        )
        self._samples.flags.writeable = False

    # ------------------------------------------------------------------ constructors
    @classmethod
    def open_keysight_bin(
        cls,
        path: Path,
        *,
        md5_supplied: str | None = None,
        checksum: Checksum | None = None,
    ) -> ExternalCapture:
        """Hash the file, parse the header structurally, map the samples. Refuses anything else."""
        path = Path(path)
        checksum = _hashed(path, md5_supplied, checksum)
        with path.open("rb") as handle:
            head = handle.read(KEYSIGHT_HEADER_BYTES)
        layout, _ = parse_keysight_bin_header(head, path.stat().st_size)
        return cls(path, layout, checksum)

    @classmethod
    def open_raw(
        cls,
        path: Path,
        spec: RawSpec,
        *,
        md5_supplied: str | None = None,
        checksum: Checksum | None = None,
        verify: bool = True,
    ) -> ExternalCapture:
        """Open a file under an explicit layout, then run the physical checks on it.

        A size that is not a whole number of samples after the offset is refused (trailing bytes
        are not explained). With `verify` False the checks are skipped; only the hypothesis
        evaluation code uses that.
        """
        path = Path(path)
        checksum = _hashed(path, md5_supplied, checksum)
        size = path.stat().st_size
        itemsize = int(np.dtype(spec.dtype).itemsize) if spec.dtype in _ALLOWED_DTYPES else 0
        if itemsize == 0:
            raise format_unknown(f"dtype {spec.dtype!r} is not supported")
        usable = size - spec.data_offset
        if usable <= 0 or (spec.count is None and usable % itemsize):
            raise format_unknown(
                f"{usable} bytes after offset {spec.data_offset} are not a whole number of "
                f"{spec.dtype} samples"
            )
        count = spec.count if spec.count is not None else usable // itemsize
        if spec.count is not None and spec.data_offset + count * itemsize != size:
            raise format_unknown(
                f"declared {count} samples end at byte {spec.data_offset + count * itemsize}, "
                f"file has {size}: truncated or trailing bytes"
            )
        layout = SampleLayout(
            "raw", spec.dtype, spec.data_offset, count, spec.x_increment_s, None, spec.scale
        )
        capture = cls(path, layout, checksum)
        if verify:
            failed = [c for c in capture.physical_checks() if not c.passed]
            if failed:
                capture.close()
                raise format_unknown(
                    f"{path.name} does not decode as {spec.dtype}@{spec.data_offset}: "
                    + "; ".join(f"{c.name} ({c.detail})" for c in failed)
                )
        return capture

    # ------------------------------------------------------------------ access
    @property
    def count(self) -> int:
        return self.layout.count

    @property
    def scale(self) -> str:
        return self.layout.scale

    def close(self) -> None:
        mmap = getattr(self._bytes, "_mmap", None)
        if mmap is not None and not mmap.closed:
            del self._samples
            mmap.close()

    def raw_bytes(self, start: int = 0, stop: int | None = None) -> bytes:
        """A copy of file bytes [start, stop); the file itself is never changed."""
        return bytes(self._bytes[start:stop])

    def assert_unchanged(self) -> None:
        """Refuse to read if the file changed since it was hashed (size or modification time)."""
        if self.checksum is not None and not self.checksum.still_current(self.path):
            raise BenchmarkError(f"{self.path.name} changed after it was hashed; hash it again")

    def blocks(
        self, block_samples: int = DEFAULT_BLOCK_SAMPLES, start: int = 0, stop: int | None = None
    ) -> Iterator[tuple[int, FloatArray]]:
        """Yield (first index, float64 copy of the block). One block is alive at a time."""
        if type(block_samples) is not int or not 16 <= block_samples <= MAX_BLOCK_SAMPLES:
            raise BenchmarkError(f"block_samples must be an integer in [16, {MAX_BLOCK_SAMPLES}]")
        stop = self.count if stop is None else stop
        if not 0 <= start < stop <= self.count:
            raise BenchmarkError(f"range [{start}, {stop}) is not inside [0, {self.count})")
        self.assert_unchanged()
        for first in range(start, stop, block_samples):
            last = min(first + block_samples, stop)
            with np.errstate(
                all="ignore"
            ):  # a wrong layout may hold bit patterns that are not floats
                yield first, np.asarray(self._samples[first:last], dtype=np.float64)

    def read(self, start: int, stop: int) -> FloatArray:
        """One slice as float64 (the caller keeps it small)."""
        if not 0 <= start < stop <= self.count:
            raise BenchmarkError(f"range [{start}, {stop}) is not inside [0, {self.count})")
        self.assert_unchanged()
        with np.errstate(all="ignore"):
            return np.asarray(self._samples[start:stop], dtype=np.float64)

    def full_scan(self, block_samples: int = DEFAULT_BLOCK_SAMPLES) -> tuple[FormatCheck, ...]:
        """Every sample, once: all finite, and a plausible scale over the whole record.

        `physical_checks` looks at three slices and can miss a short corrupted block between them;
        this pass cannot. It streams, so it never holds more than one block.
        """
        bad_values = 0
        first_bad: int | None = None
        peak = 0.0
        for first, block in self.blocks(block_samples):
            finite = np.isfinite(block)
            if not finite.all():
                bad_values += int((~finite).sum())
                if first_bad is None:
                    first_bad = first + int(np.argmin(finite))
                block = block[finite]
            if block.size:
                peak = max(peak, float(np.abs(block).max()))
        return (
            FormatCheck(
                "finite_everywhere",
                bad_values == 0,
                "every sample finite"
                if bad_values == 0
                else f"{bad_values} non-finite samples, the first at index {first_bad}",
            ),
            FormatCheck(
                "plausible_scale_everywhere",
                peak <= SCALE_ABS_MAX,
                f"largest magnitude {peak:.3g} file units (limit {SCALE_ABS_MAX:g})",
            ),
        )

    def block_rows(self, block_samples: int = COVERAGE_BLOCK_SAMPLES) -> list[dict[str, float]]:
        """One row of statistics per fixed block over the whole record, streaming.

        Blocks have `block_samples` samples; a remainder shorter than `MIN_BLOCK_SAMPLES` is folded
        into the last block, so every sample belongs to exactly one block. At most one block is in
        memory; the rows are a few numbers each.
        """
        if not MIN_BLOCK_SAMPLES <= block_samples <= MAX_BLOCK_SAMPLES:
            raise BenchmarkError(
                f"block_samples must be in [{MIN_BLOCK_SAMPLES}, {MAX_BLOCK_SAMPLES}]"
            )
        if self.count < MIN_BLOCK_SAMPLES:
            raise format_unknown(
                f"{self.count} samples: fewer than the {MIN_BLOCK_SAMPLES} one block needs"
            )
        edges = list(range(0, self.count, block_samples))
        if len(edges) > 1 and self.count - edges[-1] < MIN_BLOCK_SAMPLES:
            edges.pop()
        edges.append(self.count)
        rows: list[dict[str, float]] = []
        self.assert_unchanged()
        for begin, end in zip(edges[:-1], edges[1:], strict=True):
            with np.errstate(all="ignore"):
                block = np.asarray(self._samples[begin:end], dtype=np.float64)
                rows.append(_block_row(begin, block))
        return rows

    def coverage_scan(self, block_samples: int = COVERAGE_BLOCK_SAMPLES) -> CoverageReport:
        """The same checks on every block of the whole record (no slices, no skipped samples).

        Per block: finite, plausible magnitude, the largest deviation from the block median
        against a robust scale taken from the record itself (the median over blocks of 1.4826 x
        MAD, not an absolute limit), block spread against that record scale, lag-1 smoothness,
        band limit, continuity, clipping and distinct values. Thresholds: see the constants
        `BLOCK_*` and plan Revision 7 (set on the B2B file only, margins stated there).
        A pass makes no four-level claim: ramps, NRZ and 16 levels can pass.
        """
        rows = self.block_rows(block_samples)
        return summarize_blocks(rows, self.count, block_samples)

    def slice_geometry(self, max_samples: int = 1 << 20) -> tuple[int, tuple[int, ...]]:
        """(slice length, first indices) of the three slices `physical_checks` looks at."""
        n = min(max_samples // 3, self.count // 3)
        return n, (0, (self.count - n) // 2, self.count - n)

    def physical_checks(self, max_samples: int = 1 << 20) -> tuple[FormatCheck, ...]:
        """`waveform_checks` on up to three slices (start, middle, end), reporting any failure.

        Slices only (about 2.6 % of a B2B-sized record): `open_raw` uses it, the file inspection
        does not; `coverage_scan` is the whole-record pass.
        """
        n, starts = self.slice_geometry(max_samples)
        out: list[FormatCheck] = []
        for index, begin in enumerate(starts):
            for check in waveform_checks(self.read(begin, begin + n)):
                if not check.passed or index == 0:
                    out.append(
                        FormatCheck(check.name, check.passed, f"slice {index}: {check.detail}")
                    )
        return tuple(out)


def _block_row(begin: int, x: FloatArray) -> dict[str, float]:
    """Statistics of one block; a block with a non-finite value gets no other statistic."""
    row: dict[str, float] = {"begin": float(begin), "size": float(x.size)}
    finite = np.isfinite(x)
    row["nonfinite"] = float((~finite).sum())
    if not finite.all():
        return row
    median = float(np.median(x))
    deviation = np.abs(x - median)
    centred = x - x.mean()
    std = float(centred.std())
    row.update(
        peak=float(np.abs(x).max()),
        median=median,
        sigma=1.4826 * float(np.median(deviation)),
        max_dev=float(deviation.max()),
        std=std,
        distinct=float(np.unique(x).size),
        rail=float(((x == x.max()).sum() + (x == x.min()).sum()) / x.size),
    )
    if std > 0:
        row["lag1"] = float(np.dot(centred[:-1], centred[1:]) / np.dot(centred, centred))
        row["band_db"] = _upper_band_db(centred)
        row["jump"] = float(np.quantile(np.abs(np.diff(x)), 0.999) / std)
    return row


@dataclass(frozen=True)
class CoverageReport:
    """What the whole-record block pass tested and found. Coverage is computed, never assumed."""

    block_samples: int
    blocks_checked: int
    blocks_failed: int
    samples_total: int
    samples_checked: int
    samples_in_failed_blocks: int
    record_scale: float
    checks: tuple[FormatCheck, ...]
    first_failed_sample: int | None

    @property
    def coverage_pct(self) -> float:
        return 100.0 * self.samples_checked / self.samples_total

    @property
    def passed(self) -> bool:
        return self.blocks_failed == 0 and self.samples_checked == self.samples_total

    @property
    def tested(self) -> str:
        return (
            f"every block of {self.block_samples:,} samples (remainder folded into the last): "
            "finite; magnitude; largest deviation against a robust scale of the record; block "
            "spread against that scale; lag-1 smoothness; band limit; continuity; clipping; "
            "distinct values. This pass makes no four-level claim and no format claim"
        )

    def summary(self) -> str:
        failed_pct = 100.0 * self.samples_in_failed_blocks / self.samples_total
        return (
            f"blocks checked {self.blocks_checked}, blocks failed {self.blocks_failed}, coverage "
            f"{self.coverage_pct:.1f}% of samples checked ({self.samples_checked:,} of "
            f"{self.samples_total:,}), {failed_pct:.1f}% of samples in failed blocks"
        )


def summarize_blocks(
    rows: Sequence[dict[str, float]], count: int, block_samples: int
) -> CoverageReport:
    """Apply the block checks to the rows; the record scale comes from the rows themselves."""
    finite_rows = [r for r in rows if r["nonfinite"] == 0]
    sigmas = [r["sigma"] for r in finite_rows if r["sigma"] > 0]
    scale = float(np.median(sigmas)) if sigmas else 0.0
    failed: dict[str, list[tuple[int, str]]] = {n: [] for n in BLOCK_CHECK_NAMES}
    for r in rows:
        at = int(r["begin"])
        if r["nonfinite"]:
            failed["finite"].append((at, f"{int(r['nonfinite'])} non-finite values"))
            continue
        if r["peak"] > SCALE_ABS_MAX or r["std"] < SCALE_STD_MIN:
            failed["plausible_scale"].append((at, f"peak {r['peak']:.3g}, spread {r['std']:.3g}"))
        if not scale > 0:
            failed["spike_vs_record_scale"].append((at, "the record has no scale (no spread)"))
            failed["spread_vs_record_scale"].append((at, "the record has no scale (no spread)"))
        else:
            ratio = r["max_dev"] / scale
            if ratio > BLOCK_SPIKE_MAX:
                failed["spike_vs_record_scale"].append((at, f"{ratio:.3g} x record scale"))
            spread = r["sigma"] / scale
            if not BLOCK_SPREAD_MIN <= spread <= BLOCK_SPREAD_MAX:
                failed["spread_vs_record_scale"].append((at, f"{spread:.3g} x record scale"))
        if "lag1" not in r:
            failed["non_degenerate"].append((at, "zero spread"))
            continue
        if r["lag1"] < BLOCK_LAG1_MIN:
            failed["smooth"].append((at, f"lag-1 {r['lag1']:.3f}"))
        if r["band_db"] > BLOCK_BAND_DB_MAX:
            failed["band_limited"].append((at, f"{r['band_db']:.1f} dB"))
        if r["jump"] > BLOCK_JUMP_MAX:
            failed["continuous"].append((at, f"{r['jump']:.3g} std"))
        if r["rail"] > BLOCK_RAIL_MAX:
            failed["not_clipped"].append((at, f"{r['rail']:.2e} at extremes"))
        if r["distinct"] < BLOCK_DISTINCT_MIN:
            failed["non_degenerate"].append((at, f"{int(r['distinct'])} distinct values"))
    bad_starts = {at for items in failed.values() for at, _ in items}
    bad_samples = sum(int(r["size"]) for r in rows if int(r["begin"]) in bad_starts)
    checked = sum(int(r["size"]) for r in rows)
    checks = tuple(
        FormatCheck(
            f"block_{name}",
            not items,
            "every block passes"
            if not items
            else f"{len(items)} blocks fail, the first at sample {items[0][0]} ({items[0][1]})",
        )
        for name, items in failed.items()
    )
    return CoverageReport(
        block_samples,
        len(rows),
        len(bad_starts),
        count,
        checked,
        bad_samples,
        scale,
        checks,
        min(bad_starts) if bad_starts else None,
    )


def _hashed(path: Path, md5_supplied: str | None, checksum: Checksum | None) -> Checksum:
    """Hash before processing: never decode a file that was not hashed or whose MD5 disagrees."""
    if checksum is None or checksum.size_local is None:
        checksum = verify_local_asset(path, md5_supplied)
    if checksum.md5_state is Md5State.MISMATCH:
        raise BenchmarkError(f"{path.name}: MD5 differs from the supplied value; refusing the file")
    if not checksum.still_current(path):
        raise BenchmarkError(f"{path.name} changed after it was hashed; hash it again")
    return checksum
