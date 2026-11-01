"""Read-only importer for the Hong et al. 2021 NANF dataset workbook (Gate N2).

Dataset DOI 10.5258/SOTON/D1889, CC BY 4.0 by its DOI-registry record (see
`docs/NANF_SOURCES_AND_PROVENANCE.md`). The workbook is third-party data and is never stored in Git;
this module reads a file at an explicit local path, offline, with the standard library only
(`zipfile` and `xml.etree`; no spreadsheet dependency). It does not write, fetch or follow links.

Discipline, in the order it runs:

1. The SHA-256 of the file is compared with the recorded value before anything is parsed. A
   different file is `NOT_COMPARABLE` (it is not the object the benchmark plan was written for).
2. The schema is default-deny: the sheet list, merged ranges, header cells, dimensions, and the
   cells that hold numbers (their columns, first row and count) must equal the recorded layout. Any
   unexpected sheet, header, cell, cell type or count raises `FORMAT_UNKNOWN`. Messages carry sheet
   names and cell references, never cell values, so a failure cannot leak a holdout number.
3. A value is a number only where the layout says so. A formula cell holding `-Inf` (the unloaded
   subcarriers of Fig. 11) comes back as `-inf` with the flag `NON_FINITE_FORMULA`. A BER of zero or
   below 1e-5 comes back as NaN with a censoring flag (plan section 3 and A3): it is never a number.
4. Each series carries its role in the fit and holdout plan. Holdout series are withheld unless the
   caller asks for them (`include_holdout=True`), which belongs to the scoring step after the freeze
   hash. A holdout series prints without its values.

The vocabulary of the error codes is that of `opticps.benchmarks.provenance.ErrorCode` (the strings
are equal; a test checks it) so the two reports read the same.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree

from opticps.optical_channel.fiber import ProvenanceCategory

NANF_WORKBOOK_SHA256 = "0753aeadd215e894e46de6cb7ac10df4c9edf32386ffdc37871381d80cc19cc0"
BER_CENSOR_FLOOR = 1e-5  # plan A3: a published BER of zero or below this is censored
ROP_SCORING_CAP_DBM = -5.0  # plan section 2, A3, A4: Fig. 4 points above this are not scored
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 64

SOURCE_MISSING = "SOURCE_MISSING"
NOT_COMPARABLE = "NOT_COMPARABLE"
FORMAT_UNKNOWN = "FORMAT_UNKNOWN"

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")


class NanfImportError(ValueError):
    """The workbook was refused. `code` is a standard outcome; the message never holds a value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class DataRole(StrEnum):
    """What the fit and holdout plan says a series is (docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md)."""

    CROSS_CHECK = "cross-check"  # Fig. 1: the paper's own numerics, no fit
    CALIBRATION = "calibration"  # Fig. 4 B2B series
    CALIBRATION_INPUT = "calibration-input"  # Fig. 5: operating points and link loss
    HOLDOUT = "holdout"  # everything else


class PointFlag(StrEnum):
    """How one point was read."""

    OK = "ok"
    NON_FINITE_FORMULA = "non-finite-formula"  # formula `-Inf`; the value is -inf, not a number
    CENSORED_ZERO = "censored-zero-ber"  # BER cell equal to 0; the value is NaN
    CENSORED_BELOW_FLOOR = "censored-below-1e-5"  # 0 < BER < 1e-5; the value is NaN


@dataclass(frozen=True)
class NanfSeries:
    """One published curve with its provenance, unit and role. Holdout series hide their values."""

    key: str
    sheet: str
    quantity: str
    unit: str
    axis_name: str
    axis_unit: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    flags: tuple[PointFlag, ...]
    role: DataRole
    provenance: ProvenanceCategory
    cells: str
    unit_source: str = "inferred from the paper's axis labels (headers carry no unit)"

    def __post_init__(self) -> None:
        if not (len(self.x) == len(self.y) == len(self.flags)):
            raise ValueError("x, y and flags must have one entry per point")

    def __len__(self) -> int:
        return len(self.y)

    @property
    def above_rop_cap(self) -> tuple[bool, ...]:
        """Per point: True where a Fig. 4 ROP lies above the -5 dBm scoring cap (plan A4).

        Those points are excluded from calibration and scoring; the importer returns them, so the
        caller must drop them. Empty (all False) for every other sheet.
        """
        if self.sheet != "Fig.4":
            return (False,) * len(self.x)
        return tuple(x > ROP_SCORING_CAP_DBM for x in self.x)

    @property
    def n_censored(self) -> int:
        return sum(
            f in (PointFlag.CENSORED_ZERO, PointFlag.CENSORED_BELOW_FLOOR) for f in self.flags
        )

    @property
    def n_non_finite(self) -> int:
        return sum(f is PointFlag.NON_FINITE_FORMULA for f in self.flags)

    def __repr__(self) -> str:
        shown = "values hidden (holdout)" if self.role is DataRole.HOLDOUT else "values present"
        return (
            f"NanfSeries({self.key!r}, {self.quantity} [{self.unit}] versus {self.axis_name} "
            f"[{self.axis_unit}], {len(self)} points, {self.role.value}, "
            f"{self.provenance.value}, {shown})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class NanfWorkbook:
    """The typed series of one verified workbook."""

    sha256: str
    series: Mapping[str, NanfSeries]
    withheld_holdout: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "series", MappingProxyType(dict(self.series)))

    def __getitem__(self, key: str) -> NanfSeries:
        return self.series[key]


# Results the paper reports (BER, SNR, capacity, the Fig. 5 link loss) are `measured`; the ROP
# columns are settings or operating points and stay `published-experimental` (Sources vocabulary:
# `published-experimental` is "a setting or description ... never a result").
_MEASURED_QUANTITIES = frozenset({"BER", "SNR", "capacity", "link_loss"})


def evidence_for(quantity: str, block_provenance: ProvenanceCategory | None) -> ProvenanceCategory:
    """The evidence label of a series: the block's own (Fig. 1) or by what the quantity is."""
    if block_provenance is not None:
        return block_provenance
    if quantity in _MEASURED_QUANTITIES:
        return ProvenanceCategory.MEASURED
    return ProvenanceCategory.PUBLISHED_EXPERIMENTAL


# --- the recorded layout ------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesLayout:
    """One numeric column: where it starts, how many numbers it holds, what it is."""

    letter: str
    header: str
    quantity: str
    unit: str
    role: DataRole
    count: int
    formula_rows: frozenset[int] = frozenset()  # rows holding a `-Inf` formula, not a number


@dataclass(frozen=True)
class BlockLayout:
    """An axis column and the series that share it (a series is paired with the axis by row)."""

    label: str
    axis_letter: str
    axis_header: str
    axis_name: str
    axis_unit: str
    first_row: int
    axis_count: int
    series: tuple[SeriesLayout, ...]
    provenance: ProvenanceCategory | None = None  # None: by quantity, see `evidence_for`
    header_row: int | None = None  # row of the header cells; default first_row - 1
    unit_source: str = "inferred from the paper's axis labels (headers carry no unit)"

    @property
    def top(self) -> int:
        return self.header_row if self.header_row is not None else self.first_row - 1


@dataclass(frozen=True)
class SheetLayout:
    name: str
    dimension: str
    merges: tuple[str, ...]
    titles: Mapping[str, str]
    blocks: tuple[BlockLayout, ...]


_CAL, _HOLD, _CIN, _XCHK = (
    DataRole.CALIBRATION,
    DataRole.HOLDOUT,
    DataRole.CALIBRATION_INPUT,
    DataRole.CROSS_CHECK,
)
_NUMERICAL = ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION
_PAPER_AXES = "paper Fig. 1 axis labels (read from the author manuscript)"


def _ser(
    letter: str, header: str, quantity: str, unit: str, role: DataRole, count: int
) -> SeriesLayout:
    return SeriesLayout(letter, header, quantity, unit, role, count)


def _fig1() -> SheetLayout:
    def block(label, axis, axis_header, axis_name, axis_unit, first, n_axis, cols, quantity, unit):
        series = tuple(_ser(c, h, quantity, unit, _XCHK, n_axis) for c, h in cols)
        return BlockLayout(
            label, axis, axis_header, axis_name, axis_unit, first, n_axis, series,
            provenance=_NUMERICAL, header_row=3, unit_source=_PAPER_AXES,
        )  # fmt: skip

    return SheetLayout(
        "Fig.1",
        "A1:V49",
        ("A1:D1", "G1:J1", "M1:P1", "S1:V1"),
        {
            "A1": "Fig.1(a) CD",
            "G1": "Fig.1(b) 3-dB bandwidth @5km",
            "M1": "Fig.1(c) fading @5km",
            "S1": "Fig.1(d) Fibre latency @1550nm",
        },
        (
            block("a-CD", "A", "Wavelength", "wavelength", "um", 4, 46,
                  (("B", "NANF"), ("C", "SSMF"), ("D", "NZ-DSF")), "CD", "ps/(nm km)"),
            block("b-bandwidth", "G", "wavelength", "wavelength", "um", 4, 46,
                  (("H", "SMF@5km"), ("I", "NZ-DSF@5km"), ("J", "NANF@5km")),
                  "bandwidth_3db", "GHz"),
            block("c-fading", "M", "Frequency", "frequency", "GHz", 4, 36,
                  (("N", "NANF"), ("O", "SMF"), ("P", "NZ-DSF")), "fading", "dB"),
            block("d-latency", "S", "Fibre length", "fibre length", "km", 4, 21,
                  (("T", "SSMF"), ("U", "NZ-DSF"), ("V", "NANF")), "latency", "us"),
        ),
    )  # fmt: skip


def _rate_blocks(
    sheet: str,
    axis_header: str,
    axis_name: str,
    axis_unit: str,
    n_axis: int,
    nanf_count: int,
    ber_first: int,
    snr_first: int,
    b2b_role: DataRole,
) -> tuple[tuple[BlockLayout, ...], dict[str, str], tuple[str, ...]]:
    """The 3 rates by (BER, SNR) layout shared by Fig. 4 and Fig. 6."""
    blocks: list[BlockLayout] = []
    titles: dict[str, str] = {}
    merges: list[str] = []
    for rate, axis, cols in (
        (80, "A", "BCD"),
        (100, "F", "GHI"),
        (112, "K", "LMN"),
    ):
        for kind, first, unit, panel in (("BER", ber_first, "1", 0), ("SNR", snr_first, "dB", 1)):
            letters = "abcdef"[(0, 2, 4)[(80, 100, 112).index(rate)] + panel]
            top = first - 1
            title_row = top - 2
            titles[f"{axis}{title_row}"] = f"{sheet}({letters}) {kind}@{rate}Gb/s "
            merges.append(f"{axis}{title_row}:{cols[-1]}{title_row}")
            series = tuple(
                _ser(
                    col,
                    f"{link}-{rate}-{kind}",
                    kind,
                    unit,
                    b2b_role if link == "B2B" else _HOLD,
                    nanf_count if link == "NANF" else n_axis,
                )
                for col, link in zip(cols, ("NANF", "B2B", "SMF"), strict=True)
            )
            blocks.append(
                BlockLayout(
                    f"{kind}@{rate}", axis, axis_header, axis_name, axis_unit, first, n_axis, series
                )
            )
    merges.sort(key=lambda m: (int(re.sub(r"\D", "", m.split(":")[0])), m))
    return tuple(blocks), titles, tuple(merges)


def _fig4() -> SheetLayout:
    blocks, titles, merges = _rate_blocks("Fig.4", "ROP", "ROP", "dBm", 11, 6, 4, 20, _CAL)
    return SheetLayout("Fig.4", "A1:N30", merges, titles, blocks)


def _fig6() -> SheetLayout:
    blocks, titles, merges = _rate_blocks(
        "Fig.6", "wavelength", "wavelength", "nm", 19, 19, 4, 27, _HOLD
    )  # Fig. 6 B2B is holdout too (plan section 2)
    return SheetLayout("Fig.6", "A1:N45", merges, titles, blocks)


def _fig5() -> SheetLayout:
    cols = (
        _ser("B", "ROP@NANF", "ROP", "dBm", _CIN, 19),
        _ser("C", "ROP@SSMF", "ROP", "dBm", _CIN, 19),
        _ser("D", "NANF loss", "link_loss", "dB", _CIN, 19),
    )
    block = BlockLayout("link", "A", "wavelength", "wavelength", "nm", 2, 19, cols, header_row=1)
    return SheetLayout("Fig.5", "A1:D20", (), {}, (block,))


def _simple(
    name: str,
    dimension: str,
    axis_header: str,
    axis_name: str,
    axis_unit: str,
    n_axis: int,
    cols: tuple[SeriesLayout, ...],
) -> SheetLayout:
    block = BlockLayout(
        "table", "A", axis_header, axis_name, axis_unit, 2, n_axis, cols, header_row=1
    )
    return SheetLayout(name, dimension, (), {}, (block,))


def _fig11() -> SheetLayout:
    missing = frozenset({163, *range(165, 188)})  # the 24 `-Inf` formula cells of the SSMF column
    smf = SeriesLayout(
        "C", "240sub-SMF-DMT", "SNR", "dB", _HOLD, 240, formula_rows=missing
    )  # 216 numbers and 24 formulas
    return _simple(
        "Fig.11",
        "A1:C241",
        "Frequency",
        "frequency",
        "GHz",
        240,
        (_ser("B", "240sub-NANF-DMT", "SNR", "dB", _HOLD, 240), smf),
    )


def _layouts() -> tuple[SheetLayout, ...]:
    return (
        _fig1(),
        _fig4(),
        _fig5(),
        _fig6(),
        _simple(
            "Fig.7", "A1:E9", "Subcarrier Number", "data subcarriers", "1", 8,
            (
                _ser("B", "SMF-BER", "BER", "1", _HOLD, 8),
                _ser("C", "NANF-BER", "BER", "1", _HOLD, 8),
                _ser("D", "SMF-Average SNR", "SNR", "dB", _HOLD, 8),
                _ser("E", "NANF-Average SNR", "SNR", "dB", _HOLD, 8),
            ),
        ),
        _simple(
            "Fig.8", "A1:C241", "Frequency", "frequency", "GHz", 240,
            (
                _ser("B", "240sub-NANF-OFDM", "SNR", "dB", _HOLD, 240),
                _ser("C", "240sub-SMF-OFDM", "SNR", "dB", _HOLD, 240),
            ),
        ),
        _simple(
            "Fig.9", "A1:E9", "ROP", "ROP", "dBm", 8,
            (
                _ser("B", "SMF-OFDM-BER", "BER", "1", _HOLD, 8),
                _ser("C", "NANF-OFDM-BER", "BER", "1", _HOLD, 6),
                _ser("D", "SMF-OFDM-SNR", "SNR", "dB", _HOLD, 8),
                _ser("E", "NANF-OFDM-SNR", "SNR", "dB", _HOLD, 6),
            ),
        ),
        _simple(
            "Fig.10", "A1:C9", "Subcarrier Number", "data subcarriers", "1", 8,
            (
                _ser("B", "SMF-DMT-BER", "BER", "1", _HOLD, 8),
                _ser("C", "NANF-DMT-BER", "BER", "1", _HOLD, 8),
            ),
        ),
        _fig11(),
        _simple(
            "Fig.12", "A1:E9", "ROP", "ROP", "dBm", 8,
            (
                _ser("B", "SMF-DMT Capacity", "capacity", "Gb/s", _HOLD, 8),
                _ser("C", "NANF-DMT Capacity", "capacity", "Gb/s", _HOLD, 6),
                _ser("D", "SMF-DMT BER", "BER", "1", _HOLD, 8),
                _ser("E", "NANF-DMT BER", "BER", "1", _HOLD, 6),
            ),
        ),
    )  # fmt: skip


SHEET_LAYOUTS: tuple[SheetLayout, ...] = _layouts()
EXPECTED_SHEETS = tuple(s.name for s in SHEET_LAYOUTS)


def series_key(sheet: str, block: str, header: str) -> str:
    """The key of a series in `NanfWorkbook.series`, for example `Fig.4/BER@80/B2B-80-BER`."""
    return f"{sheet}/{block}/{header}"


# --- reading ------------------------------------------------------------------------------------


def _fail(message: str, code: str = FORMAT_UNKNOWN) -> NanfImportError:
    return NanfImportError(code, message)


def _parse_xml(data: bytes, where: str) -> ElementTree.Element:
    lowered = data.lower()
    if b"\x00" in data or b"<!doctype" in lowered or b"<!entity" in lowered:
        raise _fail(f"{where} is not plain UTF-8 XML without a DOCTYPE or an entity; refused")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as err:
        raise _fail(f"{where} is not well-formed XML") from err


def _string_item(si: ElementTree.Element) -> str:
    """Text of one shared string: plain `t` and rich-text runs, never the phonetic `rPh` part."""
    parts: list[str] = []
    for child in si:
        if child.tag == f"{_NS}t":
            parts.append(child.text or "")
        elif child.tag == f"{_NS}r":
            parts.extend(t.text or "" for t in child.findall(f"{_NS}t"))
    return "".join(parts)


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


@dataclass(frozen=True)
class _Cell:
    kind: str  # "n", "s", "e", "other", "empty"
    text: str | None
    formula: str | None


def _read_cells(
    root: ElementTree.Element, shared: list[str], sheet: str
) -> dict[tuple[str, int], _Cell]:
    cells: dict[tuple[str, int], _Cell] = {}
    masters: dict[str, str] = {}
    for element in root.iter(f"{_NS}c"):
        ref = element.get("r", "")
        match = _CELL.match(ref)
        if match is None:
            raise _fail(f"{sheet}: a cell has no valid reference")
        pos = (match.group(1), int(match.group(2)))
        if pos in cells:
            raise _fail(f"{sheet}: cell {ref} is given twice")
        t = element.get("t")
        v = element.find(f"{_NS}v")
        f = element.find(f"{_NS}f")
        formula: str | None = None
        if f is not None:
            formula = (f.text or "").strip()
            if f.get("t") == "shared":
                si = f.get("si", "")
                if formula:
                    masters[si] = formula
                else:
                    formula = masters.get(si)
                    if formula is None:
                        raise _fail(f"{sheet}: cell {ref} uses a shared formula with no master")
        text = None if v is None else (v.text or "")
        if element.find(f"{_NS}is") is not None:  # inline string: content, never an empty cell
            cells[pos] = _Cell("other", None, formula)
        elif text is None and formula is None:
            cells[pos] = _Cell("empty", None, None)
        elif t in (None, "n"):
            cells[pos] = _Cell("n", text, formula)
        elif t == "s":
            index = int(text) if text is not None and text.isascii() and text.isdigit() else -1
            if not 0 <= index < len(shared):
                raise _fail(f"{sheet}: cell {ref} has a bad shared-string index")
            cells[pos] = _Cell("s", shared[index], formula)
        elif t == "e":
            cells[pos] = _Cell("e", text, formula)
        else:
            cells[pos] = _Cell("other", None, formula)
    return cells


def _check_sheet(
    layout: SheetLayout, root: ElementTree.Element, shared: list[str]
) -> dict[tuple[str, int], _Cell]:
    sheet = layout.name
    dim = root.find(f"{_NS}dimension")
    if dim is None or dim.get("ref") != layout.dimension:
        raise _fail(f"{sheet}: the dimension differs from the recorded layout")
    merges = tuple(m.get("ref", "") for m in root.iter(f"{_NS}mergeCell"))
    if sorted(merges) != sorted(layout.merges):
        raise _fail(f"{sheet}: the merged ranges differ from the recorded layout")
    cells = _read_cells(root, shared, sheet)
    expected_text: dict[tuple[str, int], str] = {}
    expected_num: set[tuple[str, int]] = set()
    expected_formula: set[tuple[str, int]] = set()
    for ref, title in layout.titles.items():
        m = _CELL.match(ref)
        assert m is not None
        expected_text[(m.group(1), int(m.group(2)))] = title
    for block in layout.blocks:
        expected_text[(block.axis_letter, block.top)] = block.axis_header
        for r in range(block.first_row, block.first_row + block.axis_count):
            expected_num.add((block.axis_letter, r))
        for s in block.series:
            expected_text[(s.letter, block.top)] = s.header
            for r in range(block.first_row, block.first_row + s.count):
                (expected_formula if r in s.formula_rows else expected_num).add((s.letter, r))
    for pos, cell in sorted(cells.items(), key=lambda kv: (_col_index(kv[0][0]), kv[0][1])):
        ref = f"{pos[0]}{pos[1]}"
        if cell.kind == "empty":
            continue
        if pos in expected_text:
            if cell.kind != "s" or cell.text != expected_text[pos] or cell.formula is not None:
                raise _fail(f"{sheet}: the header at {ref} differs from the recorded layout")
        elif pos in expected_num:
            if cell.kind != "n" or cell.formula is not None:
                raise _fail(f"{sheet}: cell {ref} is not a plain number as the layout requires")
        elif pos in expected_formula:
            if cell.kind != "e" or cell.formula != "-Inf":
                raise _fail(f"{sheet}: cell {ref} is not the expected `-Inf` formula cell")
        else:
            raise _fail(f"{sheet}: unexpected content at {ref}")
    present = {p for p, c in cells.items() if c.kind != "empty"}
    for group, name in (
        (expected_text, "header"),
        (expected_num, "number"),
        (expected_formula, "formula"),
    ):
        missing = [p for p in group if p not in present]
        if missing:
            raise _fail(f"{sheet}: {len(missing)} expected {name} cell(s) are absent")
    return cells


def _number(cell: _Cell, sheet: str, ref: str) -> float:
    try:
        value: float | None = float(cell.text or "")
    except ValueError:
        value = None
    if value is None:  # raised outside the handler: no cause or context holds the cell text
        raise _fail(f"{sheet}: cell {ref} is not a number")
    if not math.isfinite(value):
        raise _fail(f"{sheet}: cell {ref} is not finite")
    return value


def _build_series(
    layout: SheetLayout, cells: dict[tuple[str, int], _Cell]
) -> dict[str, NanfSeries]:
    out: dict[str, NanfSeries] = {}
    sheet = layout.name
    for block in layout.blocks:
        axis_rows = range(block.first_row, block.first_row + block.axis_count)
        axis = [
            _number(cells[(block.axis_letter, r)], sheet, f"{block.axis_letter}{r}")
            for r in axis_rows
        ]
        if any(b <= a for a, b in zip(axis, axis[1:], strict=False)):
            raise _fail(
                f"{sheet}: the axis in column {block.axis_letter} is not strictly increasing"
            )
        for s in block.series:
            xs: list[float] = []
            ys: list[float] = []
            flags: list[PointFlag] = []
            for i in range(s.count):
                row = block.first_row + i
                ref = f"{s.letter}{row}"
                xs.append(axis[i])
                if row in s.formula_rows:
                    ys.append(-math.inf)
                    flags.append(PointFlag.NON_FINITE_FORMULA)
                    continue
                value = _number(cells[(s.letter, row)], sheet, ref)
                flag = PointFlag.OK
                if s.quantity == "BER":
                    if not 0.0 <= value <= 1.0:
                        raise _fail(f"{sheet}: BER cell {ref} lies outside [0, 1]")
                    if value == 0.0:
                        flag, value = PointFlag.CENSORED_ZERO, math.nan
                    elif value < BER_CENSOR_FLOOR:
                        flag, value = PointFlag.CENSORED_BELOW_FLOOR, math.nan
                elif s.quantity in ("link_loss", "capacity", "latency") and value < 0.0:
                    raise _fail(f"{sheet}: cell {ref} is negative where the quantity cannot be")
                ys.append(value)
                flags.append(flag)
            last = block.first_row + s.count - 1
            out[series_key(sheet, block.label, s.header)] = NanfSeries(
                key=series_key(sheet, block.label, s.header),
                sheet=sheet,
                quantity=s.quantity,
                unit=s.unit,
                axis_name=block.axis_name,
                axis_unit=block.axis_unit,
                x=tuple(xs),
                y=tuple(ys),
                flags=tuple(flags),
                role=s.role,
                provenance=evidence_for(s.quantity, block.provenance),
                cells=f"{sheet}!{s.letter}{block.first_row}:{s.letter}{last}",
                unit_source=block.unit_source,
            )
    return out


def read_nanf_workbook(
    path: str | Path,
    *,
    include_holdout: bool = False,
    expected_sha256: str = NANF_WORKBOOK_SHA256,
) -> NanfWorkbook:
    """Read and verify the NANF workbook at an explicit local path (offline, read-only).

    `expected_sha256` is the recorded digest; pass another one only for a synthetic fixture. With
    `include_holdout=False` (the default) the holdout series are validated but not returned; ask
    for them only in the scoring step, after the Tx/Rx parameter vector is frozen and hashed.
    """
    file = Path(path)
    if not file.is_file():
        raise NanfImportError(SOURCE_MISSING, f"{file.name} is not present locally")
    with file.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise _fail("the file is larger than the importer accepts")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise NanfImportError(
            NOT_COMPARABLE, "the SHA-256 of the file differs from the recorded value"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as err:
        raise _fail("the file is not a zip archive") from err
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS or any(i.file_size > MAX_MEMBER_BYTES for i in infos):
            raise _fail("the archive has too many or too large members")
        names = {i.filename for i in infos}

        def member(name: str) -> bytes:
            if name not in names:
                raise _fail(f"the archive has no member {name}")
            try:
                return archive.read(name)
            except (
                zlib.error,
                zipfile.BadZipFile,
                EOFError,
                OSError,
                NotImplementedError,
                RuntimeError,
            ):
                # corrupt deflate stream, bad CRC, lying size, unsupported or encrypted member
                raise _fail(f"the archive member {name} cannot be read") from None

        book = _parse_xml(member("xl/workbook.xml"), "xl/workbook.xml")
        sheets = [
            (s.get("name", ""), s.get(f"{_REL_NS}id", ""), s.get("state", "visible"))
            for s in book.iter(f"{_NS}sheet")
        ]
        if [s[0] for s in sheets] != list(EXPECTED_SHEETS):
            raise _fail("the sheet list differs from the recorded layout")
        if any(s[2] != "visible" for s in sheets):
            raise _fail("a sheet is hidden")
        rels = _parse_xml(member("xl/_rels/workbook.xml.rels"), "workbook relationships")
        targets = {
            r.get("Id", ""): r.get("Target", "") for r in rels.iter(f"{_PKG_REL_NS}Relationship")
        }
        shared_root = _parse_xml(member("xl/sharedStrings.xml"), "xl/sharedStrings.xml")
        shared = [_string_item(si) for si in shared_root.iter(f"{_NS}si")]
        all_series: dict[str, NanfSeries] = {}
        for layout, (_, rid, _) in zip(SHEET_LAYOUTS, sheets, strict=True):
            target = targets.get(rid, "")
            if not re.fullmatch(r"worksheets/sheet[0-9]{1,2}\.xml", target):
                raise _fail(f"{layout.name}: the sheet part has an unexpected path")
            root = _parse_xml(member(f"xl/{target}"), f"{layout.name} sheet part")
            cells = _check_sheet(layout, root, shared)
            all_series.update(_build_series(layout, cells))
    kept = {
        k: s for k, s in all_series.items() if include_holdout or s.role is not DataRole.HOLDOUT
    }
    withheld = tuple(k for k in all_series if k not in kept)
    return NanfWorkbook(digest, kept, withheld)
