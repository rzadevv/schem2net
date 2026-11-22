"""Bus cardinality limits at the parser and public extraction boundaries."""

import subprocess
import sys

import pytest

from schem2net import buses, pdf, pipeline
from schem2net.primitives import Document
from schem2net.scene import Label, Scene, Sheet, SheetPin

from .conftest import KICAD_INK, resistor_page


@pytest.mark.parametrize("name", ["D[0..10000]", "D[10000..0]"])
def test_vector_ranges_are_refused_before_expansion(name):
    with pytest.raises(ValueError, match="10000 members"):
        buses.parse(name)


@pytest.mark.parametrize("name", ["D[0..9999]", "D[9999..0]"])
def test_the_limit_is_inclusive_and_preserves_member_order(name):
    bus = buses.parse(name)
    assert len(bus.members) == 10000
    assert bus.members[0] == "0" and bus.members[-1] == "9999"


def test_large_endpoint_values_do_not_limit_a_small_range():
    bus = buses.parse("D[1000000000000..1000000000001]")
    assert bus.members == ("1000000000000", "1000000000001")


def test_unconvertible_endpoints_are_a_bus_limit_error():
    with pytest.raises(ValueError, match="vector bus endpoints"):
        buses.parse(f"D[0..{'9' * 5000}]")


@pytest.fixture
def oversized_pdf(tmp_path):
    builder = resistor_page(KICAD_INK)
    builder.line((245, 150), (245, 240), width=1, color=(0, 0, 132))
    builder.text("D[0..10000]", 250, 220, size=5, color=(0, 0, 132))
    return builder.save(tmp_path / "bus.pdf", creator="Eeschema (KiCad 8.0)")


@pytest.mark.parametrize("where", ["label", "sheet pin"])
@pytest.mark.parametrize("trial", [False, True])
def test_bus_limits_are_input_errors_in_page_trials_and_final_graphs(
    tmp_path, monkeypatch, where, trial
):
    builder = resistor_page(dict.fromkeys(KICAD_INK, (0, 0, 0)) if trial else KICAD_INK)
    file = builder.save(tmp_path / "page.pdf", creator="Eeschema (KiCad 8.0)")

    def drawing(result, *args):
        result.scene = Scene(page=1, path="/")
        if where == "label":
            result.scene.labels = [Label("D[0..10000]", "global", (1, 1, 10, 3), 0)]
        else:
            result.scene.sheets = [
                Sheet("child", (1, 1, 10, 10), [SheetPin("D[0..10000]", (1, 3))])
            ]

    monkeypatch.setattr(pipeline, "_read_drawing", drawing)
    with pytest.raises(pdf.InputError, match="page 1.*10000 members"):
        pipeline.extract(file, embedded=False)


def test_unknown_profile_trials_do_not_hide_bus_limit_errors(oversized_pdf, monkeypatch):
    monkeypatch.setattr(pipeline.ingest, "detect_generator", lambda doc: "unknown")
    monkeypatch.setattr(pipeline.ingest, "guess_by_colour", lambda *args: None)

    def drawing(result, *args):
        result.scene = Scene(page=1)
        result.scene.labels = [Label("D[0..10000]", "bus", (1, 1, 10, 3), 0)]

    monkeypatch.setattr(pipeline, "_read_drawing", drawing)
    with pytest.raises(pdf.InputError, match="page 1.*10000 members"):
        pipeline.extract(oversized_pdf, embedded=False)


def test_an_oversized_bus_on_a_later_page_does_not_return_a_partial_design(
    tmp_path, oversized_pdf, monkeypatch
):
    normal = resistor_page(KICAD_INK).save(tmp_path / "normal.pdf", creator="Eeschema (KiCad 8.0)")
    good, bad = pdf.read(normal), pdf.read(oversized_pdf)
    bad.pages[0].number = 2
    document = Document(pages=good.pages + bad.pages, metadata=good.metadata)
    monkeypatch.setattr(pdf, "read", lambda *args, **kwargs: document)
    with pytest.raises(pdf.InputError, match="page 2.*10000 members"):
        pipeline.extract(oversized_pdf, embedded=False)
    monkeypatch.setattr(pdf, "read", lambda *args, **kwargs: good)
    assert len(pipeline.extract(normal, embedded=False).components) == 3


@pytest.mark.parametrize(
    "command,suffix", [("extract", "json"), ("export", "net"), ("report", "html")]
)
@pytest.mark.parametrize("strict", [False, True])
def test_cli_refuses_an_oversized_bus_without_replacing_output(
    tmp_path, oversized_pdf, command, suffix, strict
):
    output = tmp_path / f"existing.{suffix}"
    output.write_text("previous output")
    args = [command, str(oversized_pdf), "-o", str(output)] + (["--strict"] if strict else [])
    result = subprocess.run(
        [sys.executable, "-c", "from schem2net.cli import main; main()", *args],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "10000 members" in result.stderr and "Traceback" not in result.stderr
    assert output.read_text() == "previous output"


def test_gui_worker_refuses_the_same_oversized_bus(tmp_path, oversized_pdf):
    output = tmp_path / "worker"
    output.mkdir()
    result = subprocess.run(
        [sys.executable, "-P", "-m", "schem2net.gui.worker", str(oversized_pdf), str(output)],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "10000 members" in result.stderr and "Traceback" not in result.stderr
    assert not list(output.iterdir())
