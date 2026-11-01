"""A synthetic stand-in for the NANF workbook, made here from the importer's recorded layout.

Every number is invented by this module (smooth made-up functions and a few sentinel values). It is
not third-party data and holds nothing of the real file. The layout (sheets, headers, columns, row
counts, merged ranges) is the importer's own `SHEET_LAYOUTS`; the structure was checked once against
the real workbook, so the fixture lets the importer tests run with `data/external` absent.
"""

import hashlib
import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

from opticps.measurement.nanf_import import SHEET_LAYOUTS, SheetLayout

SENTINEL = 424242.5  # a value no test may see in any message or repr (a holdout capacity)
Cell = tuple[str, str, str | None]  # (kind, text, formula xml); kind "n", "s", "e"
Cells = dict[str, dict[str, Cell]]  # sheet -> reference -> cell
ValueFn = Callable[[str, str, int, float], float | None]
AxisFn = Callable[[str, str, int], float]

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def default_value(sheet: str, header: str, index: int, x: float) -> float | None:
    """Invented, smooth, plausible-looking values; None leaves the default to the caller."""
    if "BER" in header:
        # first point censored zero, second below 1e-5, then falling through the 3.8e-3 level
        return (0.0, 5e-6)[index] if index < 2 else 10 ** (-1.5 - 0.3 * index)
    if "Capacity" in header:
        return SENTINEL if index == 0 else 100.0 + index
    if "loss" in header:
        return 6.5 + 0.01 * index
    if "ROP" in header:
        return -9.0 + 0.1 * index
    return 10.0 + 0.5 * index + 0.1 * len(header)


def default_axis(sheet: str, block: str, index: int) -> float:
    return -12.0 + 0.5 * index


def build_cells(value_fn: ValueFn | None = None, axis_fn: AxisFn | None = None) -> Cells:
    fn = value_fn or default_value
    axis_of = axis_fn or default_axis
    cells: Cells = {}
    for layout in SHEET_LAYOUTS:
        sheet = cells.setdefault(layout.name, {})
        for ref, title in layout.titles.items():
            sheet[ref] = ("s", title, None)
        for block in layout.blocks:
            sheet[f"{block.axis_letter}{block.top}"] = ("s", block.axis_header, None)
            axis_values = [axis_of(layout.name, block.label, i) for i in range(block.axis_count)]
            for i, a in enumerate(axis_values):
                sheet[f"{block.axis_letter}{block.first_row + i}"] = ("n", repr(a), None)
            for s in block.series:
                sheet[f"{s.letter}{block.top}"] = ("s", s.header, None)
                for i in range(s.count):
                    ref = f"{s.letter}{block.first_row + i}"
                    row = block.first_row + i
                    if row in s.formula_rows:
                        master = min(s.formula_rows - {163})
                        if row == 163:
                            sheet[ref] = ("e", "#NAME?", "<f>-Inf</f>")
                        elif row == master:
                            sheet[ref] = (
                                "e",
                                "#NAME?",
                                f'<f t="shared" ref="{s.letter}{master}:{s.letter}{max(s.formula_rows)}" si="0">-Inf</f>',
                            )
                        else:
                            sheet[ref] = ("e", "#NAME?", '<f t="shared" si="0"/>')
                        continue
                    value = fn(layout.name, s.header, i, axis_values[i])
                    if value is None:
                        value = default_value(layout.name, s.header, i, axis_values[i])
                    assert value is not None
                    sheet[ref] = ("n", repr(float(value)), None)
    return cells


def _col_number(ref: str) -> tuple[int, int]:
    letters = "".join(c for c in ref if c.isalpha())
    row = int("".join(c for c in ref if c.isdigit()))
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return row, n


def serialise(
    cells: Cells,
    *,
    layouts: tuple[SheetLayout, ...] = SHEET_LAYOUTS,
    sheet_names: list[str] | None = None,
    dimensions: dict[str, str] | None = None,
    merges: dict[str, tuple[str, ...]] | None = None,
    hidden: set[str] | None = None,
    extra_xml: dict[str, str] | None = None,
    prolog: str = "",
) -> dict[str, bytes]:
    """Build the zip members of a workbook from a cell model."""
    names = sheet_names or [layout.name for layout in layouts]
    strings: list[str] = []

    def shared(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    parts: dict[str, bytes] = {}
    sheet_entries, rel_entries = [], []
    for k, (name, layout) in enumerate(zip(names, layouts, strict=True), start=1):
        rows: dict[int, list[tuple[int, str]]] = {}
        for ref, (kind, text, formula) in cells.get(layout.name, {}).items():
            row, col = _col_number(ref)
            if kind == "s":
                xml = f'<c r="{ref}" t="s"><v>{shared(text)}</v></c>'
            elif kind == "e":
                xml = f'<c r="{ref}" t="e">{formula or ""}<v>{escape(text)}</v></c>'
            elif kind == "str":
                xml = f'<c r="{ref}" t="str"><v>{escape(text)}</v></c>'
            elif kind == "empty":
                xml = f'<c r="{ref}"/>'
            else:
                xml = f'<c r="{ref}">{formula or ""}<v>{escape(text)}</v></c>'
            rows.setdefault(row, []).append((col, xml))
        body = "".join(
            f'<row r="{r}">{"".join(x for _, x in sorted(items))}</row>'
            for r, items in sorted(rows.items())
        )
        dim = (dimensions or {}).get(layout.name, layout.dimension)
        merge_refs = (merges or {}).get(layout.name, layout.merges)
        merge_xml = (
            f'<mergeCells count="{len(merge_refs)}">'
            + "".join(f'<mergeCell ref="{m}"/>' for m in merge_refs)
            + "</mergeCells>"
            if merge_refs
            else ""
        )
        extra = (extra_xml or {}).get(layout.name, "")
        parts[f"xl/worksheets/sheet{k}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{prolog}'
            f'<worksheet xmlns="{MAIN}"><dimension ref="{dim}"/><sheetData>{body}</sheetData>'
            f"{merge_xml}{extra}</worksheet>"
        ).encode()
        state = ' state="hidden"' if hidden and name in hidden else ""
        sheet_entries.append(
            f'<sheet name="{escape(name)}" sheetId="{k}"{state} xmlns:r="{REL}" r:id="rId{k}"/>'
        )
        rel_entries.append(
            f'<Relationship Id="rId{k}" Type="{REL}/worksheet" Target="worksheets/sheet{k}.xml"/>'
        )
    parts["xl/workbook.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{MAIN}"><sheets>{"".join(sheet_entries)}</sheets></workbook>'
    ).encode()
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rel_entries)}</Relationships>"
    ).encode()
    parts["xl/sharedStrings.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{MAIN}">'
        + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings)
        + "</sst>"
    ).encode()
    return parts


def write_xlsx(path: Path, parts: dict[str, bytes]) -> str:
    """Write the members as a zip and return the SHA-256 of the file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def make_workbook(path: Path, cells: Cells | None = None, **kwargs) -> str:  # type: ignore[no-untyped-def]
    return write_xlsx(path, serialise(cells if cells is not None else build_cells(), **kwargs))
