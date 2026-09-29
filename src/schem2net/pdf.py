"""Read vector primitives from a PDF using PDFium."""

import ctypes
import math
from pathlib import Path as FilePath

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from schem2net.primitives import Color, Document, Page, Path, Point, Text

MM_PER_PT = 25.4 / 72
BEZIER_STEPS = 8

# Affine matrix (a, b, c, d, e, f) in PDF row-vector convention.
Matrix = tuple[float, float, float, float, float, float]


def read(file: str | FilePath) -> Document:
    pdf = pdfium.PdfDocument(file)
    try:
        pages = [_read_page(pdf[i], i + 1) for i in range(len(pdf))]
        return Document(pages=pages, metadata=pdf.get_metadata_dict(skip_empty=True))
    finally:
        pdf.close()


def _read_page(page: pdfium.PdfPage, number: int) -> Page:
    transform, width, height = _page_transform(page)
    out = Page(number=number, width=width, height=height)
    textpage = page.get_textpage()
    count = raw.FPDFPage_CountObjects(page.raw)
    objects = [raw.FPDFPage_GetObject(page.raw, i) for i in range(count)]
    _collect(objects, transform, textpage.raw, out)
    return out


def _collect(objects, parent: Matrix, textpage, out: Page) -> None:
    for obj in objects:
        kind = raw.FPDFPageObj_GetType(obj)
        matrix = _multiply(_object_matrix(obj), parent)
        if kind == raw.FPDF_PAGEOBJ_PATH:
            path = _read_path(obj, matrix, len(out.paths))
            if path:
                path.seq = len(out.paths) + len(out.texts)
                out.paths.append(path)
        elif kind == raw.FPDF_PAGEOBJ_TEXT:
            text = _read_text(obj, matrix, parent, textpage, len(out.texts))
            if text:
                text.seq = len(out.paths) + len(out.texts)
                out.texts.append(text)
        elif kind == raw.FPDF_PAGEOBJ_IMAGE:
            out.images += 1
        elif kind == raw.FPDF_PAGEOBJ_FORM:
            count = raw.FPDFFormObj_CountObjects(obj)
            children = [raw.FPDFFormObj_GetObject(obj, i) for i in range(count)]
            _collect(children, matrix, textpage, out)


def _read_path(obj, matrix: Matrix, id: int) -> Path | None:
    fill_mode, stroked = ctypes.c_int(), ctypes.c_int()
    raw.FPDFPath_GetDrawMode(obj, ctypes.byref(fill_mode), ctypes.byref(stroked))
    if not fill_mode.value and not stroked.value:
        return None

    subpaths: list[list[Point]] = []
    current: list[Point] = []
    controls: list[Point] = []
    curved = False
    x, y = ctypes.c_float(), ctypes.c_float()

    for i in range(raw.FPDFPath_CountSegments(obj)):
        segment = raw.FPDFPath_GetPathSegment(obj, i)
        raw.FPDFPathSegment_GetPoint(segment, ctypes.byref(x), ctypes.byref(y))
        point = _apply(matrix, x.value, y.value)
        kind = raw.FPDFPathSegment_GetType(segment)

        if kind == raw.FPDF_SEGMENT_MOVETO:
            if len(current) > 1:
                subpaths.append(current)
            current = [point]
        elif kind == raw.FPDF_SEGMENT_LINETO:
            current.append(point)
        elif kind == raw.FPDF_SEGMENT_BEZIERTO:
            controls.append(point)
            if len(controls) == 3:
                current.extend(_bezier(current[-1], *controls))
                controls.clear()
                curved = True

        if raw.FPDFPathSegment_GetClose(segment) and current:
            current.append(current[0])

    if len(current) > 1:
        subpaths.append(current)
    if not subpaths:
        return None

    width = ctypes.c_float()
    raw.FPDFPageObj_GetStrokeWidth(obj, ctypes.byref(width))
    return Path(
        id=id,
        subpaths=subpaths,
        width=width.value * _scale(matrix),
        stroke=_color(raw.FPDFPageObj_GetStrokeColor, obj) if stroked.value else None,
        fill=_color(raw.FPDFPageObj_GetFillColor, obj) if fill_mode.value else None,
        curved=curved,
    )


def _read_text(obj, matrix: Matrix, parent: Matrix, textpage, id: int) -> Text | None:
    length = raw.FPDFTextObj_GetText(obj, textpage, None, 0)
    buffer = ctypes.create_string_buffer(length)
    raw.FPDFTextObj_GetText(
        obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
    )
    content = buffer.raw.decode("utf-16-le").rstrip("\x00").strip()
    if not content:
        return None

    size = ctypes.c_float()
    raw.FPDFTextObj_GetFontSize(obj, ctypes.byref(size))
    a, b, *_ = matrix
    return Text(
        id=id,
        text=content,
        bbox=_bounds(obj, parent),
        size=size.value * _scale(matrix),
        angle=round(math.degrees(math.atan2(-b, a)), 1) % 360,
        color=_color(raw.FPDFPageObj_GetFillColor, obj),
    )


def _page_transform(page: pdfium.PdfPage) -> tuple[Matrix, float, float]:
    """Map PDF user space to displayed millimetres, top-left origin."""
    left, bottom, right, top = page.get_cropbox()
    w, h = right - left, top - bottom
    rotation = page.get_rotation()
    rotate: Matrix = {
        0: (1, 0, 0, 1, 0, 0),
        90: (0, -1, 1, 0, 0, w),
        180: (-1, 0, 0, -1, w, h),
        270: (0, 1, -1, 0, h, 0),
    }[rotation]
    shown_w, shown_h = (h, w) if rotation in (90, 270) else (w, h)
    k = MM_PER_PT
    matrix = _multiply(
        _multiply((1, 0, 0, 1, -left, -bottom), rotate), (k, 0, 0, -k, 0, k * shown_h)
    )
    return matrix, shown_w * k, shown_h * k


def _object_matrix(obj) -> Matrix:
    m = raw.FS_MATRIX()
    if not raw.FPDFPageObj_GetMatrix(obj, ctypes.byref(m)):
        return (1, 0, 0, 1, 0, 0)
    return (m.a, m.b, m.c, m.d, m.e, m.f)


def _bounds(obj, matrix: Matrix) -> tuple[float, float, float, float]:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    raw.FPDFPageObj_GetBounds(obj, *(ctypes.byref(v) for v in (left, bottom, right, top)))
    corners = [_apply(matrix, x.value, y.value) for x in (left, right) for y in (bottom, top)]
    xs, ys = zip(*corners, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _color(getter, obj) -> Color | None:
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if not getter(obj, *(ctypes.byref(v) for v in (r, g, b, a))):
        return None
    return r.value, g.value, b.value


def _multiply(m: Matrix, n: Matrix) -> Matrix:
    """Return the matrix that applies m, then n."""
    a, b, c, d, e, f = m
    p, q, r, s, t, u = n
    return (
        a * p + b * r,
        a * q + b * s,
        c * p + d * r,
        c * q + d * s,
        e * p + f * r + t,
        e * q + f * s + u,
    )


def _apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _scale(m: Matrix) -> float:
    a, b, c, d, _, _ = m
    return math.sqrt(abs(a * d - b * c))


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    points = []
    for i in range(1, BEZIER_STEPS + 1):
        t = i / BEZIER_STEPS
        s = 1 - t
        points.append(
            (
                s**3 * p0[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t**3 * p3[0],
                s**3 * p0[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return points
