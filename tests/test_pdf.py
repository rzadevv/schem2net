import signal

import pytest

from schem2net import pdf

MM = 25.4 / 72


def test_line_in_millimetres_from_top_left(tmp_path, pdf_builder):
    b = pdf_builder()
    b.line((72, 72), (144, 72), width=2, color=(0, 150, 0))
    page = pdf.read(b.save(tmp_path / "a.pdf")).pages[0]

    assert page.width == pytest.approx(612 * MM)
    assert page.height == pytest.approx(792 * MM)
    (path,) = page.paths
    (x0, y0), (x1, y1) = path.subpaths[0]
    assert (x0, y0) == pytest.approx((25.4, 254.0))
    assert (x1, y1) == pytest.approx((50.8, 254.0))
    assert path.width == pytest.approx(2 * MM)
    assert path.stroke == (0, 150, 0)
    assert path.fill is None


def test_rotated_page(tmp_path, pdf_builder):
    b = pdf_builder()
    b.line((0, 0), (72, 0))
    page = pdf.read(b.save(tmp_path / "a.pdf", rotation=90)).pages[0]

    assert (page.width, page.height) == pytest.approx((792 * MM, 612 * MM))
    start, end = page.paths[0].subpaths[0]
    assert start == pytest.approx((0, 0), abs=1e-6)
    assert end == pytest.approx((0, 25.4), abs=1e-6)


def test_bezier_is_flattened(tmp_path, pdf_builder):
    b = pdf_builder()
    b.curve((0, 0), (0, 72), (72, 72), (72, 0))
    (path,) = pdf.read(b.save(tmp_path / "a.pdf")).pages[0].paths

    assert path.curved
    points = path.subpaths[0]
    assert len(points) == pdf.BEZIER_STEPS + 1
    assert points[-1] == pytest.approx((25.4, 792 * MM))


def test_text(tmp_path, pdf_builder):
    b = pdf_builder()
    b.text("R12", 72, 720, size=10)
    (text,) = pdf.read(b.save(tmp_path / "a.pdf")).pages[0].texts

    assert text.text == "R12"
    assert text.size == pytest.approx(10 * MM)
    assert text.angle == 0
    x0, y0, x1, y1 = text.bbox
    assert x0 == pytest.approx(25.4, abs=0.5)
    assert y1 == pytest.approx(72 * MM, abs=0.5)
    assert x1 > x0 and y1 > y0


def test_points_a_printer_repeats_are_dropped(tmp_path, pdf_builder):
    """Some printers end each line by repeating its last point, or with a line of no
    length at its end. A dot elsewhere stays."""
    b = pdf_builder()
    b.line((72, 72), (144, 72), (144, 72))
    b.line((144, 72), (144, 72))
    b.line((200, 72), (200, 72))
    paths = pdf.read(b.save(tmp_path / "a.pdf")).pages[0].paths
    assert [len(p.subpaths[0]) for p in paths] == [2, 2]
    assert paths[1].subpaths[0][0] == pytest.approx((200 * MM, 720 * MM))


def test_words_far_apart_in_one_text_object_are_separate_texts(tmp_path, pdf_builder):
    """A printer may write a designator and its value, placed on one line, as one text."""
    b = pdf_builder()
    b.text("R1" + " " * 12 + "20", 72, 720, size=10)
    b.text("Pin 1 is ground", 72, 600, size=10)
    texts = pdf.read(b.save(tmp_path / "a.pdf")).pages[0].texts
    assert [t.text for t in texts] == ["R1", "20", "Pin 1 is ground"]
    assert texts[0].bbox[2] < texts[1].bbox[0]


def test_page_picture_is_a_png_as_wide_as_the_page_reads(tmp_path, pdf_builder):
    """A rotated page is pictured as shown, landscape, about 9 pixels per mm."""
    import struct

    b = pdf_builder()
    b.line((72, 72), (144, 72), width=4)
    png = pdf.page_pngs(b.save(tmp_path / "a.pdf", rotation=90), [1])[1]
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert width > height
    assert width == pytest.approx(792 * MM * pdf.PICTURE_DENSITY, rel=0.01)


def test_a_page_pdfium_cannot_load_is_an_input_error(tmp_path, pdf_builder):
    b = pdf_builder()
    b.line((72, 72), (144, 72))
    file = b.save(tmp_path / "a.pdf")
    file.write_bytes(file.read_bytes().replace(b"/Type/Page>>", b"/Type/Pagx>>"))
    with pytest.raises(pdf.InputError):
        pdf.read(file)


def test_a_dashed_line_is_never_a_wire(tmp_path, pdf_builder):
    from schem2net import profile, scene

    b = pdf_builder()
    b.line((72, 72), (144, 72), width=0.5, color=(0, 150, 0), dash=[3, 2])
    b.line((72, 100), (144, 100), width=0.5, color=(0, 150, 0))
    page = pdf.read(b.save(tmp_path / "a.pdf")).pages[0]
    assert [p.dashed for p in page.paths] == [True, False]
    assert len(scene.build(page, profile.load("kicad")).wires) == 1


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires POSIX interval timers")
def test_a_page_timeout_leaves_the_following_page_readable(tmp_path, pdf_builder, monkeypatch):
    import time

    b = pdf_builder()
    b.line((72, 72), (144, 72))
    file = b.save(tmp_path / "two.pdf")
    b.page = b.pdf.new_page(612, 792)
    b.line((72, 72), (144, 72))
    b.save(file)
    chars = pdf._chars
    calls = 0

    def slow_first(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(1)
        return chars(*args)

    monkeypatch.setattr(pdf, "_chars", slow_first)
    first, second = pdf.read(file, page_seconds=0.05).pages
    assert "TimeoutError" in first.read_error and not first.paths
    assert second.read_error is None and len(second.paths) == 1


def test_nested_forms_must_not_silently_drop_drawing(monkeypatch):
    from schem2net.primitives import Page

    monkeypatch.setattr(pdf, "MAX_FORM_DEPTH", 2)
    monkeypatch.setattr(pdf.raw, "FPDFPageObj_GetType", lambda obj: pdf.raw.FPDF_PAGEOBJ_FORM)
    monkeypatch.setattr(pdf, "_object_matrix", lambda obj: (1, 0, 0, 1, 0, 0))
    monkeypatch.setattr(pdf.raw, "FPDFFormObj_CountObjects", lambda obj: 1)
    monkeypatch.setattr(pdf.raw, "FPDFFormObj_GetObject", lambda obj, i: obj)
    with pytest.raises(pdf._TooLarge):
        pdf._collect([object()], (1, 0, 0, 1, 0, 0), None, Page(1, 100, 100), {})


def test_object_budget_counts_deduplicated_paths(tmp_path, pdf_builder, monkeypatch):
    b = pdf_builder()
    b.line((72, 72), (144, 72))
    for _ in range(8):
        b.line((144, 72), (144, 72))
    file = b.save(tmp_path / "repeat.pdf")
    monkeypatch.setattr(pdf, "MAX_OBJECTS", 4)
    assert pdf.read(file).pages[0].too_large
