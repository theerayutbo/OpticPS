"""Import oscilloscope (Keysight Infiniium / UXR) waveform exports.

Three formats are read: HDF5, CSV and BIN. The layouts follow the UXR Programmer's Guide
(pp598, 2090-2098) and the Infiniium HDF5 schema page; none has been tested on a real file.
Anything not documented is recorded in ScopeWaveform.attributes, and ambiguous or
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
VOLT_SCALES = {"V": 1.0, "mV": 1e-3, "uV": 1e-6, "\u00b5V": 1e-6, "\u03bcV": 1e-6}
TIME_SCALES = {
    "s": 1.0, "ms": 1e-3, "us": 1e-6, "\u00b5s": 1e-6, "\u03bcs": 1e-6, "ns": 1e-9, "ps": 1e-12,
}  # fmt: skip
UNIT_WORDS = {"volt": "V", "volts": "V", "second": "s", "seconds": "s"}
DEFAULT_MAX_SAMPLES = 500_000_000
METADATA_MAX_BYTES = 4096  # per identification dataset (Frame, FileType)
METADATA_MAX_TEXT = 256  # characters kept from any metadata string
METADATA_MAX_ELEMENTS = 64  # elements kept from any array attribute
DEFAULT_WAVEFORM_TYPES = ("NORMAL", "AVERAGE")
CSV_DEFAULT_TYPES = ("NORMAL", "RAW", "AVERAGE")
CSV_TYPE_NAMES = ("NORMAL", "RAW", "INTERPOLATE", "AVERAGE", "VERSUS")
WAVEFORM_TYPE_NAMES = {
    0: "UNKNOWN", 1: "NORMAL", 2: "PEAK DETECT", 3: "AVERAGE", 4: "HORIZONTAL HISTOGRAM",
    5: "VERTICAL HISTOGRAM", 6: "LOGIC",
}  # fmt: skip
UNIT_CODES = {1: "Volt", 2: "Second"}
METADATA_MAX_VALUES = 1024
CHANNEL_LABEL = re.compile(r"^\s*(?:channel|chan|ch)\s*(\d+)\s*$", re.IGNORECASE)
UNIFORM_TOLERANCE = 1e-3
BIN_FILE_HEADER = struct.Struct("<2s2sii")
BIN_WAVE_HEADER = struct.Struct("<iiiiifdddii16s16s24s16sdI")
BIN_DATA_HEADER = struct.Struct("<ihhi")
BIN_FLOAT32 = 1
BIN_COOKIE = b"AG"
BIN_VERSION = b"10"
BIN_TYPES = (1, 3)
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
        text = bytes(value[: 4 * METADATA_MAX_TEXT]).decode("utf-8", errors="replace")
    else:
        text = str(value)
    return text.strip("\x00 \t\r\n")[:METADATA_MAX_TEXT]


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
    if array.size > METADATA_MAX_ELEMENTS:
        return f"<{array.size} values, not kept>"
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


def _unit_scale(text: str, table: dict[str, float], what: str) -> float:
    """Return the factor that converts a stated unit to the base unit; unknown units raise."""
    unit = UNIT_WORDS.get(text.strip().lower(), text.strip())
    if unit not in table:
        raise UxrImportError(f"{what} unit {text!r} is not recognised; accepted {sorted(table)}")
    return table[unit]


def _title_unit(cell: str) -> str | None:
    """Return the unit written in brackets or parentheses at the end of a column title."""
    found = re.findall(r"\(([^)]*)\)|\[([^\]]*)\]", cell)
    return (found[-1][0] or found[-1][1]).strip() if found else None


def _check_increment(x_increment_s: float) -> None:
    if not x_increment_s > 0 or not np.isfinite(x_increment_s):
        raise UxrImportError(f"Time increment must be positive and finite, got {x_increment_s}")


def _finite_samples(samples: FloatArray) -> FloatArray:
    if samples.size < 2 or not np.all(np.isfinite(samples)):
        raise UxrImportError("Waveform has fewer than 2 samples or non-finite samples")
    return samples


def _member(
    parent: Any, name: str, what: str, kind: str, max_values: int | None = METADATA_MAX_VALUES
) -> Any:
    """Return a hard-linked group or dataset; links and unsafe storage are never followed.

    Every dataset read goes through here: soft and external links, virtual and externally
    stored datasets, a null dataspace and (when max_values is given) too many values are refused.
    """
    import h5py

    link = parent.get(name, getlink=True)
    if link is None:
        raise UxrImportError(f"Missing {what}")
    if isinstance(link, h5py.SoftLink | h5py.ExternalLink):
        raise UxrImportError(f"{what} is a {type(link).__name__}; links are not followed")
    item = parent[name]
    if kind == "group":
        if not isinstance(item, h5py.Group):
            raise UxrImportError(f"{what} is not a group")
        return item
    if not isinstance(item, h5py.Dataset):
        raise UxrImportError(f"{what} is not a dataset")
    if item.is_virtual or item.external:
        raise UxrImportError(f"{what} uses virtual or external storage; refused")
    if item.shape is None:
        raise UxrImportError(f"{what} has a null dataspace and holds no data")
    if max_values is not None and item.size > max_values:
        raise UxrImportError(f"{what} holds {item.size} values, more than the limit {max_values}")
    return item


def _type_name(value: Any) -> str:
    """Waveform type as an upper-case name; the guide's integer codes are translated."""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text.upper()
    if not np.isfinite(number) or number != int(number) or int(number) not in WAVEFORM_TYPE_NAMES:
        raise UxrImportError(f"Waveform type {value!r} is not one of the guide's codes 0 to 6")
    return WAVEFORM_TYPE_NAMES[int(number)]


def _waveform_type(attrs: dict[str, Any], where: str) -> str:
    """Read the type from `WaveformType` (help page) or `Waveform Type` (guide p2090 example)."""
    found = {k: _type_name(attrs[k]) for k in ("WaveformType", "Waveform Type") if k in attrs}
    if not found:
        raise UxrImportError(f"Attribute WaveformType (or 'Waveform Type') not found on {where}")
    if len(set(found.values())) > 1:
        raise UxrImportError(f"Waveform type attributes disagree on {where}: {found}")
    return next(iter(found.values()))


def _unit_text(value: Any) -> str:
    """Unit name from a string or from the guide's integer code (1 = Volt, 2 = Second)."""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if not np.isfinite(number) or number != int(number) or int(number) not in UNIT_CODES:
        raise UxrImportError(f"Unit code {value!r} is not 1 (Volt) or 2 (Second)")
    return UNIT_CODES[int(number)]


def _whole_number(value: Any, name: str) -> int:
    """An integer-valued attribute; fractions are rejected, not truncated."""
    number = _number(value, name)
    if number != int(number):
        raise UxrImportError(f"Attribute {name} is {number:g}, not a whole number")
    return int(number)


def read_hdf5(
    path: Path,
    channel: int = 1,
    segment: int | None = None,
    allow_waveform_types: Iterable[str] | None = None,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> ScopeWaveform:
    """Read one channel of an Infiniium HDF5 export (layout from the vendor schema page).

    The file is untrusted: links and external or virtual storage are refused and the
    dataset shape is checked against NumPoints x NumSegments and max_samples before any
    data is read. Scaling follows the UXR Programmer's Guide (p598): an H5 float dataset holds
    actual volts, an H5INt integer dataset needs raw * YInc + YOrg. Time = XOrg + i * XInc.
    The dataset type is the only indication of which export was used.
    """
    import h5py

    allowed = {t.upper() for t in (allow_waveform_types or DEFAULT_WAVEFORM_TYPES)}
    try:
        handle = h5py.File(path, "r")
    except OSError as error:
        raise UxrImportError(f"{path.name} is not a readable HDF5 file: {error}") from error
    with handle:
        waveforms = _member(handle, "Waveforms", "/Waveforms group", "group")
        group_name = f"Channel {channel}"
        if group_name not in waveforms.keys():  # noqa: SIM118 - key listing, no link followed
            raise UxrImportError(f"Missing {group_name}; the file holds {sorted(waveforms.keys())}")
        group = _member(waveforms, group_name, f"/Waveforms/{group_name}", "group")
        data_name = f"{group_name}Data"
        dataset = _member(
            group, data_name, f"dataset {data_name} in /Waveforms/{group_name}", "dataset", None
        )
        attrs = {k: _plain(v) for k, v in group.attrs.items()}
        for name in ("NumPoints", "XInc", "XOrg", "XUnits", "YUnits"):
            if name not in attrs:
                raise UxrImportError(f"Attribute {name} not found on /Waveforms/{group_name}")
        _check_units("YUnits", _unit_text(attrs["YUnits"]), VOLT_NAMES)
        _check_units("XUnits", _unit_text(attrs["XUnits"]), ("second", "seconds"))
        wave_type = _waveform_type(attrs, f"/Waveforms/{group_name}")
        if wave_type not in allowed:
            raise UxrImportError(
                f"WaveformType {wave_type!r} is not allowed; use {sorted(allowed)}"
            )
        x_inc = _number(attrs["XInc"], "XInc")
        _check_increment(x_inc)
        x_org = _number(attrs["XOrg"], "XOrg")
        num_points = _whole_number(attrs["NumPoints"], "NumPoints")
        if num_points < 2:
            raise UxrImportError(f"NumPoints is {num_points}; at least 2 are needed")
        num_segments = _whole_number(attrs.get("NumSegments", 1), "NumSegments")
        notes: dict[str, Any] = {}
        notes_warn: list[str] = []
        if num_segments < 0:
            raise UxrImportError(f"NumSegments is {num_segments}")
        if num_segments == 0:
            num_segments = 1
            notes["num_segments_note"] = (
                "NumSegments was 0, treated as 1 (non-segmented); the guide's own HDF5 "
                "example (p2090) shows NumSegments = 0 for a normal capture"
            )
        interp = _number(attrs.get("SavedInterpFactor", 1), "SavedInterpFactor")
        if interp not in (0.0, 1.0):
            notes_warn.append(
                f"SavedInterpFactor is {interp:g}; the meaning of XInc under interpolation is "
                "unverified, so the sample rate may not be the acquisition rate"
            )
        if num_segments != 1 and segment is None:
            raise UxrImportError(
                f"NumSegments is {num_segments}; select one with segment=N (0-based)"
            )
        expected = num_points * num_segments
        if expected > max_samples or dataset.size > max_samples:
            raise UxrImportError(
                f"{max(expected, dataset.size)} values exceed the limit of {max_samples}; "
                "raise max_samples if this is intended"
            )
        if dataset.size != expected or dataset.ndim > 2:
            raise UxrImportError(
                f"Dataset shape {dataset.shape} does not match NumPoints*NumSegments = "
                f"{num_points}*{num_segments}"
            )
        if dataset.dtype.kind not in "iuf":
            raise UxrImportError(f"Unsupported dataset type {dataset.dtype}")
        if num_segments != 1:
            if segment is None or not 0 <= segment < num_segments:
                raise UxrImportError(f"Segment {segment} outside 0..{num_segments - 1}")
            if dataset.ndim == 1:
                raw = np.asarray(dataset[segment * num_points : (segment + 1) * num_points])
            elif dataset.shape == (num_segments, num_points):
                raw = np.asarray(dataset[segment])
            else:
                raise UxrImportError(f"Dataset shape {dataset.shape} cannot be sliced by segment")
            notes["segment"] = segment
            notes["segment_layout_assumption"] = "segments stored back to back (unverified)"
        else:
            raw = np.asarray(dataset[()]).reshape(-1)
        if raw.dtype.kind in "iu":
            y_inc = _number(attrs.get("YInc"), "YInc") if "YInc" in attrs else None
            y_org = _number(attrs.get("YOrg"), "YOrg") if "YOrg" in attrs else None
            if y_inc is None or y_org is None or y_inc == 0:
                raise UxrImportError("Integer dataset needs nonzero YInc and a YOrg to scale")
            samples = y_org + raw.astype(np.float64) * y_inc
            notes["scaling_rule"] = (
                "integers (H5INt): volts = raw * YInc + YOrg (UXR Programmer's Guide p598)"
            )
        else:
            samples = raw.astype(np.float64)
            notes["scaling_rule"] = (
                "floats (H5): values are actual vertical values, no scaling (UXR Programmer's "
                "Guide p598)"
            )
        samples = _finite_samples(samples)
        model = serial = date = None
        frame = _first_value(handle, "Frame", "TheFrame")
        if frame is None:
            notes_warn.append(
                "instrument model unknown: /Frame/TheFrame is absent or not laid out as the "
                "guide describes (a group holding the TheFrame dataset)"
            )
        else:
            names = frame.dtype.names or ()
            model = _text(frame["Model"]) if "Model" in names else None
            serial = _text(frame["Serial"]) if "Serial" in names else None
            date = _text(frame["Date"]) if "Date" in names else None
        type_value = _first_value(handle, "FileType", "KeysightH5FileType")
        file_type = None if type_value is None else _text(type_value)
        extra = {
            "file_type": file_type,
            "dataset_dtype": str(raw.dtype),
            "waveform_type": wave_type,
            **notes,
        }
        if notes_warn:
            extra["warnings"] = notes_warn
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


def _first_value(handle: Any, group: str, name: str) -> Any:
    """First element of handle[group][name] if present, else None; links and storage checked."""
    import h5py

    if group not in handle.keys():  # noqa: SIM118
        return None
    if isinstance(handle.get(group, getlink=True), h5py.HardLink) and isinstance(
        handle[group], h5py.Dataset
    ):
        return None  # laid out as a dataset instead of a group: identification unknown
    folder = _member(handle, group, f"/{group}", "group")
    if name not in folder.keys():  # noqa: SIM118
        return None
    dataset = _member(folder, name, f"/{group}/{name}", "dataset")
    if dataset.size * dataset.dtype.itemsize > METADATA_MAX_BYTES:
        raise UxrImportError(
            f"/{group}/{name} holds {dataset.size * dataset.dtype.itemsize} bytes, more than "
            f"the metadata limit {METADATA_MAX_BYTES}"
        )
    values = np.asarray(dataset[()]).reshape(-1)
    if values.size == 0:
        raise UxrImportError(f"/{group}/{name} is empty")
    return values[0]


def _is_number(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


def _is_whole(cell: str) -> bool:
    return _is_number(cell) and np.isfinite(float(cell)) and float(cell) == int(float(cell))


CSV_KEYS = {
    "revision", "type", "start", "points", "count", "segments", "xdisprange", "xdisporg",
    "xinc", "xorg", "xunits", "ydisprange", "ydisporg", "yinc", "yorg", "yunits", "frame",
    "date", "time", "maxbandwidth", "minbandwidth", "timetags", "data",
}  # fmt: skip
CSV_ALIASES = {
    "xincrement": "xinc", "xorigin": "xorg", "yincrement": "yinc", "yorigin": "yorg",
    "xunit": "xunits", "yunit": "yunits", "xdisplayrange": "xdisprange",
    "xdisplayorigin": "xdisporg", "ydisplayrange": "ydisprange", "ydisplayorigin": "ydisporg",
    "countorsegments": "count",
}  # fmt: skip


def _csv_key(cell: str) -> str | None:
    """Canonical header key for a cell, or None if it is not one of the documented fields."""
    key = re.sub(r"[\s_]", "", cell.lower())
    key = CSV_ALIASES.get(key, key)
    return key if key in CSV_KEYS else None


def _header_fields(rows: list[list[str]]) -> dict[str, str]:
    """Collect documented header fields from 'key,value', 'key=value' or name-row/value-row text.

    The vendor guide lists the fields (Revision, Type, ... Data) but the separator and exact
    layout of a real file are unverified, so the three plausible shapes are all read.
    """
    fields: dict[str, str] = {}
    for index, row in enumerate(rows):
        keys = [_csv_key(cell) for cell in row]
        if sum(k is not None for k in keys) >= 3 and index + 1 < len(rows):
            below = rows[index + 1]
            if len(below) == len(row):
                for key, value in zip(keys, below, strict=True):
                    if key is not None and value.strip():
                        fields.setdefault(key, value.strip())
                continue
        for position, cell in enumerate(row):
            split = re.split(r"\s*[=:]\s*", cell, maxsplit=1)
            if len(split) == 2 and _csv_key(split[0]) and split[1].strip():
                fields.setdefault(str(_csv_key(split[0])), split[1].strip())
            elif _csv_key(cell) and position == 0 and len(row) >= 2 and row[1].strip():
                fields.setdefault(str(_csv_key(cell)), row[1].strip())
    return fields


def _csv_type(text: str) -> str:
    """Canonical CSV waveform type; SCPI short forms such as NORM or AVER are expanded."""
    upper = text.strip().upper()
    for full in CSV_TYPE_NAMES:
        if len(upper) >= 3 and full.startswith(upper):
            return full
    return upper


def read_csv(
    path: Path,
    x_increment_s: float | None = None,
    channel: int | None = None,
    allow_waveform_types: Iterable[str] | None = None,
) -> ScopeWaveform:
    """Read a CSV of numeric rows after optional non-numeric header rows.

    The vendor guide (UXR Programmer's Guide pp2091-2092) lists the header fields; the
    separator and exact spelling in a real file are unverified, so parsing is tolerant. Two
    data shapes are accepted: (time, value) rows, or value-only rows with XInc taken from
    the header or the x_increment_s argument. Multi-source files (more columns) and
    transmitter DataOut files are rejected. Units are parsed; unknown units are rejected.
    A header Type of interpolate or versus (an XY plot) is refused unless allowed, a header
    Segments above 1 is always refused, and a header Points that differs from the data is an
    error.
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
    titles = header[-1] if header else []
    width = len(rows[0])
    time_title = _title_unit(titles[0]) if width == 2 and titles else None
    value_cell = width - 1
    value_title = _title_unit(titles[value_cell]) if len(titles) > value_cell else None
    fields = _header_fields(header)
    allowed = {_csv_type(t) for t in (allow_waveform_types or CSV_DEFAULT_TYPES)}
    csv_type = _csv_type(fields["type"]) if "type" in fields else None
    if csv_type is not None and csv_type not in allowed:
        raise UxrImportError(
            f"Header Type {fields['type']!r} is not allowed; use {sorted(allowed)} "
            "(a versus file is an XY plot, not a time record)"
        )
    segments_text = fields.get("segments")
    if segments_text is not None:
        if not _is_whole(segments_text):
            raise UxrImportError(f"Header Segments is not a whole number: {segments_text!r}")
        if int(float(segments_text)) > 1:
            raise UxrImportError(
                f"Header Segments is {segments_text}: segmented CSV is not supported; save one "
                "segment, or use an HDF5 export with --segment"
            )
    units = fields.get("yunits")
    volt_scale = 1.0
    stated = [u for u in (value_title, units) if u is not None]
    if stated:
        scales = {_unit_scale(u, VOLT_SCALES, "Y") for u in stated}
        if len(scales) > 1:
            raise UxrImportError(f"Y units {stated} in the header disagree")
        volt_scale = scales.pop()
    time_scale = _unit_scale(time_title, TIME_SCALES, "Time") if time_title else 1.0
    x_units = fields.get("xunits")
    if x_units is not None and _unit_scale(x_units, TIME_SCALES, "X") != 1.0:
        raise UxrImportError(f"Header XUnits is {x_units!r}; only Second is supported")
    header_inc_text = fields.get("xinc")
    header_inc = None
    if header_inc_text is not None:
        try:
            header_inc = float(header_inc_text)
        except ValueError as error:
            raise UxrImportError(f"Header XInc is not numeric: {header_inc_text!r}") from error
    table = np.array(rows, dtype=np.float64)
    notes: dict[str, Any] = {
        "header_rows": len(header),
        "header_fields": fields,
        "y_unit_scale_to_volt": volt_scale,
        "time_unit_scale_to_second": time_scale,
        "waveform_type": csv_type,
    }
    if not stated:
        notes["y_units_unstated"] = "no unit in the header; values taken as volts (unverified)"
    if table.shape[1] == 2:
        time = table[:, 0] * time_scale
        samples = table[:, 1] * volt_scale
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
        samples = table[:, 0] * volt_scale
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
        if "xorg" in fields and _is_number(fields["xorg"]):
            x_org = float(fields["xorg"])
        else:
            notes["x_origin_assumed_zero"] = True
    if "points" in fields:
        points = fields["points"]
        if not _is_whole(points):
            raise UxrImportError(f"Header Points is not a whole number: {points!r}")
        if int(float(points)) != len(samples):
            raise UxrImportError(
                f"Header Points is {points} but the file has {len(samples)} data rows"
            )
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


def _label_channel(label: str) -> int | None:
    """Channel number from a waveform label such as 'Channel 3', else None."""
    found = CHANNEL_LABEL.match(label)
    return int(found.group(1)) if found else None


def read_bin(path: Path, channel: int | None = None) -> ScopeWaveform:
    """Read a Keysight BIN file, validating it strictly against the documented layout.

    Layout: UXR Programmer's Guide pp2093-2098 (file header 12 bytes, waveform header 140
    bytes, data header 12 bytes, signed 4-byte ints, 4-byte floats, 8-byte doubles, structs
    packed to 4). Cookie must be 'AG' and version '10'. No real file has been tested.

    The channel is taken from the waveform label ('Channel N'). A file with several waveforms
    needs exactly one labelled with the requested channel (repeated labels would be segments,
    which are not supported); a single waveform whose label names another channel is refused
    instead of being relabelled.
    """
    blob = path.read_bytes()
    if len(blob) < BIN_FILE_HEADER.size:
        raise UxrImportError("BIN file is shorter than its file header")
    cookie, version, file_size, count = BIN_FILE_HEADER.unpack_from(blob, 0)
    if cookie != BIN_COOKIE or version != BIN_VERSION:
        raise UxrImportError(
            f"BIN cookie/version {cookie!r}/{version!r} is not b'AG'/b'10'; refusing the file"
        )
    if file_size != len(blob):
        raise UxrImportError(f"BIN File Size field {file_size} differs from actual {len(blob)}")
    if count < 1:
        raise UxrImportError("BIN file declares no waveforms")
    offset = BIN_FILE_HEADER.size
    entries: list[tuple[tuple[Any, ...], int, int]] = []
    for _ in range(count):
        if offset + BIN_WAVE_HEADER.size > len(blob):
            raise UxrImportError("BIN waveform header runs past the end of the file")
        fields = BIN_WAVE_HEADER.unpack_from(blob, offset)
        header_size, wave_type, buffers, points = fields[0], fields[1], fields[2], fields[3]
        if header_size != BIN_WAVE_HEADER.size:
            raise UxrImportError(
                f"BIN waveform header size {header_size} is not the documented "
                f"{BIN_WAVE_HEADER.size}"
            )
        if wave_type not in BIN_TYPES:
            raise UxrImportError(
                f"BIN waveform type {wave_type} is not supported; only 1 (Normal) and 3 (Average)"
            )
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
        if data_header_size != BIN_DATA_HEADER.size:
            raise UxrImportError(
                f"BIN data header size {data_header_size} is not the documented "
                f"{BIN_DATA_HEADER.size}"
            )
        start = data_at + data_header_size
        if points < 0 or buffer_size < 0:
            raise UxrImportError(
                f"BIN point count {points} or buffer size {buffer_size} is negative"
            )
        if width != 4 or buffer_size != 4 * points or start + buffer_size > len(blob):
            raise UxrImportError("BIN buffer size, width and point count disagree")
        entries.append((fields, start, points))
        offset = start + buffer_size
    labels = [_text(e[0][14]) for e in entries]
    numbers = [_label_channel(label) for label in labels]
    if count > 1:
        if channel is None:
            raise UxrImportError(
                f"BIN holds {count} waveforms labelled {labels}; select one with channel"
            )
        matches = [i for i, n in enumerate(numbers) if n == channel]
        if len(matches) != 1:
            raise UxrImportError(
                f"BIN holds {count} waveforms labelled {labels}; {len(matches)} are labelled "
                f"'Channel {channel}' and exactly one is needed (repeated labels would be "
                "segments, which are not supported)"
            )
        chosen = matches[0]
    else:
        chosen = 0
        if channel is not None and numbers[0] is not None and numbers[0] != channel:
            raise UxrImportError(
                f"BIN holds {labels[0]!r} but channel {channel} was requested; "
                f"pass channel {numbers[0]} to read it"
            )
    fields, start, points = entries[chosen]
    (_, wave_type, _, _, count_avg, x_range, x_display, x_inc, x_org, x_units, y_units) = fields[
        :11
    ]
    date, clock, frame, label, tags, seg_index = fields[11:]
    if y_units != BIN_UNIT_VOLT or x_units != BIN_UNIT_SECOND:
        raise UxrImportError(f"BIN units Y={y_units}, X={x_units}; only Volt(1)/Second(2)")
    _check_increment(x_inc)
    samples = np.frombuffer(blob, dtype="<f4", count=points, offset=start).astype(np.float64)
    labelled = numbers[chosen]
    notes: dict[str, Any] = {}
    if labelled is None:
        notes["channel_unverified"] = (
            f"waveform label {_text(label)!r} does not name a channel, so the channel is as "
            "requested and was not checked against the file"
        )
    if seg_index:
        notes["warnings"] = [
            f"BIN segment index is {seg_index}; the guide does not say whether a nonzero value "
            "marks a segmented acquisition, and only this waveform was read"
        ]
    return ScopeWaveform(
        samples_v=_finite_samples(samples),
        x_increment_s=float(x_inc),
        x_origin_s=float(x_org),
        y_units="V",
        channel=labelled if labelled is not None else channel,
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
            "layout_source": "UXR Programmer's Guide pp2093-2098; no real file tested",
            "frame": _text(frame),
            "label": _text(label),
            "time_tag": tags,
            "segment_index": seg_index,
            "widths": "4-byte signed ints, 4-byte floats, 8-byte doubles (pp2093-2095)",
            **notes,
        },
    )


def read_scope_file(
    path: Path,
    channel: int = 1,
    x_increment_s: float | None = None,
    segment: int | None = None,
    allow_waveform_types: Iterable[str] | None = None,
    max_samples: int | None = None,
) -> ScopeWaveform:
    """Dispatch on the file suffix: .h5/.hdf5, .csv or .bin.

    max_samples (HDF5 only) caps the number of values read; the default is
    DEFAULT_MAX_SAMPLES. allow_waveform_types applies to HDF5 and CSV, segment to HDF5 only.
    """
    suffix = path.suffix.lower()
    if suffix in (".h5", ".hdf5"):
        return read_hdf5(
            path,
            channel,
            segment,
            allow_waveform_types,
            DEFAULT_MAX_SAMPLES if max_samples is None else max_samples,
        )
    if suffix in (".csv", ".bin") and (segment is not None or max_samples is not None):
        raise UxrImportError("segment and max_samples apply to HDF5 files only")
    if suffix == ".bin" and allow_waveform_types:
        raise UxrImportError("waveform-type options apply to HDF5 and CSV files only")
    if suffix == ".csv":
        return read_csv(path, x_increment_s, channel, allow_waveform_types)
    if suffix == ".bin":
        return read_bin(path, channel)
    raise UxrImportError(f"Unsupported scope file suffix {suffix!r}; use .h5, .csv or .bin")
