"""Read text drawn as strokes, such as Eagle's vector font.

Some generators draw text with a stroke font: every letter is a handful of
short lines, with no text object in the PDF. Strokes drawn one after another in
one style are grouped into lines of text and split into glyphs; each glyph is
compared with a table of known glyph shapes in a frame set by its line's
baseline and height.
"""

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import cache
from importlib import resources

import numpy as np

from schem2net import geometry
from schem2net.primitives import BBox, Page, Path, Point, Text

TRACE_SLACK = 0.4  # text heights a traced letter may reach past its copy's box
TRACE_RUN = 1.0  # the same, past either end of the line
LETTER = 1.2  # text heights; a longer stroke is not part of a letter
TRACE_SPREAD = 0.6  # share of a text's length its letters' ink spans
MAX_STROKE = 3.0  # mm; longer lines are not parts of letters
MIN_WIDTH = 0.05  # mm; hairlines are fills and artwork
JUMP = 6  # a jump this many times the usual stroke length starts another text
MAX_MATCH = 0.12  # glyph distance, in text heights, still taken as a match
SPACE = 0.5  # a gap this many text heights wide between glyphs is a space
SCALES = (1.0, 1.15, 0.87, 1.3, 0.77)  # tried in this order
BY_SIZE = {c: c.upper() for c in "cosvwxz"}  # small letters drawn as their capitals, smaller
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


def traced(page: Page) -> Page:
    """Text drawn as strokes, with an invisible copy laid over it for search, as KiCad 7
    and 8 write it: the copy is the text, and the strokes under it are its letters.

    An invisible text counts only if ink of its own colour lies within its box, so
    hidden markers laid over other drawing, such as a Smart PDF's, stay hidden.
    """
    hidden = [t for t in page.texts if not t.visible and t.text.strip()]
    if not hidden:
        return page
    index = geometry.GridIndex(cell=3.0)
    for k, p in enumerate(page.paths):
        index.add(k, p.bbox)
    letters: set[int] = set()
    shown = set()
    for t in hidden:
        # The copy's font is not the drawn one: its box can miss the letters' edges, and
        # over a long string their ends, as the two fonts' letters differ in width.
        size = max(t.size, 0.5)
        across, along = TRACE_SLACK * size, TRACE_RUN * size
        sx, sy = (along, across) if round(t.angle) % 180 == 0 else (across, along)
        x0, y0, x1, y1 = t.bbox
        box = (x0 - sx, y0 - sy, x1 + sx, y1 + sy)
        under = [
            k
            for k in index.within(box)
            if (page.paths[k].stroke or page.paths[k].fill) == t.color
            and _inside(page.paths[k].bbox, box)
            and _longest(page.paths[k].bbox) <= LETTER * max(t.size, 0.5)
        ]
        if _spells(t, [page.paths[k].bbox for k in under]):
            letters.update(under)
            shown.add(id(t))
    if not shown:
        return page
    return replace(
        page,
        paths=[p for k, p in enumerate(page.paths) if k not in letters],
        texts=[replace(t, visible=True) if id(t) in shown else t for t in page.texts],
    )


def _spells(text: Text, boxes: list[BBox]) -> bool:
    """Ink that could draw the text: a stroke or more for each letter, spread along it.
    A pin line under a hidden pin marker is not."""
    letters = sum(not c.isspace() for c in text.text)
    if not boxes or len(boxes) < letters:
        return False
    k = 0 if round(text.angle) % 180 == 0 else 1  # along the reading direction
    ink = max(b[k + 2] for b in boxes) - min(b[k] for b in boxes)
    return ink >= TRACE_SPREAD * (text.bbox[k + 2] - text.bbox[k])


def _longest(box: BBox) -> float:
    return max(box[2] - box[0], box[3] - box[1])


def _inside(inner: BBox, outer: BBox) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


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
    def apart(i: int, j: int) -> np.ndarray:
        return np.hypot(a[:, None, i, 0] - b[None, :, j, 0], a[:, None, i, 1] - b[None, :, j, 1])

    same = np.maximum(apart(0, 0), apart(1, 1))
    flipped = np.maximum(apart(0, 1), apart(1, 0))
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
        if not path.stroke or path.width < MIN_WIDTH or len(path.subpaths) != 1:
            continue
        points = path.subpaths[0]
        if path.fill is not None and len(points) > 2:  # a filled shape; a line has no inside
            continue
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
        # Measured by pen stroke: a curve cut into many short pieces is still one.
        drawn: dict[int, float] = {}
        for s in run:
            drawn[s.id] = drawn.get(s.id, 0.0) + geometry.distance(*s.subpaths[0])
        lengths = sorted(drawn.values())
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

    # A polyline is one pen stroke: its pieces stay in one glyph.
    pieces: list[list[Path]] = []
    for s in run:
        if pieces and pieces[-1][-1].id == s.id:
            pieces[-1].append(s)
        else:
            pieces.append([s])

    glyphs: list[list[Path]] = []
    lo = hi = 0.0
    for piece in pieces:
        ends = [sign * p[k] for s in piece for p in s.subpaths[0]]
        start, end = min(ends), max(ends)
        if glyphs and lo - 0.02 <= end and start <= hi + 0.02:
            glyphs[-1] += piece
            lo, hi = min(lo, start), max(hi, end)
        else:
            glyphs.append(piece)
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
    return Text(-1, by_word(out, BY_SIZE), box, line.height, angle, run[0].stroke, seq)


def by_word(text: str, pairs: dict[str, str]) -> str:
    """Letters that only size tells from another, given as small: capital pairs, take
    the case of the rest of their word. A word may start with a capital, so its first
    letter is never made small."""
    capitals = {v: k for k, v in pairs.items()}
    words = []
    for word in text.split(" "):
        others = [c for c in word if c.isalpha() and c not in pairs and c not in capitals]
        small = sum(c.islower() for c in others) > sum(c.isupper() for c in others)
        if others:
            word = "".join(
                (capitals.get(c, c) if small and k else pairs.get(c, c)) for k, c in enumerate(word)
            )
        words.append(word)
    return " ".join(words)


@cache
def _font(name: str) -> list[tuple[str, Shape]]:
    text = resources.files("schem2net").joinpath("profiles", f"{name}_font.json").read_text()
    return [
        (entry["char"], [tuple(map(tuple, seg)) for seg in shape])
        for entry in json.loads(text)
        for shape in entry["shapes"]
    ]
