"""Read vector primitives from a PDF using PDFium."""

import ctypes
import math
import struct
import zlib
from dataclasses import replace
from pathlib import Path as FilePath

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from schem2net.primitives import BBox, Color, Document, Page, Path, Point, Text

MM_PER_PT = 25.4 / 72
BEZIER_STEPS = 8
WORD_GAP = 2.0  # font sizes between words of one text object that are separate texts

# Affine matrix (a, b, c, d, e, f) in PDF row-vector convention.
Matrix = tuple[float, float, float, float, float, float]


class InputError(Exception):
    """Input that cannot be read as asked: not a PDF, locked with a password, or a page
    the PDF does not have."""


def read(file: str | FilePath) -> Document:
    try:
        pdf = pdfium.PdfDocument(file)
    except pdfium.PdfiumError as e:
        raise InputError(f"{file}: not a PDF that can be read ({e})") from None
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
    _collect(objects, transform, textpage.raw, out, _chars(textpage.raw, transform))
    return out


def _chars(textpage, transform: Matrix) -> dict[int, list[tuple[str, BBox]]]:
    """Each text object's characters with their boxes, by the object's address."""
    found: dict[int, list[tuple[str, BBox]]] = {}
    sides = [ctypes.c_double() for _ in range(4)]
    for i in range(raw.FPDFText_CountChars(textpage)):
        obj = raw.FPDFText_GetTextObject(textpage, i)
        if not obj or not raw.FPDFText_GetCharBox(textpage, i, *map(ctypes.byref, sides)):
            continue
        left, right, bottom, top = (v.value for v in sides)
        corners = [_apply(transform, x, y) for x in (left, right) for y in (bottom, top)]
        xs, ys = zip(*corners, strict=True)
        char = chr(raw.FPDFText_GetUnicode(textpage, i))
        key = ctypes.cast(obj, ctypes.c_void_p).value
        found.setdefault(key, []).append((char, (min(xs), min(ys), max(xs), max(ys))))
    return found


def _collect(objects, parent: Matrix, textpage, out: Page, chars) -> None:
    for obj in objects:
        kind = raw.FPDFPageObj_GetType(obj)
        matrix = _multiply(_object_matrix(obj), parent)
        if kind == raw.FPDF_PAGEOBJ_PATH:
            path = _read_path(obj, matrix, len(out.paths))
            if path and not _repeats_end(path, out.paths[-1] if out.paths else None):
                path.seq = len(out.paths) + len(out.texts)
                out.paths.append(path)
        elif kind == raw.FPDF_PAGEOBJ_TEXT:
            text = _read_text(obj, matrix, parent, textpage, len(out.texts))
            key = ctypes.cast(obj, ctypes.c_void_p).value
            for part in _apart(text, chars.get(key, [])) if text else []:
                part.id = len(out.texts)
                part.seq = len(out.paths) + len(out.texts)
                out.texts.append(part)
        elif kind == raw.FPDF_PAGEOBJ_IMAGE:
            out.images += 1
        elif kind == raw.FPDF_PAGEOBJ_FORM:
            count = raw.FPDFFormObj_CountObjects(obj)
            children = [raw.FPDFFormObj_GetObject(obj, i) for i in range(count)]
            _collect(children, matrix, textpage, out, chars)


def _repeats_end(path: Path, last: Path | None) -> bool:
    """A line of no length at the end of the line just drawn, in its ink, which some
    printers add after every line: it draws nothing new."""
    return (
        last is not None
        and path.fill is None
        and path.stroke == last.stroke
        and path.width == last.width
        and all(p == last.subpaths[-1][-1] for sub in path.subpaths for p in sub)
    )


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
            # Some printers repeat a line's end; a dot is a line to its own start.
            if len(current) < 2 or point != current[-1]:
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
    # PDFium reads a dash that ends a line as a hyphen breaking a word, and returns it as
    # the control character 2.
    content = content.replace("\x02", "-")
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
        visible=raw.FPDFTextObj_GetTextRenderMode(obj) != raw.FPDF_TEXTRENDERMODE_INVISIBLE,
    )


def _apart(text: Text, chars: list[tuple[str, BBox]]) -> list[Text]:
    """A text object whose words lie far apart is texts that a printer joined into one
    object, such as a part's designator and its value written on one line."""
    angle = math.radians(text.angle)
    along = (math.cos(angle), -math.sin(angle))  # reading direction, y down

    def span(box: BBox) -> tuple[float, float]:
        ends = [x * along[0] + y * along[1] for x in box[::2] for y in box[1::2]]
        return min(ends), max(ends)

    words: list[list[tuple[str, BBox | None]]] = [[]]
    end = None
    for char, box in chars:
        if char.isspace():
            words[-1].append((char, None))
            continue
        start, stop = span(box)
        if end is not None and start - end > WORD_GAP * text.size:
            words.append([])
        words[-1].append((char, box))
        end = stop
    if len(words) < 2:
        return [text]
    parts = []
    for word in words:
        boxes = [box for _, box in word if box]
        box = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        parts.append(replace(text, text="".join(c for c, _ in word).strip(), bbox=box))
    return parts


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


PICTURE_DENSITY = 9  # pixels per mm of a page drawn under what was read from it
PICTURE_PIXELS = (1800, 4000)  # the fewest and most pixels across


def page_png(file: str | FilePath, number: int) -> bytes:
    """Page `number` (from 1) as it is shown, rendered in grey as a PNG fine enough to
    read when zoomed in, to lay under what was read from it."""
    pdf = pdfium.PdfDocument(file)
    try:
        page = pdf[number - 1]
        across = max(page.get_size())  # points
        lo, hi = PICTURE_PIXELS
        width = min(hi, max(lo, across * MM_PER_PT * PICTURE_DENSITY))
        scale = width / across
        pixels = page.render(scale=scale, grayscale=True).to_numpy()
    finally:
        pdf.close()
    if pixels.ndim == 3:
        pixels = pixels[:, :, 0]
    return _png(pixels)


def _png(grey) -> bytes:
    """A greyscale PNG of an 8-bit image."""
    height, width = grey.shape
    rows = b"".join(b"\x00" + grey[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )
