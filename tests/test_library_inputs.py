"""Malformed library indexes must be refused before any export is replaced."""

import gzip
import json
import subprocess
import sys

import pytest

from schem2net import library

from .conftest import KICAD_INK, resistor_page


def compressed(value):
    return gzip.compress(json.dumps(value).encode("utf-8"), mtime=0)


INVALID = [
    b"not gzip",
    gzip.compress(b"{}", mtime=0)[:-4],
    gzip.compress(b"{", mtime=0),
    gzip.compress(b"\xff", mtime=0),
    compressed([]),
    compressed({"r": [["Device:R", [["1"]]]]}),
    compressed({"r": [["Device:R", [["1", "A", -1, 0, 0, False]]]]}),
    compressed({"r": [["Device:R", [["1", "A", 0, float("nan"), 0, False]]]]}),
    compressed({"r": [["Device:R", [["1", "A", 0, 0, 0, "false"]]]]}),
]
IDS = [
    "not gzip",
    "truncated gzip",
    "JSON",
    "UTF-8",
    "root",
    "pin row",
    "unit",
    "position",
    "hidden",
]


@pytest.fixture(params=INVALID, ids=IDS)
def invalid_index(tmp_path, request):
    folder = tmp_path / "parts"
    folder.mkdir()
    index = library.path(folder)
    index.write_bytes(request.param)
    return folder, index


def test_library_loader_refuses_malformed_indexes(invalid_index):
    folder, index = invalid_index
    with pytest.raises(ValueError, match="library index") as error:
        library.load(folder)
    assert str(index) in str(error.value)


def test_a_repaired_library_can_be_read_after_rejection(tmp_path):
    index = library.path(tmp_path)
    index.write_bytes(b"broken index")
    with pytest.raises(ValueError, match="library index"):
        library.load(tmp_path)
    expected = {"r": [("Device:R", [library.LibPin("1", "A", 0, (0.0, 0.0), False)])]}
    library.save(expected, index)
    assert library.load(tmp_path) == expected


@pytest.mark.parametrize("command", ["extract", "export", "report"])
def test_cli_bad_library_preserves_existing_output(tmp_path, invalid_index, command):
    folder, index = invalid_index
    pdf = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator="Eeschema (KiCad 8.0)")
    output = tmp_path / "existing.output"
    output.write_text("previous output")
    result = subprocess.run(
        [sys.executable, "-c", "from schem2net.cli import main; main()", command,
         str(pdf), "--library", str(folder), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert result.returncode == 1, result.stderr
    assert str(index) in result.stderr and "library index" in result.stderr
    assert "Traceback" not in result.stderr
    assert output.read_text() == "previous output"


def test_worker_bad_library_writes_no_partial_result(tmp_path, invalid_index):
    folder, index = invalid_index
    pdf = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator="Eeschema (KiCad 8.0)")
    output = tmp_path / "worker"
    output.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "schem2net.gui.worker", str(pdf), str(output), str(folder)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert str(index) in result.stderr and "library index" in result.stderr
    assert "Traceback" not in result.stderr
    assert list(output.iterdir()) == []
