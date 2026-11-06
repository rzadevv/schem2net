import ctypes
import os
import re

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest
from hypothesis import settings

# The usual number of examples in a test run; many more in the nightly one.
settings.register_profile("quick", max_examples=100)
settings.register_profile("nightly", max_examples=2000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "quick"))


class PdfBuilder:
    """Write small PDFs with known geometry. Units are PDF points."""

    def __init__(self, width: float = 612, height: float = 792):
        self.pdf = pdfium.PdfDocument.new()
        self.page = self.pdf.new_page(width, height)

    def line(self, *points, width=1.0, color=(0, 0, 0), dash=None):
        path = raw.FPDFPageObj_CreateNewPath(*points[0])
        for x, y in points[1:]:
            raw.FPDFPath_LineTo(path, x, y)
        if dash:
            raw.FPDFPageObj_SetDashArray(path, (ctypes.c_float * len(dash))(*dash), len(dash), 0)
        self._stroke(path, width, color)

    def curve(self, start, c1, c2, end, width=1.0):
        path = raw.FPDFPageObj_CreateNewPath(*start)
        raw.FPDFPath_BezierTo(path, *c1, *c2, *end)
        self._stroke(path, width, (0, 0, 0))

    def text(self, content, x, y, size=10.0, color=(0, 0, 0)):
        font = raw.FPDFText_LoadStandardFont(self.pdf.raw, b"Helvetica")
        obj = raw.FPDFPageObj_CreateTextObj(self.pdf.raw, font, size)
        raw.FPDFPageObj_SetFillColor(obj, *color, 255)
        encoded = (content + "\x00").encode("utf-16-le")
        buffer = ctypes.create_string_buffer(encoded, len(encoded))
        raw.FPDFText_SetText(obj, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        raw.FPDFPage_InsertObject(self.page.raw, obj)

    def save(self, path, rotation=0, creator=None):
        raw.FPDFPage_GenerateContent(self.page.raw)
        self.page.set_rotation(rotation)
        self.pdf.save(path)
        if creator:
            _set_creator(path, creator)
        return path

    def _stroke(self, path, width, color):
        raw.FPDFPath_SetDrawMode(path, 0, True)
        raw.FPDFPageObj_SetStrokeWidth(path, width)
        raw.FPDFPageObj_SetStrokeColor(path, *color, 255)
        raw.FPDFPage_InsertObject(self.page.raw, path)


def _set_creator(path, creator):
    """Name the program that made the PDF, in an update appended to the file: PDFium
    writes no document information of its own."""
    data = path.read_bytes().rstrip(b"\n") + b"\n"
    root = re.findall(rb"/Root (\d+ \d+ R)", data)[-1]
    size = int(re.findall(rb"/Size (\d+)", data)[-1])
    prev = int(re.findall(rb"startxref\s+(\d+)", data)[-1])
    info = b"%d 0 obj\n<< /Creator (%s) >>\nendobj\n" % (size, creator.encode())
    xref = len(data) + len(info)
    tail = (
        b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d 00000 n \n" % (size, len(data))
        + b"trailer\n<< /Root %s /Info %d 0 R /Size %d /Prev %d >>\n" % (root, size, size + 1, prev)
        + b"startxref\n%d\n%%%%EOF\n" % xref
    )
    path.write_bytes(data + info + tail)


MM = 72 / 25.4
KICAD_INK = {
    "symbol": (132, 0, 0),
    "wire": (0, 150, 0),
    "field": (0, 100, 100),
    "pin_number": (169, 0, 0),
    "local_label": (15, 15, 15),
}


def resistor_page(ink, label="VIN"):
    """Three resistors in a row at KiCad's sizes, each role in its ink: the top ends wired
    together under the label VIN, the first two bottom ends too, the third left open."""
    b = PdfBuilder(400, 300)

    def line(*points, role, width=0.152):
        b.line(*[(x * MM, 300 - y * MM) for x, y in points], width=width * MM, color=ink[role])

    def text(content, x, y, role):
        # Helvetica at 1.778 mm draws R1 1.27 mm high, KiCad's usual text.
        b.text(content, x * MM, 300 - y * MM, size=1.778 * MM, color=ink[role])

    for i, x in enumerate((30.48, 50.8, 71.12)):
        body = [(x - 1, 30.48), (x + 1, 30.48), (x + 1, 35.48), (x - 1, 35.48), (x - 1, 30.48)]
        line(*body, role="symbol", width=0.254)
        line((x, 30.48), (x, 27.94), role="symbol")
        line((x, 35.48), (x, 38.02), role="symbol")
        text("1", x - 1.2, 29.6, "pin_number")
        text("2", x - 1.2, 37.3, "pin_number")
        text(f"R{i + 1}", x + 2, 32.48, "field")
        text(("1k", "2k2", "4k7")[i], x + 2, 34.48, "field")
    line((30.48, 27.94), (71.12, 27.94), role="wire")
    line((30.48, 38.02), (50.8, 38.02), role="wire")
    text(label, 35, 27.6, "local_label")
    return b


@pytest.fixture
def pdf_builder():
    return PdfBuilder
