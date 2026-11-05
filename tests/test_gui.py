import json
import os
import re
import subprocess
import sys
import time

import pytest

from schem2net import export, pipeline, report
from schem2net.ir import Design

from .conftest import KICAD_INK, PdfBuilder, resistor_page

KICAD = "Eeschema (KiCad 8.0)"


def _worker(file, folder):
    return subprocess.run(
        [sys.executable, "-P", "-m", "schem2net.gui.worker", str(file), str(folder)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_worker_writes_what_the_command_line_does(tmp_path):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    done = _worker(file, tmp_path)
    assert done.returncode == 0, done.stderr
    extraction = pipeline.run(file)
    assert Design.load(tmp_path / "design.ir.json") == extraction.design
    expected = report.render(extraction, report.pictures(file, extraction))
    assert (tmp_path / "report.html").read_text() == expected
    review = json.loads((tmp_path / "review.json").read_text())
    assert review == json.loads(json.dumps(report.review(extraction.design, extraction)))
    assert (tmp_path / "kicad" / "r.kicad_pro").exists()


def test_the_worker_says_why_it_cannot_read_a_file(tmp_path):
    (tmp_path / "x.pdf").write_text("not a pdf")
    done = _worker(tmp_path / "x.pdf", tmp_path)
    assert done.returncode == 1 and "not a PDF that can be read" in done.stderr
    assert not (tmp_path / "design.ir.json").exists()


def test_the_report_has_the_markup_the_desktop_view_relies_on(tmp_path):
    """view.js finds nets, review entries and pages by these; see its header."""
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    extraction = pipeline.run(file)
    html = report.render(extraction)
    for net in extraction.design.nets:
        assert (
            f'<li data-net="{net.id}">' in html or f'<li class="low" data-net="{net.id}">' in html
        )
    for entry in report.review(extraction.design, extraction):
        if entry["spots"]:
            assert f'data-mark="{entry["id"]}"' in html and f'id="{entry["id"]}"' in html
    assert re.search(
        r'<section><h2>Page 1[^<]*</h2>\s*<svg viewBox="[^"]+" [^>]*aria-label="Page 1"', html
    )


# The window itself, where Qt and its web view are installed.


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Headless, Chromium has no GL to draw with, and crashes repainting the report.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    from PySide6.QtWidgets import QApplication

    from schem2net.gui.app import application

    return QApplication.instance() or application([])


@pytest.fixture
def window(app, monkeypatch):
    from PySide6.QtCore import QEvent

    from schem2net.gui.app import Window

    errors = []
    monkeypatch.setattr(Window, "_error", lambda self, title, text: errors.append(text))
    window = Window()
    window.errors = errors
    window.resize(1280, 800)
    window.show()
    yield window
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait(app, done, seconds=60):
    end = time.time() + seconds
    while not done() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert done()


def _js(app, window, code):
    from schem2net.gui.app import WORLD

    result = []
    window.web.page().runJavaScript(f"JSON.stringify({code})", WORLD, result.append)
    _wait(app, lambda: result)
    return json.loads(result[0])


def _click(tree, item):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    center = tree.visualItemRect(item).center()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)


def _extracted(app, window, file):
    assert window.open(file)
    window.extract()
    _wait(app, lambda: window.process is None and window.report_pages)


def test_a_file_that_is_no_pdf_leaves_the_window_as_it_was(window, tmp_path):
    (tmp_path / "x.pdf").write_text("not a pdf")
    assert not window.open(tmp_path / "x.pdf")
    assert not window.open(tmp_path / "missing.pdf")
    assert window.file is None and len(window.errors) == 2
    assert not window.extract_action.isEnabled()


def test_extraction_fills_the_lists_and_drives_the_report(app, window, tmp_path):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    _extracted(app, window, file)
    design = pipeline.extract(file)
    assert window.nets.topLevelItemCount() == len(design.nets)
    assert window.parts.topLevelItemCount() == len(design.components)
    assert window.tabs.currentWidget() is window.web
    assert window.report_pages == [1]

    vin = next(n for n in design.nets if n.name == "VIN")
    item = next(
        window.nets.topLevelItem(k)
        for k in range(window.nets.topLevelItemCount())
        if window.nets.topLevelItem(k).text(0) == "VIN"
    )
    _click(window.nets, item)
    lit = f"document.querySelectorAll('svg [data-net=\"{vin.id}\"].on').length"
    _wait(app, lambda: _js(app, window, lit) > 0)
    assert _js(app, window, "document.body.classList.contains('focus')")
    _click(window.nets, item)  # the same net again clears it
    _wait(app, lambda: not _js(app, window, "document.body.classList.contains('focus')"))

    # R3.2 is left open: the review queue's one entry, marked on the drawing
    assert [e["what"] for e in window.review] == ["R3.2"]
    window.issues.setCurrentItem(window.issues.topLevelItem(0).child(0))
    _wait(app, lambda: _js(app, window, "document.querySelectorAll('.mark.on').length") == 1)
    assert window.properties.topLevelItem(0).text(1) == "pin on no net, without a no-connect flag"
    window.clear()
    _wait(app, lambda: _js(app, window, "document.querySelectorAll('.on').length") == 0)


def test_exports_write_what_the_exporters_give(app, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    _extracted(app, window, file)
    names = iter(["r.net", "r.ir.json", "r.bom.csv", "r.cir", "r.html"])
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / next(names)), "")
    )
    for action in window.exports:
        action.trigger()
    design = pipeline.extract(file)
    assert (tmp_path / "r.net").read_text() == export.kicad_netlist(design)
    assert Design.load(tmp_path / "r.ir.json") == design
    assert (tmp_path / "r.bom.csv").read_text() == export.bom_csv(design)
    assert (tmp_path / "r.cir").read_text() == export.spice_netlist(design)
    assert (tmp_path / "r.html").read_text() == window._output("report.html").read_text()

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(project))
    window.schematic_action.trigger()
    assert (project / "r.kicad_pro").exists()
    (project / "r.kicad_sch").write_text("mine")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window.schematic_action.trigger()
    assert (project / "r.kicad_sch").read_text() == "mine"


def test_stopping_keeps_nothing(app, window, tmp_path):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    assert window.open(file)
    window.extract()
    folder = window.out.path()
    window.stop()
    assert window.process is None and window.out is None and window.design is None
    assert not os.path.exists(folder)
    assert window.extract_action.isEnabled() and not window.exports[0].isEnabled()


def test_a_drawing_with_no_part_has_nothing_to_export(app, window, tmp_path):
    file = PdfBuilder().save(tmp_path / "blank.pdf", creator=KICAD)
    assert window.open(file)
    window.extract()
    _wait(app, lambda: window.process is None)
    assert window.design is not None and not window.design.components
    assert window.errors and "No component" in window.errors[-1]
    assert not any(action.isEnabled() for action in window.exports)
