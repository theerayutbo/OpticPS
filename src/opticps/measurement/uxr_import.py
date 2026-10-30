"""Import oscilloscope (Keysight Infiniium / UXR) waveform exports.

Three formats are read: HDF5, CSV and BIN. Only what could be confirmed from the vendor
help pages is relied on; every inference is recorded in ScopeWaveform.attributes and
unverified formats are gated behind explicit flags. Nothing is guessed: ambiguous or
unrecognised content raises UxrImportError instead of producing a waveform.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
VOLT_NAMES = ("volt", "volts", "v")
DEFAULT_WAVEFORM_TYPES = ("NORMAL", "AVERAGE")
UNIFORM_TOLERANCE = 1e-3
BIN_FILE_HEADER = struct.Struct("<2s2sii")
BIN_WAVE_HEADER = struct.Struct("<iiiiifdddii16s16s24s16sdI")
BIN_DATA_HEADER = struct.Struct("<ihhi")
BIN_FLOAT32 = 1
BIN_UNIT_VOLT = 1
BIN_UNIT_SECOND = 2


class UxrImportError(ValueError):
    """A scope export was rejected. The message says why."""


@dataclass(frozen=True)
class ScopeWaveform:
    """One channel of one acquisition, in volts against a uniform time axis."""

    samples_v: FloatArray
    x_increment_s: float
    x_origin_s: float
    y_units: str
    channel: int | None
    model: str | None
    serial: str | None
    saved_date: str | None
    source_format: str
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def measured_sample_rate(self) -> float:
        """Sample rate implied by the file's own time increment."""
        return 1.0 / self.x_increment_s


def _text(value: Any) -> str:
    """Return a stripped string from bytes, str or a numpy string scalar."""
    if isinstance(value, bytes | np.bytes_):
        return bytes(value).decode("utf-8", errors="replace").strip("\x00 \t\r\n")
    return str(value).strip("\x00 \t\r\n")


def _scalar(value: Any, name: str) -> Any:
    """Unwrap numpy scalars and 1-element arrays; reject anything longer."""
    array = np.asarray(value)
    if array.size != 1:
        raise UxrImportError(f"Attribute {name} has {array.size} elements, expected 1")
    item = array.reshape(-1)[0]
    if isinstance(item, bytes | np.bytes_ | str | np.str_):
        return _text(item)
    return item.item() if hasattr(item, "item") else item


def _plain(value: Any) -> Any:
    """Decode an attribute for the record: scalars unwrapped, longer arrays kept as lists."""
    array = np.asarray(value)
    if array.size == 1:
        return _scalar(value, "attribute")
    return [_text(v) if isinstance(v, bytes | np.bytes_) else v for v in array.reshape(-1).tolist()]


def _number(value: Any, name: str) -> float:
    """Return a finite float attribute."""
    item = _scalar(value, name)
    try:
        number = float(item)
    except (TypeError, ValueError) as error:
        raise UxrImportError(f"Attribute {name} is not numeric: {item!r}") from error
    if not np.isfinite(number):
        raise UxrImportError(f"Attribute {name} is not finite")
    return number


def _check_units(label: str, value: str, accepted: Iterable[str]) -> None:
    if value.strip().lower() not in tuple(accepted):
        raise UxrImportError(f"{label} is {value!r}; only {tuple(accepted)[0]} is supported")


def _check_increment(x_increment_s: float) -> None:
    if not x_increment_s > 0 or not np.isfinite(x_increment_s):
        raise UxrImportError(f"Time increment must be positive and finite, got {x_increment_s}")


def _finite_samples(samples: FloatArray) -> FloatArray:
    if samples.size < 2 or not np.all(np.isfinite(samples)):
        raise UxrImportError("Waveform has fewer than 2 samples or non-finite samples")
    return samples


def read_hdf5(
    path: Path,
    channel: int = 1,
    segment: int | None = None,
    allow_waveform_types: Iterable[str] | None = None,
) -> ScopeWaveform:
    """Read one channel of an Infiniium HDF5 export (layout from the vendor schema page).

    Time = XOrg + i * XInc and volts = YOrg + raw * YInc are inferences, not stated by the
    vendor. A float dataset is taken as already in volts. Both are recorded as unverified.
    """
    import h5py

    allowed = {t.upper() for t in (allow_waveform_types or DEFAULT_WAVEFORM_TYPES)}
    try:
        handle = h5py.File(path, "r")
    except OSError as error:
        raise UxrImportError(f"{path.name} is not a readable HDF5 file: {error}") from error
    with handle:
        if "Waveforms" not in handle:
            raise UxrImportError("HDF5 file has no /Waveforms group")
        group_name = f"Channel {channel}"
        waveforms = handle["Waveforms"]
        if group_name not in waveforms:
            raise UxrImportError(f"Missing {group_name}; the file holds {sorted(waveforms.keys())}")
        group = waveforms[group_name]
        data_name = f"{group_name}Data"
        if data_name not in group:
            raise UxrImportError(f"Missing dataset {data_name} in /Waveforms/{group_name}")
        attrs = {k: _plain(v) for k, v in group.attrs.items()}
        for name in ("NumPoints", "XInc", "XOrg", "XUnits", "YUnits", "WaveformType"):
            if name not in attrs:
                raise UxrImportError(f"Attribute {name} not found on /Waveforms/{group_name}")
        _check_units("YUnits", str(attrs["YUnits"]), VOLT_NAMES)
        _check_units("XUnits", str(attrs["XUnits"]), ("second", "seconds"))
        wave_type = str(attrs["WaveformType"]).upper()
        if wave_type not in allowed:
            raise UxrImportError(
                f"WaveformType {wave_type!r} is not allowed; use {sorted(allowed)}"
            )
        x_inc = _number(attrs["XInc"], "XInc")
        _check_increment(x_inc)
        x_org = _number(attrs["XOrg"], "XOrg")
        num_points = int(_number(attrs["NumPoints"], "NumPoints"))
        num_segments = int(_number(attrs.get("NumSegments", 1), "NumSegments"))
        raw = np.asarray(group[data_name])
        notes: dict[str, Any] = {}
        if num_segments != 1:
            if segment is None:
                raise UxrImportError(
                    f"NumSegments is {num_segments}; select one with segment=N (0-based)"
                )
            if not 0 <= segment < num_segments:
                raise UxrImportError(f"Segment {segment} outside 0..{num_segments - 1}")
            if raw.size != num_points * num_segments:
                raise UxrImportError(
                    f"Cannot slice segments: dataset has {raw.size} values, "
                    f"expected NumPoints*NumSegments = {num_points * num_segments}"
                )
            raw = raw.reshape(num_segments, num_points)[segment]
            notes["segment"] = segment
            notes["segment_layout_assumption"] = "segments stored back to back (unverified)"
        elif raw.size != num_points:
            raise UxrImportError(f"NumPoints is {num_points} but the dataset has {raw.size} values")
        if raw.ndim != 1 and num_segments == 1:
            raw = raw.reshape(-1)
        if raw.dtype.kind in "iu":
            y_inc = _number(attrs.get("YInc"), "YInc") if "YInc" in attrs else None
            y_org = _number(attrs.get("YOrg"), "YOrg") if "YOrg" in attrs else None
            if y_inc is None or y_org is None or y_inc == 0:
                raise UxrImportError("Integer dataset needs nonzero YInc and a YOrg to scale")
            samples = y_org + raw.astype(np.float64) * y_inc
            notes["scaling_assumption"] = "volts = YOrg + raw*YInc for integers (unverified)"
        elif raw.dtype.kind == "f":
            samples = raw.astype(np.float64)
            notes["scaling_assumption"] = "float dataset treated as volts (unverified)"
        else:
            raise UxrImportError(f"Unsupported dataset type {raw.dtype}")
        samples = _finite_samples(samples)
        model = serial = date = None
        if "Frame" in handle and "TheFrame" in handle["Frame"]:
            frame = np.asarray(handle["Frame/TheFrame"]).reshape(-1)[0]
            names = frame.dtype.names or ()
            model = _text(frame["Model"]) if "Model" in names else None
            serial = _text(frame["Serial"]) if "Serial" in names else None
            date = _text(frame["Date"]) if "Date" in names else None
        file_type = None
        if "FileType" in handle and "KeysightH5FileType" in handle["FileType"]:
            file_type = _text(np.asarray(handle["FileType/KeysightH5FileType"]).reshape(-1)[0])
        extra = {"file_type": file_type, "dataset_dtype": str(raw.dtype), **notes}
        return ScopeWaveform(
            samples_v=samples,
            x_increment_s=x_inc,
            x_origin_s=x_org,
            y_units="V",
            channel=channel,
            model=model,
            serial=serial,
            saved_date=date,
            source_format="hdf5",
            attributes={**attrs, **extra},
        )


def _is_number(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


def _header_value(rows: list[list[str]], pattern: str) -> str | None:
    """Return the value of a header entry written as 'key,value', 'key=value' or 'key: value'."""
    regex = re.compile(rf"\s*(?:{pattern})\s*[=:]?\s*(.*)", re.IGNORECASE)
    for row in rows:
        for position, cell in enumerate(row):
            match = regex.fullmatch(cell)
            if match is None:
                continue
            if match.group(1).strip():
                return match.group(1).strip()
            if position + 1 < len(row) and row[position + 1].strip():
                return row[position + 1].strip()
    return None


def read_csv(
    path: Path, x_increment_s: float | None = None, channel: int | None = None
) -> ScopeWaveform:
    """Read a CSV of numeric rows after optional non-numeric header rows.

    The Infiniium CSV header layout is unconfirmed, so only two shapes are accepted:
    (time, value) rows, or value-only rows with XInc taken from a header row or the
    x_increment_s argument. Transmitter DataOut files are rejected explicitly.
    """
    with path.open(newline="") as handle:
        rows = [[c.strip() for c in row] for row in csv.reader(handle) if any(row)]
    header: list[list[str]] = []
    while rows and not all(_is_number(c) for c in rows[0]):
        header.append(rows.pop(0))
    for row in header:
        if any(c.lower().startswith("dataout") for c in row):
            raise UxrImportError(
                "This is a transmitter waveform file (DataOut header), not a scope capture"
            )
    if not rows:
        raise UxrImportError("CSV has no numeric rows")
    widths = {len(r) for r in rows}
    if widths not in ({1}, {2}) or not all(all(_is_number(c) for c in r) for r in rows):
        raise UxrImportError("CSV data rows must be all numeric with one or two columns")
    units = _header_value(header, r"y[ _]?units?")
    if units is not None and units.lower() not in VOLT_NAMES:
        raise UxrImportError(f"Header states Y units {units!r}; only volts are supported")
    header_inc_text = _header_value(header, r"x[ _]?inc(?:rement)?")
    header_inc = None
    if header_inc_text is not None:
        try:
            header_inc = float(header_inc_text)
        except ValueError as error:
            raise UxrImportError(f"Header XInc is not numeric: {header_inc_text!r}") from error
    table = np.array(rows, dtype=np.float64)
    notes: dict[str, Any] = {"header_rows": len(header)}
    if table.shape[1] == 2:
        time = table[:, 0]
        samples = table[:, 1]
        if time.size < 2:
            raise UxrImportError("CSV needs at least 2 rows")
        step = (time[-1] - time[0]) / (time.size - 1)
        _check_increment(float(step))
        if np.max(np.abs(np.diff(time) - step)) > UNIFORM_TOLERANCE * step:
            raise UxrImportError("Time column is not uniformly spaced within 1e-3 of the step")
        x_inc, x_org = float(step), float(time[0])
        for label, given in (("header XInc", header_inc), ("x_increment_s", x_increment_s)):
            if given is not None and abs(given - x_inc) > UNIFORM_TOLERANCE * x_inc:
                raise UxrImportError(f"Time column step {x_inc:g} disagrees with {label} {given:g}")
        notes["x_increment_source"] = "time column"
    else:
        samples = table[:, 0]
        if header_inc is not None and x_increment_s is not None:
            if abs(header_inc - x_increment_s) > UNIFORM_TOLERANCE * header_inc:
                raise UxrImportError("Header XInc disagrees with x_increment_s")
        chosen = header_inc if header_inc is not None else x_increment_s
        if chosen is None:
            raise UxrImportError(
                "One-column CSV: no XInc header row and no x_increment_s given; not guessing"
            )
        _check_increment(chosen)
        x_inc, x_org = float(chosen), 0.0
        notes["x_increment_source"] = "header" if header_inc is not None else "argument"
        notes["x_origin_assumed_zero"] = True
    return ScopeWaveform(
        samples_v=_finite_samples(samples),
        x_increment_s=x_inc,
        x_origin_s=x_org,
        y_units="V",
        channel=channel,
        model=None,
        serial=None,
        saved_date=None,
        source_format="csv",
        attributes=notes,
    )


def read_bin(
    path: Path, channel: int | None = None, accept_unverified_bin: bool = False
) -> ScopeWaveform:
    """Read a Keysight BIN file. Integer widths are assumed, so a flag is required.

    Assumes 4-byte little-endian integers and floats. Field order follows the vendor
    page; widths and the meaning of 'X Origin' were not confirmed on real files.
    """
    if not accept_unverified_bin:
        raise UxrImportError(
            "BIN import is unverified on real files: field widths are assumed. "
            "Pass accept_unverified_bin=True (--accept-unverified-bin) to use it anyway, "
            "or export HDF5."
        )
    blob = path.read_bytes()
    if len(blob) < BIN_FILE_HEADER.size:
        raise UxrImportError("BIN file is shorter than its file header")
    cookie, version, file_size, count = BIN_FILE_HEADER.unpack_from(blob, 0)
    if file_size != len(blob):
        raise UxrImportError(f"BIN File Size field {file_size} differs from actual {len(blob)}")
    if count < 1:
        raise UxrImportError("BIN file declares no waveforms")
    wanted = 1 if channel is None else channel
    if count > 1 and channel is None:
        raise UxrImportError(f"BIN holds {count} waveforms; select one with channel (1-based)")
    if not 1 <= wanted <= count:
        raise UxrImportError(f"Waveform {wanted} not in file with {count} waveforms")
    offset = BIN_FILE_HEADER.size
    for index in range(1, count + 1):
        if offset + BIN_WAVE_HEADER.size > len(blob):
            raise UxrImportError("BIN waveform header runs past the end of the file")
        fields = BIN_WAVE_HEADER.unpack_from(blob, offset)
        header_size, wave_type, buffers, points = fields[0], fields[1], fields[2], fields[3]
        if header_size < BIN_WAVE_HEADER.size:
            raise UxrImportError(f"BIN waveform header size {header_size} is too small")
        if buffers != 1:
            raise UxrImportError(f"BIN waveform has {buffers} buffers; only 1 is supported")
        data_at = offset + header_size
        if data_at + BIN_DATA_HEADER.size > len(blob):
            raise UxrImportError("BIN data header runs past the end of the file")
        data_header_size, buffer_type, width, buffer_size = BIN_DATA_HEADER.unpack_from(
            blob, data_at
        )
        if buffer_type != BIN_FLOAT32:
            raise UxrImportError(f"BIN buffer type {buffer_type} is not supported (only 1)")
        if data_header_size < BIN_DATA_HEADER.size:
            raise UxrImportError(f"BIN data header size {data_header_size} is too small")
        start = data_at + data_header_size
        if width != 4 or buffer_size != 4 * points or start + buffer_size > len(blob):
            raise UxrImportError("BIN buffer size, width and point count disagree")
        if index == wanted:
            break
        offset = start + buffer_size
    (_, _, _, _, count_avg, x_range, x_display, x_inc, x_org, x_units, y_units) = fields[:11]
    date, clock, frame, label, tags, seg_index = fields[11:]
    if y_units != BIN_UNIT_VOLT or x_units != BIN_UNIT_SECOND:
        raise UxrImportError(f"BIN units Y={y_units}, X={x_units}; only Volt(1)/Second(2)")
    _check_increment(x_inc)
    samples = np.frombuffer(blob, dtype="<f4", count=points, offset=start).astype(np.float64)
    return ScopeWaveform(
        samples_v=_finite_samples(samples),
        x_increment_s=float(x_inc),
        x_origin_s=float(x_org),
        y_units="V",
        channel=wanted,
        model=None,
        serial=None,
        saved_date=f"{_text(date)} {_text(clock)}".strip() or None,
        source_format="bin",
        attributes={
            "cookie": cookie.hex(),
            "version": version.hex(),
            "waveform_type": wave_type,
            "count": count_avg,
            "x_display_range": x_range,
            "x_display_origin": x_display,
            "x_origin_note": "'X Origin' field used; vendor text is ambiguous (unverified)",
            "frame": _text(frame),
            "label": _text(label),
            "time_tag": tags,
            "segment_index": seg_index,
            "widths_assumed": "4-byte little-endian ints and floats (unverified)",
        },
    )


def read_scope_file(
    path: Path,
    channel: int = 1,
    x_increment_s: float | None = None,
    accept_unverified_bin: bool = False,
    segment: int | None = None,
) -> ScopeWaveform:
    """Dispatch on the file suffix: .h5/.hdf5, .csv or .bin."""
    suffix = path.suffix.lower()
    if suffix in (".h5", ".hdf5"):
        return read_hdf5(path, channel, segment)
    if suffix == ".csv":
        return read_csv(path, x_increment_s, channel)
    if suffix == ".bin":
        return read_bin(path, channel, accept_unverified_bin)
    raise UxrImportError(f"Unsupported scope file suffix {suffix!r}; use .h5, .csv or .bin")
