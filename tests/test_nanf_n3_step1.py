"""Gate N3 step 1: guards closed after the second N2 review (QA5 survivors and new guards).

Synthetic workbook only; passes with data/external absent.
"""

import re
import zipfile
import zlib

import pytest

from nanf_workbook_fixture import build_cells, make_workbook, serialise, write_xlsx
from opticps.measurement import nanf_benchmark as nb
from opticps.measurement.nanf_import import NanfImportError, read_nanf_workbook


def _read(path, digest):
    return read_nanf_workbook(path, expected_sha256=digest)


def _with_shared_index(tmp_path, text: str):
    parts = serialise(build_cells())
    parts["xl/worksheets/sheet3.xml"] = re.sub(
        rb't="s"><v>\d+</v>', b't="s"><v>' + text.encode() + b"</v>",
        parts["xl/worksheets/sheet3.xml"], count=1,
    )  # fmt: skip
    path = tmp_path / "idx.xlsx"
    return path, write_xlsx(path, parts)


@pytest.mark.parametrize(
    "text",
    [
        "9999",  # past the end
        "-1",  # would index from the end of the list if the lower bound were dropped
        "٣",  # an Arabic-Indic digit: str.isdigit() is True, int() accepts it, not ASCII
        "1" * 5000,  # past the int digit limit: must be a typed error, not a raw ValueError
        "1" * 10,
        "",
    ],
)
def test_a_bad_shared_string_index_is_the_typed_error_with_no_cause(tmp_path, text):
    path, digest = _with_shared_index(tmp_path, text)
    with pytest.raises(NanfImportError, match="bad shared-string") as err:
        _read(path, digest)
    assert err.value.code == "FORMAT_UNKNOWN"
    assert err.value.__cause__ is None


@pytest.mark.parametrize(
    "exc", [zlib.error, zipfile.BadZipFile, EOFError, OSError, NotImplementedError, RuntimeError]
)
def test_every_archive_read_failure_is_the_typed_error(tmp_path, monkeypatch, exc):
    path = tmp_path / "ok.xlsx"
    digest = make_workbook(path)

    def boom(self, name, pwd=None):
        raise exc("member text that must not be echoed 424242")

    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    with pytest.raises(NanfImportError, match="cannot be read") as err:
        _read(path, digest)
    assert err.value.code == "FORMAT_UNKNOWN"
    assert err.value.__cause__ is None and "424242" not in str(err.value)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
def test_the_length_of_the_distributed_loss_bound_is_validated(bad):
    class Never:  # the check must come before any workbook access
        def __getitem__(self, key):
            raise AssertionError("workbook touched before the length check")

    with pytest.raises(ValueError, match="length_km"):
        nb.distributed_loss_bound_db_per_km(Never(), 1550.0, length_km=bad)
    with pytest.raises(ValueError, match="length_km"):
        nb.link_loss_summary(Never(), length_km=bad)


def test_the_distributed_loss_bound_divides_by_the_length_given(tmp_path):
    from test_nanf_benchmark import fig5_cells  # noqa: PLC0415

    loss = [8.33 if i == 0 else 6.45 + 0.1 * abs(i - 15) for i in range(19)]
    path = tmp_path / "f5.xlsx"
    digest = make_workbook(path, fig5_cells(loss=loss))
    wb = _read(path, digest)
    assert nb.distributed_loss_bound_db_per_km(wb, 1610.0) == pytest.approx(6.45 / 4.76)
    assert nb.distributed_loss_bound_db_per_km(wb, 1610.0, length_km=2.0) == pytest.approx(3.225)
    assert nb.distributed_loss_bound_db_per_km(wb, 1610.0, length_km=10.0) == pytest.approx(0.645)
    assert nb.link_loss_summary(wb, length_km=2.0).distributed_upper_bound_db_per_km == (
        pytest.approx(3.225)
    )
