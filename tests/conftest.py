import ctypes

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest


class PdfBuilder:
    """Write small PDFs with known geometry. Units are PDF points."""

    def __init__(self, width: float = 612, height: float = 792):
        self.pdf = pdfium.PdfDocument.new()
        self.page = self.pdf.new_page(width, height)

    def line(self, *points, width=1.0, color=(0, 0, 0)):
        path = raw.FPDFPageObj_CreateNewPath(*points[0])
        for x, y in points[1:]:
            raw.FPDFPath_LineTo(path, x, y)
        self._stroke(path, width, color)

    def curve(self, start, c1, c2, end, width=1.0):
        path = raw.FPDFPageObj_CreateNewPath(*start)
        raw.FPDFPath_BezierTo(path, *c1, *c2, *end)
        self._stroke(path, width, (0, 0, 0))

    def text(self, content, x, y, size=10.0):
        font = raw.FPDFText_LoadStandardFont(self.pdf.raw, b"Helvetica")
        obj = raw.FPDFPageObj_CreateTextObj(self.pdf.raw, font, size)
        encoded = (content + "\x00").encode("utf-16-le")
        buffer = ctypes.create_string_buffer(encoded, len(encoded))
        raw.FPDFText_SetText(obj, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        raw.FPDFPage_InsertObject(self.page.raw, obj)

    def save(self, path, rotation=0):
        raw.FPDFPage_GenerateContent(self.page.raw)
        self.page.set_rotation(rotation)
        self.pdf.save(path)
        return path

    def _stroke(self, path, width, color):
        raw.FPDFPath_SetDrawMode(path, 0, True)
        raw.FPDFPageObj_SetStrokeWidth(path, width)
        raw.FPDFPageObj_SetStrokeColor(path, *color, 255)
        raw.FPDFPage_InsertObject(self.page.raw, path)


@pytest.fixture
def pdf_builder():
    return PdfBuilder
