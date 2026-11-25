"""Netlist construction timeouts refuse the whole input before writing output."""

import signal
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from schem2net import pdf, pipeline
from schem2net.scene import Scene

from .conftest import KICAD_INK, resistor_page

pytestmark = pytest.mark.skipif(
    not hasattr(signal, "setitimer"), reason="requires POSIX interval timers"
)


@pytest.fixture
def schematic(tmp_path):
    return resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator="Eeschema (KiCad 8.0)")


@pytest.mark.parametrize(
    "stage",
    [
        (pipeline, "_name_sheets"),
        (pipeline.fields, "whole_names"),
        (pipeline.library, "read"),
        (pipeline.library, "resolve"),
        (pipeline.fields, "names_apart"),
        (pipeline.Netlister, "add_page"),
        (pipeline.Netlister, "result"),
    ],
    ids=["sheet names", "field names", "library load", "library fit", "names", "graph", "nets"],
)
def test_netlist_timeout_covers_every_final_stage(schematic, monkeypatch, stage):
    # Isolate final assembly from the graph trials inside page interpretation.
    def page(result, *args):
        result.scene = Scene(page=result.page.number)

    monkeypatch.setattr(pipeline, "_read_page", page)
    monkeypatch.setattr(pipeline, "NETLIST_SECONDS", 0.02, raising=False)
    owner, name = stage
    original = getattr(owner, name)

    def slow(*args, **kwargs):
        time.sleep(0.2)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(owner, name, slow)
        with pytest.raises(pdf.InputError, match=r"r.pdf: netlist construction timed out"):
            pipeline.extract(schematic, embedded=False)
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert pipeline.extract(schematic, embedded=False).source.generator == "kicad"


def test_netlist_budget_is_shared_across_pages(schematic, monkeypatch):
    doc = pdf.read(schematic)
    doc.pages = [replace(doc.pages[0], number=i) for i in range(1, 4)]
    monkeypatch.setattr(pdf, "read", lambda *args, **kwargs: doc)
    monkeypatch.setattr(pipeline, "NETLIST_SECONDS", 0.075, raising=False)

    def page(result, *args):
        result.scene = Scene(page=result.page.number)

    original = pipeline.Netlister.add_page

    def slow(self, *args):
        time.sleep(0.04)  # each page fits; the combined construction does not
        return original(self, *args)

    monkeypatch.setattr(pipeline, "_read_page", page)
    monkeypatch.setattr(pipeline.Netlister, "add_page", slow)
    with pytest.raises(pdf.InputError, match="netlist construction timed out"):
        pipeline.extract(schematic, embedded=False)


def test_timeout_inside_library_read_keeps_the_extraction_budget(schematic, tmp_path, monkeypatch):
    folder = tmp_path / "parts"
    pipeline.library.save({}, pipeline.library.path(folder))
    original = pipeline.library._load

    def slow(*args):
        time.sleep(0.2)
        return original(*args)

    monkeypatch.setattr(pipeline.library, "_load", slow)
    monkeypatch.setattr(pipeline, "NETLIST_SECONDS", 0.02)
    with pytest.raises(pdf.InputError, match="netlist construction timed out"):
        pipeline.extract(schematic, embedded=False, library_dir=folder)


SLOW_GRAPH = """
import time
from schem2net import pipeline
pipeline.NETLIST_SECONDS = 0.02
original = pipeline.Netlister.result
def slow(self):
    time.sleep(0.2)
    return original(self)
pipeline.Netlister.result = slow
"""


@pytest.mark.parametrize("command", ["extract", "export", "report"])
@pytest.mark.parametrize("strict", [False, True])
def test_cli_timeout_preserves_existing_output(tmp_path, schematic, command, strict):
    output = tmp_path / "existing.output"
    output.write_text("previous output")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            SLOW_GRAPH + "from schem2net.cli import main; main()",
            command,
            str(schematic),
            "-o",
            str(output),
            *(["--strict"] if strict else []),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1, result.stderr
    assert "netlist construction timed out" in result.stderr and "Traceback" not in result.stderr
    assert output.read_text() == "previous output"


def test_gui_worker_timeout_writes_no_partial_result(tmp_path, schematic):
    folder = tmp_path / "worker"
    folder.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            SLOW_GRAPH + "from schem2net.gui.worker import main; main()",
            str(schematic),
            str(folder),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "netlist construction timed out" in result.stderr and "Traceback" not in result.stderr
    assert not list(folder.iterdir())
