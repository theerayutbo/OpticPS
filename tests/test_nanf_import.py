"""Gate N2: the NANF workbook importer. Synthetic fixture only; passes with data/external absent.

Holdout discipline: these tests assert schema (counts, types, flags, roles, error codes) and never a
published value. The one test that opens the real workbook, when it is present, checks counts and
flags of the typed series and prints nothing.
"""

import hashlib
import io
import math
import re
import traceback
import zipfile
from pathlib import Path

import pytest

from nanf_workbook_fixture import SENTINEL, build_cells, make_workbook, serialise, write_xlsx
from opticps.benchmarks.provenance import ErrorCode
from opticps.measurement import nanf_import
from opticps.measurement.nanf_import import (
    EXPECTED_SHEETS,
    NANF_WORKBOOK_SHA256,
    SHEET_LAYOUTS,
    DataRole,
    NanfImportError,
    NanfSeries,
    PointFlag,
    read_nanf_workbook,
    series_key,
)
from opticps.optical_channel.fiber import ProvenanceCategory

REAL = Path("data/external/nanf_hong2021/extracted/dataset_JLT_NANF_vs_SMF.xlsx")


@pytest.fixture
def fixture_file(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    digest = make_workbook(path)
    return path, digest


def read(path, digest, **kw):
    return read_nanf_workbook(path, expected_sha256=digest, **kw)


# --- what a good file returns --------------------------------------------------------------------


def test_layout_has_the_ten_sheets_and_sixty_nine_series():
    assert EXPECTED_SHEETS == (
        "Fig.1", "Fig.4", "Fig.5", "Fig.6", "Fig.7", "Fig.8", "Fig.9", "Fig.10", "Fig.11", "Fig.12",
    )  # fmt: skip
    series = [s for layout in SHEET_LAYOUTS for b in layout.blocks for s in b.series]
    assert len(series) == 69
    keys = {
        series_key(layout.name, b.label, s.header)
        for layout in SHEET_LAYOUTS
        for b in layout.blocks
        for s in b.series
    }
    assert len(keys) == 69  # keys are unique


def test_default_read_withholds_the_holdout_and_keeps_the_rest(fixture_file):
    path, digest = fixture_file
    wb = read(path, digest)
    roles = {s.role for s in wb.series.values()}
    assert roles == {DataRole.CROSS_CHECK, DataRole.CALIBRATION, DataRole.CALIBRATION_INPUT}
    assert len(wb.series) == 21 and len(wb.withheld_holdout) == 48
    full = read(path, digest, include_holdout=True)
    assert len(full.series) == 69 and full.withheld_holdout == ()
    assert wb.sha256 == digest


def test_roles_follow_the_plan_section_2():
    by_role: dict[DataRole, set[str]] = {r: set() for r in DataRole}
    for layout in SHEET_LAYOUTS:
        for b in layout.blocks:
            for s in b.series:
                by_role[s.role].add(f"{layout.name}:{s.header}")
    assert {x.split(":")[0] for x in by_role[DataRole.CROSS_CHECK]} == {"Fig.1"}
    assert {x.split(":")[0] for x in by_role[DataRole.CALIBRATION_INPUT]} == {"Fig.5"}
    # calibration: only the three B2B BER and three B2B SNR series of Fig. 4
    assert by_role[DataRole.CALIBRATION] == {
        f"Fig.4:B2B-{rate}-{kind}" for rate in (80, 100, 112) for kind in ("BER", "SNR")
    }
    # every Fig. 6 series (B2B included) and Fig. 7 to 12 are holdout
    for sheet in ("Fig.6", "Fig.7", "Fig.8", "Fig.9", "Fig.10", "Fig.11", "Fig.12"):
        assert all(x.startswith(sheet) for x in by_role[DataRole.HOLDOUT] if x.startswith(sheet))
        assert not any(
            x.startswith(sheet)
            for r in (DataRole.CALIBRATION, DataRole.CROSS_CHECK)
            for x in by_role[r]
        )
    assert {"Fig.4:NANF-80-BER", "Fig.4:SMF-112-SNR"} <= by_role[DataRole.HOLDOUT]


def test_provenance_units_and_counts_per_series(fixture_file):
    path, digest = fixture_file
    wb = read(path, digest, include_holdout=True)
    fig1 = wb[series_key("Fig.1", "a-CD", "SSMF")]
    assert fig1.provenance is ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION
    assert (fig1.unit, fig1.axis_unit, len(fig1)) == ("ps/(nm km)", "um", 46)
    assert "axis labels" in fig1.unit_source
    assert wb[series_key("Fig.1", "d-latency", "NANF")].unit == "us"
    for key, s in wb.series.items():
        if s.sheet == "Fig.1":
            continue
        # results the paper reports are `measured`; ROP columns are settings (Sources vocabulary)
        expected = (
            ProvenanceCategory.PUBLISHED_EXPERIMENTAL
            if s.quantity == "ROP"
            else ProvenanceCategory.MEASURED
        )
        assert s.provenance is expected, key
    quantities = {s.quantity for s in wb.series.values() if s.sheet != "Fig.1"}
    assert quantities == {"BER", "SNR", "capacity", "link_loss", "ROP"}
    assert wb[series_key("Fig.5", "link", "NANF loss")].provenance is ProvenanceCategory.MEASURED
    assert (
        wb[series_key("Fig.5", "link", "ROP@NANF")].provenance
        is ProvenanceCategory.PUBLISHED_EXPERIMENTAL
    )
    sizes = {
        series_key("Fig.4", "BER@80", "NANF-80-BER"): 6,
        series_key("Fig.4", "BER@80", "B2B-80-BER"): 11,
        series_key("Fig.4", "SNR@112", "NANF-112-SNR"): 6,
        series_key("Fig.6", "BER@100", "NANF-100-BER"): 19,
        series_key("Fig.5", "link", "NANF loss"): 19,
        series_key("Fig.8", "table", "240sub-NANF-OFDM"): 240,
        series_key("Fig.9", "table", "NANF-OFDM-SNR"): 6,
        series_key("Fig.9", "table", "SMF-OFDM-SNR"): 8,
        series_key("Fig.12", "table", "NANF-DMT Capacity"): 6,
    }
    for key, n in sizes.items():
        assert len(wb[key]) == n, key
    assert wb[series_key("Fig.5", "link", "NANF loss")].unit == "dB"
    assert wb[series_key("Fig.12", "table", "SMF-DMT Capacity")].unit == "Gb/s"
    assert wb[series_key("Fig.7", "table", "NANF-BER")].unit == "1"


def test_inf_formula_cells_and_censored_ber_are_never_numbers(fixture_file):
    path, digest = fixture_file
    wb = read(path, digest, include_holdout=True)
    smf = wb[series_key("Fig.11", "table", "240sub-SMF-DMT")]
    assert len(smf) == 240 and smf.n_non_finite == 24
    flagged = {i + 2 for i, f in enumerate(smf.flags) if f is PointFlag.NON_FINITE_FORMULA}
    assert flagged == {163, *range(165, 188)}  # row numbers; C164 is a plain number
    assert all(
        math.isinf(y) and y < 0
        for y, f in zip(smf.y, smf.flags, strict=True)
        if f is not PointFlag.OK
    )
    assert smf.flags[163 - 2] is PointFlag.NON_FINITE_FORMULA and smf.flags[164 - 2] is PointFlag.OK
    ber = wb[series_key("Fig.4", "BER@80", "B2B-80-BER")]
    assert (
        ber.flags[0] is PointFlag.CENSORED_ZERO and ber.flags[1] is PointFlag.CENSORED_BELOW_FLOOR
    )
    assert math.isnan(ber.y[0]) and math.isnan(ber.y[1])  # NaN, not 0 and not 5e-6
    assert ber.n_censored == 2 and all(f is PointFlag.OK for f in ber.flags[2:])
    assert all(not math.isnan(y) and 0 < y <= 1 for y in ber.y[2:])
    # a non-BER series is never censored; a BER at exactly the floor is a number
    assert wb[series_key("Fig.4", "SNR@80", "B2B-80-SNR")].n_censored == 0


def test_a_ber_at_exactly_the_floor_is_a_number_and_just_below_it_is_censored(tmp_path):
    cells = build_cells(lambda sheet, header, i, x: {2: 1e-5, 3: 9.99e-6}.get(i))
    path = tmp_path / "f.xlsx"
    digest = make_workbook(path, cells)
    ber = read(path, digest)[series_key("Fig.4", "BER@80", "B2B-80-BER")]
    # i = 0 and 1 follow the default (censored); i = 2 is exactly 1e-5; i = 3 is below it
    assert ber.flags[2] is PointFlag.OK and ber.y[2] == 1e-5
    assert ber.flags[3] is PointFlag.CENSORED_BELOW_FLOOR


def test_series_pairs_each_point_with_the_axis_value_of_its_row(fixture_file):
    path, digest = fixture_file
    s = read(path, digest, include_holdout=True)[series_key("Fig.4", "BER@80", "NANF-80-BER")]
    assert s.x == tuple(-12.0 + 0.5 * i for i in range(6))
    assert s.cells == "Fig.4!B4:B9"


# --- holdout discipline: nothing prints a holdout value --------------------------------------------


def test_a_holdout_series_prints_without_values(fixture_file):
    path, digest = fixture_file
    wb = read(path, digest, include_holdout=True)
    cap = wb[series_key("Fig.12", "table", "SMF-DMT Capacity")]
    assert cap.y[0] == SENTINEL  # present for the scoring step
    for text in (repr(cap), str(cap), f"{cap}", repr(wb.series[cap.key]), f"{cap!r}"):
        assert str(SENTINEL) not in text and "424242" not in text
        assert "values hidden" in text
    cal = wb[series_key("Fig.4", "SNR@80", "B2B-80-SNR")]
    assert "values hidden" not in repr(cal) and cal.role is DataRole.CALIBRATION


def test_the_default_object_holds_no_holdout_value_anywhere(fixture_file):
    path, digest = fixture_file
    wb = read(path, digest)
    assert str(SENTINEL) not in repr(wb.series) and "424242" not in repr(wb.series)
    with pytest.raises(KeyError):
        wb[series_key("Fig.12", "table", "SMF-DMT Capacity")]


# --- refusals: source, checksum, format ------------------------------------------------------------


def test_error_codes_use_the_benchmark_vocabulary():
    assert nanf_import.SOURCE_MISSING == ErrorCode.SOURCE_MISSING.value
    assert nanf_import.NOT_COMPARABLE == ErrorCode.NOT_COMPARABLE.value
    assert nanf_import.FORMAT_UNKNOWN == ErrorCode.FORMAT_UNKNOWN.value


def test_a_missing_file_is_source_missing_and_a_wrong_hash_is_not_comparable(
    tmp_path, fixture_file
):
    with pytest.raises(NanfImportError) as missing:
        read_nanf_workbook(tmp_path / "absent.xlsx")
    assert missing.value.code == "SOURCE_MISSING"
    with pytest.raises(NanfImportError) as directory:
        read_nanf_workbook(tmp_path)
    assert directory.value.code == "SOURCE_MISSING"
    path, _ = fixture_file
    with pytest.raises(NanfImportError) as wrong:
        read_nanf_workbook(path)  # the recorded hash is the real workbook's
    assert wrong.value.code == "NOT_COMPARABLE"
    assert "SHA-256" in str(wrong.value)


def test_the_hash_is_checked_before_anything_is_parsed(tmp_path):
    path = tmp_path / "junk.xlsx"
    path.write_bytes(b"not a zip at all")
    with pytest.raises(NanfImportError) as err:
        read_nanf_workbook(path)
    assert err.value.code == "NOT_COMPARABLE"  # not FORMAT_UNKNOWN: the hash came first
    digest = hashlib.sha256(b"not a zip at all").hexdigest()
    with pytest.raises(NanfImportError) as err2:
        read_nanf_workbook(path, expected_sha256=digest)
    assert err2.value.code == "FORMAT_UNKNOWN"


def test_the_recorded_hash_is_the_one_in_the_sources_document():
    text = Path("docs/NANF_SOURCES_AND_PROVENANCE.md").read_text()
    assert NANF_WORKBOOK_SHA256 in text
    assert re.fullmatch(r"[0-9a-f]{64}", NANF_WORKBOOK_SHA256)


def test_the_file_is_read_only_and_unchanged(fixture_file):
    path, digest = fixture_file
    before = (path.stat().st_mtime_ns, path.read_bytes())
    read(path, digest, include_holdout=True)
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


# --- default-deny on any schema mismatch ------------------------------------------------------------


def refused(tmp_path, cells=None, expect="FORMAT_UNKNOWN", **kwargs):
    path = tmp_path / "mutant.xlsx"
    digest = make_workbook(path, cells, **kwargs)
    with pytest.raises(NanfImportError) as err:
        read(path, digest, include_holdout=True)
    assert err.value.code == expect
    assert str(SENTINEL) not in str(err.value) and "424242" not in str(err.value)
    return str(err.value)


def mutated(fn):
    cells = build_cells()
    fn(cells)
    return cells


def test_an_unexpected_sheet_or_a_renamed_sheet_is_refused(tmp_path):
    names = list(EXPECTED_SHEETS)
    refused(tmp_path, sheet_names=[*names[:-1], "Fig.13"])
    refused(tmp_path, sheet_names=[names[1], names[0], *names[2:]])  # order is part of the layout
    # an eleventh sheet: build the members, then add one to the workbook list
    parts = serialise(build_cells())
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        b"</sheets>",
        b'<sheet name="Extra" sheetId="11" r:id="rId11" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>',
    )
    path = tmp_path / "eleven.xlsx"
    digest = write_xlsx(path, parts)
    with pytest.raises(NanfImportError) as err:
        read(path, digest)
    assert err.value.code == "FORMAT_UNKNOWN" and "sheet list" in str(err.value)


def test_a_hidden_sheet_is_refused(tmp_path):
    assert "hidden" in refused(tmp_path, hidden={"Fig.8"})


def test_a_changed_header_title_dimension_or_merge_is_refused(tmp_path):
    def rename(cells):
        cells["Fig.4"]["B3"] = ("s", "NANF-80-BER-renamed", None)

    assert "B3" in refused(tmp_path, mutated(rename))

    def retitle(cells):
        cells["Fig.6"]["A1"] = ("s", "Fig.6(a) SNR@80Gb/s ", None)

    assert "A1" in refused(tmp_path, mutated(retitle))
    assert "dimension" in refused(tmp_path, dimensions={"Fig.8": "A1:C242"})
    assert "merged" in refused(tmp_path, merges={"Fig.4": ("A1:D1",)})


def test_the_header_message_does_not_echo_what_was_found(tmp_path):
    def rename(cells):
        cells["Fig.4"]["B3"] = ("s", "SECRET-HEADER-TEXT", None)

    assert "SECRET-HEADER-TEXT" not in refused(tmp_path, mutated(rename))


def test_an_unexpected_cell_a_missing_cell_and_a_wrong_count_are_refused(tmp_path):
    def extra_value(cells):
        cells["Fig.8"]["D2"] = ("n", str(SENTINEL), None)

    assert "D2" in refused(tmp_path, mutated(extra_value))

    def extra_row(cells):  # the NANF Fig. 4 series has 6 points; a 7th is a count mismatch
        cells["Fig.4"]["B10"] = ("n", str(SENTINEL), None)

    assert "B10" in refused(tmp_path, mutated(extra_row))

    def drop_one(cells):
        del cells["Fig.9"]["C7"]  # NANF-OFDM-BER loses a point

    assert "absent" in refused(tmp_path, mutated(drop_one))

    def extra_text(cells):
        cells["Fig.7"]["F1"] = ("s", "SECRET-COLUMN", None)

    message = refused(tmp_path, mutated(extra_text))
    assert "F1" in message and "SECRET-COLUMN" not in message


def test_an_empty_styled_cell_is_not_content_but_a_wrong_type_is(tmp_path):
    def styled(cells):
        cells["Fig.4"]["B12"] = ("empty", "", None)  # beyond the 6 NANF points, no value

    path = tmp_path / "ok.xlsx"
    digest = make_workbook(path, mutated(styled))
    assert read(path, digest, include_holdout=True)

    def text_in_number(cells):
        cells["Fig.4"]["B5"] = ("s", "n/a", None)

    assert "B5" in refused(tmp_path, mutated(text_in_number))

    def str_formula_result(cells):
        cells["Fig.4"]["B5"] = ("str", "1.0", None)

    assert "B5" in refused(tmp_path, mutated(str_formula_result))

    def number_with_formula(cells):
        cells["Fig.4"]["B5"] = ("n", "1.0", "<f>1+1</f>")

    assert "B5" in refused(tmp_path, mutated(number_with_formula))


def test_error_cells_are_accepted_only_where_the_layout_says_and_only_as_minus_inf(tmp_path):
    def error_elsewhere(cells):
        cells["Fig.11"]["C164"] = ("e", "#NAME?", "<f>-Inf</f>")  # the one number in the span

    assert "C164" in refused(tmp_path, mutated(error_elsewhere))

    def other_formula(cells):
        cells["Fig.11"]["C163"] = ("e", "#NAME?", "<f>1/0</f>")

    assert "C163" in refused(tmp_path, mutated(other_formula))

    def number_where_formula(cells):
        cells["Fig.11"]["C170"] = ("n", "1.0", None)

    assert "C170" in refused(tmp_path, mutated(number_where_formula))

    def error_in_other_sheet(cells):
        cells["Fig.8"]["C10"] = ("e", "#DIV/0!", "<f>-Inf</f>")

    assert "C10" in refused(tmp_path, mutated(error_in_other_sheet))


def test_value_domains_are_default_deny_without_echoing_the_value(tmp_path):
    def ber_above_one(cells):
        cells["Fig.7"]["B5"] = ("n", "1.5", None)

    assert "BER" in refused(tmp_path, mutated(ber_above_one))

    def ber_negative(cells):
        cells["Fig.10"]["C4"] = ("n", "-0.001", None)

    assert "BER" in refused(tmp_path, mutated(ber_negative))

    def negative_loss(cells):
        cells["Fig.5"]["D4"] = ("n", "-1.0", None)

    assert "negative" in refused(tmp_path, mutated(negative_loss))

    def negative_capacity(cells):
        cells["Fig.12"]["B3"] = ("n", f"-{SENTINEL}", None)

    assert "negative" in refused(tmp_path, mutated(negative_capacity))

    for bad in ("nan", "inf", "-inf", "1e999", "abc", ""):

        def not_finite(cells, bad=bad):
            cells["Fig.8"]["B7"] = ("n", bad, None)

        refused(tmp_path, mutated(not_finite))


def test_an_axis_that_is_not_strictly_increasing_is_refused(tmp_path):
    def repeat(cells):
        cells["Fig.8"]["A5"] = cells["Fig.8"]["A4"]

    assert "strictly increasing" in refused(tmp_path, mutated(repeat))

    def reverse(cells):
        cells["Fig.4"]["F5"] = ("n", "-100.0", None)

    assert "strictly increasing" in refused(tmp_path, mutated(reverse))


def test_xml_with_a_doctype_or_an_entity_or_utf16_is_refused(tmp_path):
    entity = '<!DOCTYPE x [<!ENTITY e "boom">]>'
    assert "DOCTYPE" in refused(tmp_path, prolog=entity)
    assert "DOCTYPE" in refused(tmp_path, prolog="<!DOCTYPE worksheet>")  # no entity needed
    # the same text in UTF-16 would hide the marker from a byte search
    parts = serialise(build_cells())
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].decode().encode("utf-16")
    path = tmp_path / "u16.xlsx"
    digest = write_xlsx(path, parts)
    with pytest.raises(NanfImportError) as err:
        read(path, digest)
    assert err.value.code == "FORMAT_UNKNOWN"


def test_a_malformed_part_a_missing_part_and_a_bad_path_are_refused(tmp_path):
    def broken(mutate):
        parts = serialise(build_cells())
        mutate(parts)
        path = tmp_path / "broken.xlsx"
        digest = write_xlsx(path, parts)
        with pytest.raises(NanfImportError) as err:
            read(path, digest)
        assert err.value.code == "FORMAT_UNKNOWN"
        return str(err.value)

    assert "well-formed" in broken(lambda p: p.update({"xl/sharedStrings.xml": b"<sst"}))
    assert "no member" in broken(lambda p: p.pop("xl/sharedStrings.xml"))
    assert "no member" in broken(lambda p: p.pop("xl/worksheets/sheet3.xml"))
    assert "unexpected path" in broken(
        lambda p: p.update(
            {
                "xl/_rels/workbook.xml.rels": p["xl/_rels/workbook.xml.rels"].replace(
                    b"worksheets/sheet2.xml", b"../../etc/sheet2.xml"
                )
            }
        )
    )
    assert "bad shared-string" in broken(
        lambda p: p.update(
            {
                "xl/worksheets/sheet3.xml": re.sub(
                    rb't="s"><v>\d+</v>',
                    b't="s"><v>9999</v>',
                    p["xl/worksheets/sheet3.xml"],
                    count=1,
                )
            }
        )
    )


def test_a_cell_given_twice_and_a_bad_reference_are_refused(tmp_path):
    parts = serialise(build_cells())
    sheet = parts["xl/worksheets/sheet5.xml"].decode()
    duplicated = sheet.replace("</row>", '<c r="A2"><v>1.0</v></c></row>', 1)
    parts["xl/worksheets/sheet5.xml"] = duplicated.encode()
    path = tmp_path / "dup.xlsx"
    digest = write_xlsx(path, parts)
    with pytest.raises(NanfImportError, match="given twice"):
        read(path, digest)
    parts = serialise(build_cells())
    parts["xl/worksheets/sheet5.xml"] = (
        parts["xl/worksheets/sheet5.xml"].decode().replace('r="A2"', 'r="2A"', 1).encode()
    )
    digest = write_xlsx(path, parts)
    with pytest.raises(NanfImportError, match="valid reference"):
        read(path, digest)


def test_an_oversized_file_or_archive_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "f.xlsx"
    digest = make_workbook(path)
    monkeypatch.setattr(nanf_import, "MAX_FILE_BYTES", 100)
    with pytest.raises(NanfImportError, match="larger"):
        read(path, digest)
    monkeypatch.setattr(nanf_import, "MAX_FILE_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(nanf_import, "MAX_MEMBER_BYTES", 100)
    with pytest.raises(NanfImportError, match="too many or too large"):
        read(path, digest)


def test_series_validates_its_own_lengths():
    with pytest.raises(ValueError, match="one entry per point"):
        NanfSeries(
            "k", "s", "SNR", "dB", "x", "1", (1.0,), (1.0, 2.0), (PointFlag.OK,),
            DataRole.CALIBRATION, ProvenanceCategory.PUBLISHED_EXPERIMENTAL, "c",
        )  # fmt: skip


def test_the_importer_has_no_spreadsheet_or_network_dependency():
    source = Path(nanf_import.__file__).read_text()
    imports = set(re.findall(r"^(?:import|from) ([a-zA-Z_][\w.]*)", source, re.M))
    assert not imports & {"openpyxl", "xlrd", "pandas", "requests", "urllib", "socket", "http"}
    assert "open(" not in source.replace("file.open(", "").replace("archive", "")
    assert '"wb"' not in source and "'w'" not in source


# --- Gate N2 fix round: messages, causes, archive faults, inline strings --------------------------


def broken_parts(tmp_path, mutate, **read_kw):
    parts = serialise(build_cells())
    mutate(parts)
    path = tmp_path / "broken.xlsx"
    digest = write_xlsx(path, parts)
    return path, digest


def test_a_cell_that_is_not_a_plain_number_never_echoes_what_it_holds(tmp_path):
    def text_in_number(cells):
        cells["Fig.8"]["B7"] = ("s", "424242-secret", None)

    message = refused(tmp_path, mutated(text_in_number))
    assert "B7" in message and "plain number" in message and "secret" not in message

    def formula_in_number(cells):
        cells["Fig.8"]["B7"] = ("n", "424242.5", "<f>424242+1</f>")

    message = refused(tmp_path, mutated(formula_in_number))
    assert "plain number" in message and "424242" not in message


def test_a_ber_outside_zero_one_never_echoes_the_value(tmp_path):
    for bad in ("424242.5", "-424242.5", "1.0000001"):

        def ber(cells, bad=bad):
            cells["Fig.7"]["B5"] = ("n", bad, None)

        message = refused(tmp_path, mutated(ber))
        assert "BER" in message and "B5" in message and "424242" not in message
        assert "1.0000001" not in message


def test_a_non_number_leaves_no_cause_or_context_holding_the_cell_text(tmp_path):
    def junk(cells):
        cells["Fig.8"]["B7"] = ("n", "abc424242secret", None)

    path = tmp_path / "junk.xlsx"
    digest = make_workbook(path, mutated(junk))
    with pytest.raises(NanfImportError) as err:
        read(path, digest, include_holdout=True)
    assert err.value.__cause__ is None and err.value.__context__ is None
    shown = "".join(traceback.format_exception(err.value))
    assert "secret" not in shown and "424242" not in shown

    def index(parts):
        parts["xl/worksheets/sheet3.xml"] = re.sub(
            rb't="s"><v>\d+</v>', b't="s"><v>9999</v>', parts["xl/worksheets/sheet3.xml"], count=1
        )

    path, digest = broken_parts(tmp_path, index)
    with pytest.raises(NanfImportError, match="bad shared-string") as err:
        read(path, digest)
    assert err.value.__cause__ is None and err.value.__context__ is None


def test_a_nul_byte_or_utf16_with_a_hidden_doctype_is_refused_as_not_plain_utf8(tmp_path):
    def nul(parts):
        sheet = parts["xl/worksheets/sheet5.xml"]
        parts["xl/worksheets/sheet5.xml"] = sheet.replace(b"<sheetData>", b"<sheetData>\x00", 1)

    path, digest = broken_parts(tmp_path, nul)
    with pytest.raises(NanfImportError, match="plain UTF-8"):
        read(path, digest)

    def utf16(parts):
        text = parts["xl/worksheets/sheet5.xml"].decode()
        text = text.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace(
            "<worksheet", '<!DOCTYPE worksheet [<!ENTITY e "x">]><worksheet', 1
        )
        parts["xl/worksheets/sheet5.xml"] = text.encode("utf-16")  # declared and with a BOM

    path, digest = broken_parts(tmp_path, utf16)
    with pytest.raises(NanfImportError, match="plain UTF-8"):
        read(path, digest)


def test_the_member_count_is_capped(tmp_path):
    def many(parts):
        for k in range(nanf_import.MAX_MEMBERS + 1):
            parts[f"xl/extra{k}.bin"] = b"x"

    path, digest = broken_parts(tmp_path, many)
    with pytest.raises(NanfImportError, match="too many or too large"):
        read(path, digest)

    def just_enough(parts):
        for k in range(nanf_import.MAX_MEMBERS - len(parts)):
            parts[f"xl/extra{k}.bin"] = b"x"

    path, digest = broken_parts(tmp_path, just_enough)
    assert read(path, digest)


def test_rich_text_runs_are_joined_and_phonetic_text_is_ignored(tmp_path):
    def rich(parts):
        sst = parts["xl/sharedStrings.xml"].decode()
        old = '<si><t xml:space="preserve">SMF-BER</t></si>'
        assert old in sst
        parts["xl/sharedStrings.xml"] = sst.replace(
            old,
            "<si><r><t>SMF-</t></r><r><t>BER</t></r><rPh><t>PHONETIC</t></rPh></si>",
        ).encode()

    path, digest = broken_parts(tmp_path, rich)
    assert read(path, digest, include_holdout=True)

    def phonetic_only_changes_nothing(parts):
        sst = parts["xl/sharedStrings.xml"].decode()
        old = '<si><t xml:space="preserve">SMF-BER</t></si>'
        parts["xl/sharedStrings.xml"] = sst.replace(
            old, "<si><r><t>SMF-</t></r><r><t>BER2</t></r></si>"
        ).encode()

    path, digest = broken_parts(tmp_path, phonetic_only_changes_nothing)
    with pytest.raises(NanfImportError, match="header"):
        read(path, digest, include_holdout=True)


def test_a_shared_formula_needs_its_master_and_a_child_resolves_to_it(tmp_path):
    def orphan(parts):
        sheet = parts["xl/worksheets/sheet9.xml"].decode()
        assert '<f t="shared" si="0"/>' in sheet
        sheet = sheet.replace(
            '<f t="shared" ref="C165:C187" si="0">-Inf</f>', '<f t="shared" si="7"/>', 1
        )
        assert 'si="0">' not in sheet
        parts["xl/worksheets/sheet9.xml"] = sheet.encode()

    path, digest = broken_parts(tmp_path, orphan)
    with pytest.raises(NanfImportError, match="no master"):
        read(path, digest, include_holdout=True)
    # the unmodified fixture uses a master and children, and is accepted
    path2 = tmp_path / "ok.xlsx"
    digest2 = make_workbook(path2)
    wb = read(path2, digest2, include_holdout=True)
    assert wb[series_key("Fig.11", "table", "240sub-SMF-DMT")].n_non_finite == 24


def test_an_inline_string_outside_the_layout_is_refused_like_one_inside(tmp_path):
    inline = '<c r="{ref}" t="inlineStr"><is><t>424242-secret</t></is></c>'

    def outside(parts):
        sheet = parts["xl/worksheets/sheet5.xml"].decode()
        parts["xl/worksheets/sheet5.xml"] = sheet.replace(
            "</row>", inline.format(ref="Z99") + "</row>", 1
        ).encode()

    path, digest = broken_parts(tmp_path, outside)
    with pytest.raises(NanfImportError, match="unexpected content at Z99") as err:
        read(path, digest, include_holdout=True)
    assert "secret" not in str(err.value) and "424242" not in str(err.value)

    def inside(parts):
        sheet = parts["xl/worksheets/sheet5.xml"].decode()
        parts["xl/worksheets/sheet5.xml"] = re.sub(
            r'<c r="B4"[^>]*>.*?</c>', inline.format(ref="B4"), sheet, count=1
        ).encode()

    path, digest = broken_parts(tmp_path, inside)
    with pytest.raises(NanfImportError, match="B4"):
        read(path, digest, include_holdout=True)


def corrupt_archive(tmp_path, damage):
    """A zip whose directory is intact and whose stored sheet member is damaged; SHA matches."""
    parts = serialise(build_cells())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    raw = bytearray(buffer.getvalue())
    damage(raw, parts)
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(bytes(raw))
    return path, hashlib.sha256(bytes(raw)).hexdigest()


def test_a_corrupt_archive_member_raises_the_typed_error_not_zlib_or_badzipfile(tmp_path):
    def local_header(raw, name):
        pos = bytes(raw).index(name.encode())
        return pos - 30  # start of its local file header

    def flip_deflate(raw, parts):
        start = local_header(raw, "xl/worksheets/sheet5.xml")
        name_len = int.from_bytes(raw[start + 26 : start + 28], "little")
        extra_len = int.from_bytes(raw[start + 28 : start + 30], "little")
        data = start + 30 + name_len + extra_len
        for k in range(8):  # destroy the head of the deflate stream
            raw[data + k] = 0xFF

    def bad_crc(raw, parts):
        start = local_header(raw, "xl/worksheets/sheet5.xml")
        raw[start + 14] ^= 0xFF  # CRC-32 in the local header
        central = bytes(raw).index(b"PK\x01\x02" + b"")  # first central entry is another member
        while True:
            name_len = int.from_bytes(raw[central + 28 : central + 30], "little")
            name = bytes(raw[central + 46 : central + 46 + name_len])
            if name == b"xl/worksheets/sheet5.xml":
                raw[central + 16] ^= 0xFF  # CRC-32 in the central directory
                return
            extra = int.from_bytes(raw[central + 30 : central + 32], "little")
            comment = int.from_bytes(raw[central + 32 : central + 34], "little")
            central += 46 + name_len + extra + comment

    for damage in (flip_deflate, bad_crc):
        path, digest = corrupt_archive(tmp_path, damage)
        with pytest.raises(NanfImportError) as err:
            read(path, digest, include_holdout=True)
        assert err.value.code == "FORMAT_UNKNOWN" and "cannot be read" in str(err.value)


def test_fig4_points_above_the_minus_five_dbm_cap_are_flagged_on_return(tmp_path):
    def rop_axis(sheet, block, i):
        return -12.0 + 1.0 * i  # 11 points, -12 to -2 dBm

    path = tmp_path / "rop.xlsx"
    digest = make_workbook(path, build_cells(axis_fn=rop_axis))
    wb = read(path, digest, include_holdout=True)
    b2b = wb[series_key("Fig.4", "BER@80", "B2B-80-BER")]
    assert b2b.role is DataRole.CALIBRATION and len(b2b) == 11
    assert b2b.above_rop_cap == (False,) * 8 + (True,) * 3  # -4, -3, -2 dBm
    snr = wb[series_key("Fig.4", "SNR@100", "B2B-100-SNR")]
    assert sum(snr.above_rop_cap) == 3
    nanf = wb[series_key("Fig.4", "BER@80", "NANF-80-BER")]
    assert len(nanf.above_rop_cap) == 6 and not any(nanf.above_rop_cap)  # -12 to -7
    # exactly -5 dBm is scored (the cap is "at most -5 dBm"), and other sheets are never flagged
    assert nanf_import.ROP_SCORING_CAP_DBM == -5.0
    assert b2b.above_rop_cap[7] is False and b2b.x[7] == -5.0
    assert not any(wb[series_key("Fig.5", "link", "ROP@NANF")].above_rop_cap)


# --- the real workbook, if present: schema only, nothing printed ----------------------------------


@pytest.mark.skipif(not REAL.is_file(), reason="data/external/nanf_hong2021 is absent")
def test_the_real_workbook_matches_the_recorded_layout_schema_only():
    wb = read_nanf_workbook(REAL, include_holdout=True)
    assert wb.sha256 == NANF_WORKBOOK_SHA256 and len(wb.series) == 69
    counts = {}
    for s in wb.series.values():
        counts[s.sheet] = counts.get(s.sheet, 0) + 1
        assert len(s.x) == len(s.y) == len(s.flags) and len(s) > 0
        assert all(math.isfinite(v) for v in s.x)
    assert counts == {
        "Fig.1": 12, "Fig.4": 18, "Fig.5": 3, "Fig.6": 18, "Fig.7": 4, "Fig.8": 2, "Fig.9": 4,
        "Fig.10": 2, "Fig.11": 2, "Fig.12": 4,
    }  # fmt: skip
    # the structure facts of the Sources document, as counts of flagged points
    assert wb[series_key("Fig.11", "table", "240sub-SMF-DMT")].n_non_finite == 24
    assert sum(s.n_non_finite for s in wb.series.values()) == 24
    for s in wb.series.values():
        if s.quantity != "BER":
            assert s.n_censored == 0
    default = read_nanf_workbook(REAL)
    assert len(default.series) == 21 and len(default.withheld_holdout) == 48
    assert not any(s.role is DataRole.HOLDOUT for s in default.series.values())


@pytest.mark.skipif(not REAL.is_file(), reason="data/external/nanf_hong2021 is absent")
def test_a_copy_of_the_real_workbook_with_one_byte_changed_is_not_comparable(tmp_path):
    data = bytearray(REAL.read_bytes())
    data[-1] ^= 1
    copy_path = tmp_path / "copy.xlsx"
    copy_path.write_bytes(bytes(data))
    with pytest.raises(NanfImportError) as err:
        read_nanf_workbook(copy_path)
    assert err.value.code == "NOT_COMPARABLE"
    assert zipfile.is_zipfile(REAL)
