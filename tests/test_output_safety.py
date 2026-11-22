"""Output paths and temporary files must not destroy source inputs."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from schem2net import cli

from .conftest import KICAD_INK, resistor_page
from .test_outputs import DESIGN


def alias_of(source, kind):
    if kind == "same":
        return source
    if kind == "relative":
        folder = source.parent / "sub"
        folder.mkdir()
        return folder / ".." / source.name
    alias = source.with_name("alias.output")
    if kind == "symlink":
        alias.symlink_to(source)
    else:
        os.link(source, alias)
    return alias


def invoke(*args):
    return subprocess.run(
        [sys.executable, "-c", "from schem2net.cli import main; main()", *map(str, args)],
        text=True,
        capture_output=True,
        timeout=30,
    )


@pytest.mark.parametrize("command", ["extract", "export", "report", "draw"])
@pytest.mark.parametrize("kind", ["same", "relative", "symlink", "hardlink"])
def test_output_cannot_alias_the_source_pdf(tmp_path, command, kind):
    source = resistor_page(KICAD_INK).save(tmp_path / "board.pdf", creator="Eeschema (KiCad 8.0)")
    output = alias_of(source, kind)
    before = source.read_bytes()
    result = invoke(command, source, "-o", output)
    assert result.returncode == 1, result.stderr
    assert "overwrite input" in result.stderr and "Traceback" not in result.stderr
    assert source.read_bytes() == output.read_bytes() == before
    if kind == "symlink":
        assert output.is_symlink()


@pytest.mark.parametrize("kind", ["same", "relative", "symlink", "hardlink"])
def test_netlist_export_cannot_destroy_its_json_input(tmp_path, kind):
    source = tmp_path / "design.ir.json"
    DESIGN.save(source)
    output = alias_of(source, kind)
    before = source.read_bytes()
    result = invoke("export", source, "-o", output)
    assert result.returncode == 1, result.stderr
    assert "overwrite input" in result.stderr and "Traceback" not in result.stderr
    assert source.read_bytes() == output.read_bytes() == before


@pytest.mark.parametrize("command", ["extract", "export", "report", "draw"])
def test_distinct_existing_output_can_still_be_replaced(tmp_path, command):
    source = resistor_page(KICAD_INK).save(tmp_path / "board.pdf", creator="Eeschema (KiCad 8.0)")
    before = source.read_bytes()
    output = tmp_path / "existing.output"
    output.write_bytes(before)  # identical bytes do not make this the same file
    result = invoke(command, source, "-o", output)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    assert output.read_bytes() != before


def test_a_source_named_like_the_old_temporary_file_is_preserved(tmp_path):
    source = resistor_page(KICAD_INK).save(
        tmp_path / ".board.html.part", creator="Eeschema (KiCad 8.0)"
    )
    before = source.read_bytes()
    output = tmp_path / "board.html"
    result = invoke("report", source, "-o", output)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    assert "<html" in output.read_text()


def test_an_existing_temporary_symlink_cannot_redirect_a_write(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"original input")
    output = tmp_path / "board.net"
    old_part = tmp_path / ".board.net.part"
    old_part.symlink_to(source)
    cli._write(output, "netlist")
    assert source.read_bytes() == b"original input"
    assert old_part.is_symlink()
    assert output.read_text() == "netlist" and not output.is_symlink()


def test_concurrent_text_outputs_each_finish_with_a_complete_file(tmp_path, monkeypatch):
    output = tmp_path / "board.net"
    ready, replace = Barrier(2), os.replace

    def overlap(source, target):
        ready.wait(timeout=10)
        replace(source, target)

    monkeypatch.setattr(os, "replace", overlap)
    choices = ["first\n" * 100, "second\n" * 100]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda text: cli._write(output, text), choices))
    assert output.read_text() in choices
    assert set(tmp_path.iterdir()) == {output}


def test_failed_text_replacement_cleans_up_without_losing_the_old_output(tmp_path, monkeypatch):
    output = tmp_path / "board.html"
    output.write_text("earlier report")

    def fail(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        cli._write(output, "new report")
    assert output.read_text() == "earlier report"
    assert set(tmp_path.iterdir()) == {output}
