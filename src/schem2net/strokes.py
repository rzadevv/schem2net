"""Read text drawn as strokes, such as Eagle's vector font.

Some generators draw text with a stroke font: every letter is a handful of
short lines, with no text object in the PDF. Strokes drawn one after another in
one style are grouped into lines of text and split into glyphs; each glyph is
compared with a table of known glyph shapes in a frame set by its line's
baseline and height.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from importlib import resources

import numpy as np

from schem2net import geometry
from schem2net.primitives import BBox, Path, Point, Text

MAX_STROKE = 3.0  # mm; longer lines are not parts of letters
MIN_WIDTH = 0.05  # mm; hairlines are fills and artwork
JUMP = 6  # a jump this many times the usual stroke length starts another text
MAX_MATCH = 0.12  # glyph distance, in text heights, still taken as a match
SPACE = 0.5  # a gap this many text heights wide between glyphs is a space
SCALES = (1.0, 1.15, 0.87, 1.3, 0.77)  # tried in this order
MAX_ASPECT_GAP = 0.35  # radians between a glyph's shape and a candidate's

Segment = tuple[Point, Point]
Shape = list[Segment]


@dataclass
class Glyph:
    strokes: list[Path]
    box: BBox


@dataclass
class Line:
    glyphs: list[Glyph]
    horizontal: bool
    base: float  # the baseline, across the reading direction
    height: float


def read(paths: list[Path], font: str) -> tuple[list[Text], set[int]]:
    """Texts found among the strokes, and the seq of every stroke they use."""
    shapes = _font(font)
    texts, used = [], set()
    for run in _runs(_strokes(paths)):
        for line in _lines(run):
            chars = [match(normalise(g, line), shapes) for g in line.glyphs]
            if not line.glyphs or sum(c is not None for c in chars) < 0.8 * len(chars):
                continue
            # Outlines and arrows read as strings of signs; text is mostly letters.
            if sum(bool(c and c.isalnum()) for c in chars) < 0.5 * len(chars):
                continue
            texts.append(_text(line, chars, run))
            used |= {s.seq for g in line.glyphs for s in g.strokes}
    return texts, used


def runs_and_lines(paths: list[Path]) -> list[Line]:
    """Every line of stroke glyphs, for building the font table."""
    return [line for run in _runs(_strokes(paths)) for line in _lines(run)]


def normalise(glyph: Glyph, line: Line) -> Shape:
    """A glyph's strokes, with the line's baseline at y=0 and its height as unit."""
    out = []
    for stroke in glyph.strokes:
        pts = []
        for x, y in stroke.subpaths[0]:
            if line.horizontal:
                pts.append(((x - glyph.box[0]) / line.height, (line.base - y) / line.height))
            else:  # turned a quarter: reading up the page
                pts.append(((glyph.box[3] - y) / line.height, (line.base - x) / line.height))
        out.append((pts[0], pts[1]))
    return out


def distance(a: Shape, b: Shape) -> float:
    """How far apart two glyph shapes are: each stroke against its nearest in the other.

    The typical gap counts, and so does the worst one, so that a stroke with no
    counterpart, the leg that makes P an R, is not averaged away.
    """
    if not a or not b:
        return float("inf")
    return _distance(np.asarray(a, dtype=float), np.asarray(b, dtype=float))


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    """distance() on arrays of segments, shaped (n, 2, 2)."""
    # Each segment pair compared end to end, and with one of them turned round.
    same = np.maximum(
        np.linalg.norm(a[:, None, 0] - b[None, :, 0], axis=2),
        np.linalg.norm(a[:, None, 1] - b[None, :, 1], axis=2),
    )
    flipped = np.maximum(
        np.linalg.norm(a[:, None, 0] - b[None, :, 1], axis=2),
        np.linalg.norm(a[:, None, 1] - b[None, :, 0], axis=2),
    )
    gaps = np.minimum(same, flipped)

    def one_way(rows: np.ndarray) -> float:
        return max(rows.mean(), rows.max() / 2)

    return float(max(one_way(gaps.min(axis=1)), one_way(gaps.min(axis=0))))


def _strokes(paths: list[Path]) -> list[Path]:
    """Every short line that could be part of a letter, one per segment. Some PDFs draw a
    letter's strokes one line at a time, others as polylines; a segment keeps the seq
    of the path it came from."""
    out = []
    for path in paths:
        if path.fill is not None or not path.stroke or path.width < MIN_WIDTH:
            continue
        if len(path.subpaths) != 1:
            continue
        points = path.subpaths[0]
        pairs = list(zip(points, points[1:], strict=False))
        if not pairs or not all(0 < geometry.distance(a, b) < MAX_STROKE for a, b in pairs):
            continue
        for a, b in pairs:
            out.append(Path(path.id, [[a, b]], path.width, path.stroke, None, seq=path.seq))
    return out


def _runs(strokes: list[Path]) -> list[list[Path]]:
    """Strokes drawn one after another in one style, cut where the pen jumps far."""
    runs: list[list[Path]] = []
    for s in sorted(strokes, key=lambda s: s.seq):
        last = runs[-1][-1] if runs else None
        same = last and s.seq in (last.seq, last.seq + 1) and s.stroke == last.stroke
        if not (same and abs(s.width - last.width) < 1e-3):
            runs.append([])
        runs[-1].append(s)
    out = []
    for run in runs:
        lengths = sorted(geometry.distance(*s.subpaths[0]) for s in run)
        step = JUMP * max(lengths[len(lengths) // 2], 0.2)
        piece = [run[0]]
        for prev, s in zip(run, run[1:], strict=False):
            gap = geometry.bbox_gap(
                geometry.bbox_of(prev.subpaths[0]), geometry.bbox_of(s.subpaths[0])
            )
            if gap > step:
                out.append(piece)
                piece = []
            piece.append(s)
        out.append(piece)
    return out


def _lines(run: list[Path]) -> list[Line]:
    x0, y0, x1, y1 = geometry.bbox_of([p for s in run for p in s.subpaths[0]])
    first, last = run[0].subpaths[0][0], run[-1].subpaths[0][0]
    horizontal = not (abs(last[1] - first[1]) > abs(last[0] - first[0]) and y1 - y0 > x1 - x0)
    k, sign = (0, 1) if horizontal else (1, -1)  # turned text reads up: y decreases

    glyphs: list[list[Path]] = []
    lo = hi = 0.0
    for s in run:
        a, b = s.subpaths[0]
        start, end = sorted((sign * a[k], sign * b[k]))
        if glyphs and lo - 0.02 <= end and start <= hi + 0.02:
            glyphs[-1].append(s)
            lo, hi = min(lo, start), max(hi, end)
        else:
            glyphs.append([s])
            lo, hi = start, end

    lines: list[list[Glyph]] = []
    prev = None
    for strokes in glyphs:
        box = geometry.bbox_of([p for s in strokes for p in s.subpaths[0]])
        start = box[0] if horizontal else -box[3]
        if prev is None or start < prev - 0.02:  # the pen went back: a new line
            lines.append([])
        lines[-1].append(Glyph(strokes, box))
        prev = start

    out = []
    for line in lines:
        bottoms = Counter(round(g.box[3] if horizontal else g.box[2], 2) for g in line)
        base = bottoms.most_common(1)[0][0]
        tops = [g.box[1] if horizontal else g.box[0] for g in line]
        out.append(Line(line, horizontal, base, max(base - t for t in tops)))
    return [line for line in out if line.height > 0]


def match(shape: Shape, shapes: list[tuple[str, Shape]]) -> str | None:
    """The character whose shape is nearest. The line's height is only an estimate (a
    bracket or a tall letter stretches it), so a few scales around it are tried."""
    key = tuple((round(a, 2), round(b, 2), round(c, 2), round(d, 2)) for (a, b), (c, d) in shape)
    table = _prepared(shapes)
    if key not in table.seen:
        table.seen[key] = _nearest(np.asarray(shape, dtype=float), table)
    return table.seen[key]


@dataclass
class _Table:
    chars: list[str]
    arrays: list[np.ndarray]
    aspects: list[float]
    seen: dict = field(default_factory=dict)  # shapes already read: letters repeat


_TABLES: dict[int, tuple[list, _Table]] = {}


def _prepared(shapes: list[tuple[str, Shape]]) -> _Table:
    """The table ready for matching, made once for each list of shapes."""
    entry = _TABLES.get(id(shapes))
    if entry is None or entry[0] is not shapes:  # kept alive here, so the id stays its own
        arrays = [np.asarray(known, dtype=float) for _, known in shapes]
        entry = (shapes, _Table([c for c, _ in shapes], arrays, [_aspect(a) for a in arrays]))
        _TABLES[id(shapes)] = entry
    return entry[1]


def _nearest(shape: np.ndarray, table: _Table) -> str | None:
    best, found = MAX_MATCH, None
    aspect = _aspect(shape)
    candidates = [
        k
        for k, known in enumerate(table.arrays)
        if abs(len(known) - len(shape)) <= 4  # large text is drawn with more pieces
        and abs(table.aspects[k] - aspect) <= MAX_ASPECT_GAP
    ]
    for scale in SCALES:
        scaled = shape * scale
        for k in candidates:
            d = _distance(scaled, table.arrays[k])
            if d < best:
                best, found = d, table.chars[k]
        if best < MAX_MATCH / 2:
            break
    return found


def _aspect(segments: np.ndarray) -> float:
    """Width over height of a glyph, which scaling does not change."""
    points = segments.reshape(-1, 2)
    width, height = np.ptp(points[:, 0]), np.ptp(points[:, 1])
    return float(np.arctan2(width, height))  # an angle: stays finite for flat glyphs


def _text(line: Line, chars: list[str | None], run: list[Path]) -> Text:
    out = ""
    for i, (glyph, char) in enumerate(zip(line.glyphs, chars, strict=True)):
        if i:
            prev = line.glyphs[i - 1].box
            gap = (glyph.box[0] - prev[2]) if line.horizontal else (prev[1] - glyph.box[3])
            if gap > SPACE * line.height:
                out += " "
        out += char or "?"
    box = geometry.bbox_of([p for g in line.glyphs for s in g.strokes for p in s.subpaths[0]])
    seq = min(s.seq for g in line.glyphs for s in g.strokes)
    angle = 0.0 if line.horizontal else 90.0
    return Text(-1, out, box, line.height, angle, run[0].stroke, seq)


@cache
def _font(name: str) -> list[tuple[str, Shape]]:
    text = resources.files("schem2net").joinpath("profiles", f"{name}_font.json").read_text()
    return [
        (entry["char"], [tuple(map(tuple, seg)) for seg in shape])
        for entry in json.loads(text)
        for shape in entry["shapes"]
    ]
