"""Read text drawn as filled glyph outlines.

Some PDF printers turn text into filled shapes: a string becomes one filled path
whose subpaths outline its letters, holes included. The subpaths of one letter
come one after another and overlap along the line, which splits a string into
letters. Each letter is described by where it sits against the line's baseline
and height, its width, and a coarse raster of its shape, and is compared with a
table of known letters.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

import numpy as np

from schem2net.primitives import BBox, Path, Text

MAX_HEIGHT = 5.0  # mm; filled shapes taller than this across the line are not text
GRID = 12  # raster cells along each side of a letter
JOIN = 0.5  # share of the narrower extent two outlines overlap by in one letter
MAX_MATCH = 0.25  # distance still taken as a match
SPACE = 0.35  # a gap this many line heights wide between letters is a space
SCALES = (1.0, 1.15, 0.87, 1.3, 0.77)  # the line height is an estimate; tried in turn
SCALE_COST = 0.5  # per unit of log scale: a capital is not its small letter scaled down


@dataclass
class Glyph:
    rings: list[np.ndarray]  # outlines in line coordinates: along the line, then down
    box: BBox  # in line coordinates


@dataclass
class Line:
    glyphs: list[Glyph]
    upright: bool  # False for text turned a quarter, reading up the page
    base: float  # the baseline, in line coordinates
    height: float
    path: Path


@dataclass(frozen=True)
class Shape:
    """A letter, measured in line heights from the left end of its baseline."""

    raster: np.ndarray  # GRID * GRID cells, 1 where the letter is filled
    top: float
    bottom: float
    width: float


def read(paths: list[Path], font: str) -> tuple[list[Text], set[int]]:
    """Texts found among the filled shapes, and the seq of every path they use."""
    table = _font(font)
    texts, used = [], set()
    for path in paths:
        best = None
        for reading in _readings(path):
            read_lines = [
                (line, [match(shape(g, line), table) for g in line.glyphs]) for line in reading
            ]
            found = sum(c is not None for _, chars in read_lines for c in chars)
            if best is None or found > best[0]:
                best = (found, read_lines)
        if best is None:
            continue
        for line, chars in best[1]:
            if not chars or sum(c is not None for c in chars) < 0.8 * len(chars):
                continue
            if sum(bool(c and c.isalnum()) for c in chars) < 0.5 * len(chars):
                continue
            texts.append(_text(line, chars))
            used.add(path.seq)
    return texts, used


def lines(paths: list[Path]) -> list[Line]:
    """Every line of outlined letters, in the likelier reading, for building the table."""
    out = []
    for path in paths:
        readings = _readings(path)
        if readings:
            out += readings[0]
    return out


def shape(glyph: Glyph, line: Line) -> Shape:
    """How a letter looks, measured in its line's height."""
    x0, y0, x1, y1 = glyph.box
    h = line.height
    width, tall = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    steps = (np.arange(GRID) + 0.5) / GRID
    xs, ys = np.meshgrid(x0 + steps * width, y0 + steps * tall)
    points = np.column_stack([xs.ravel(), ys.ravel()])
    return Shape(
        _inside(points, glyph.rings).astype(float),
        (line.base - y0) / h,
        (line.base - y1) / h,
        (x1 - x0) / h,
    )


def distance(a: Shape, b: Shape) -> float:
    return float(
        np.abs(a.raster - b.raster).mean()
        + abs(a.top - b.top)
        + abs(a.bottom - b.bottom)
        + abs(a.width - b.width)
    )


def match(found: Shape, table: "Table") -> str | None:
    """The character of the nearest known letter, or None if none is near."""
    if not table.chars:
        return None
    pixels = np.abs(table.rasters - found.raster[None, :]).mean(axis=1)
    best, char = MAX_MATCH, None
    for scale in SCALES:
        cost = (
            pixels
            + SCALE_COST * abs(np.log(scale))
            + np.abs(table.tops - found.top * scale)
            + np.abs(table.bottoms - found.bottom * scale)
            + np.abs(table.widths - found.width * scale)
        )
        k = int(np.argmin(cost))
        if cost[k] < best:
            best, char = float(cost[k]), table.chars[k]
        if best < MAX_MATCH / 2:
            break
    return char


@dataclass
class Table:
    """Known letters, laid out for matching many at once."""

    chars: list[str]
    rasters: np.ndarray
    tops: np.ndarray
    bottoms: np.ndarray
    widths: np.ndarray


def table_of(entries: list[tuple[str, Shape]]) -> Table:
    if not entries:
        return Table([], np.zeros((0, GRID * GRID)), *(np.zeros(0) for _ in range(3)))
    return Table(
        [c for c, _ in entries],
        np.array([s.raster for _, s in entries]),
        np.array([s.top for _, s in entries]),
        np.array([s.bottom for _, s in entries]),
        np.array([s.width for _, s in entries]),
    )


def _readings(path: Path) -> list[list[Line]]:
    """The path read upright and turned, the likelier first; none if it is not text."""
    # Letters are filled and not outlined; a shape both filled and stroked is drawing.
    if path.fill is None or path.stroke is not None:
        return []
    if not path.subpaths or any(len(s) < 3 for s in path.subpaths):
        return []
    x0, y0, x1, y1 = path.bbox
    if min(x1 - x0, y1 - y0) > MAX_HEIGHT:
        return []
    upright = _lines(path, True)
    turned = _lines(path, False)
    # A turned string runs up the page: taller than wide, and split into letters along it.
    if y1 - y0 > x1 - x0 and len(turned) and sum(len(t.glyphs) for t in turned) > 1:
        return [turned, upright]
    return [upright, turned]


def _lines(path: Path, upright: bool) -> list[Line]:
    rings = [_to_line(np.asarray(sub, dtype=float), upright) for sub in path.subpaths]
    glyphs: list[list[np.ndarray]] = []
    lo = hi = 0.0
    for ring in rings:
        start, end = ring[:, 0].min(), ring[:, 0].max()
        overlap = min(end, hi) - max(start, lo)
        if glyphs and overlap >= JOIN * min(end - start, hi - lo):
            glyphs[-1].append(ring)
            lo, hi = min(lo, start), max(hi, end)
        else:
            glyphs.append([ring])
            lo, hi = start, end

    rows: list[list[Glyph]] = []
    prev = None
    for group in glyphs:
        points = np.concatenate(group)
        box = (points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max())
        if prev is None or box[0] < prev:  # back to the left: another line
            rows.append([])
        rows[-1].append(Glyph(group, box))
        prev = box[0]

    out = []
    for row in rows:
        tall = max(g.box[3] - g.box[1] for g in row)
        base = _baseline([g.box[3] for g in row], 0.06 * tall)
        height = max(base - g.box[1] for g in row)
        if height > 0:
            out.append(Line(row, upright, base, height, path))
    return out


def _baseline(bottoms: list[float], slack: float) -> float:
    """The bottom most letters share; round letters dip a little below it."""
    return max(bottoms, key=lambda b: (sum(abs(o - b) <= slack for o in bottoms), -b))


def _to_line(points: np.ndarray, upright: bool) -> np.ndarray:
    """Page points in line coordinates: along the line, then down across it."""
    if upright:
        return points
    return np.column_stack([-points[:, 1], points[:, 0]])  # reading up the page


def _inside(points: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Points inside the outlines, by the even-odd rule, so holes stay empty."""
    inside = np.zeros(len(points), dtype=bool)
    px, py = points[:, :1], points[:, 1:]
    for ring in rings:
        a, b = ring, np.roll(ring, -1, axis=0)
        ax, ay, bx, by = a[None, :, 0], a[None, :, 1], b[None, :, 0], b[None, :, 1]
        spans = (ay > py) != (by > py)
        dy = np.where(by == ay, 1e-12, by - ay)
        crossing = ax + (py - ay) * (bx - ax) / dy
        inside ^= (spans & (px < crossing)).sum(axis=1) % 2 == 1
    return inside


def box(line: Line) -> BBox:
    """Where the line lies on the page."""
    points = np.concatenate([ring for g in line.glyphs for ring in g.rings])
    u0, v0 = points.min(axis=0)
    u1, v1 = points.max(axis=0)
    if line.upright:
        return float(u0), float(v0), float(u1), float(v1)
    return float(v0), float(-u1), float(v1), float(-u0)


def _text(line: Line, chars: list[str | None]) -> Text:
    out = ""
    for i, (glyph, char) in enumerate(zip(line.glyphs, chars, strict=True)):
        if i and glyph.box[0] - line.glyphs[i - 1].box[2] > SPACE * line.height:
            out += " "
        out += char or "?"
    angle = 0.0 if line.upright else 90.0
    return Text(-1, _i_or_l(out), box(line), line.height, angle, line.path.fill, line.path.seq)


def _i_or_l(text: str) -> str:
    """Capital I and small l are one bar in most sans fonts: the rest of the word says
    which it is."""
    words = []
    for word in text.split(" "):
        letters = [c for c in word if c.isalpha() and c not in "Il"]
        small = sum(c.islower() for c in letters) > sum(c.isupper() for c in letters)
        words.append(re.sub("[Il]", "l" if small else "I", word))
    return " ".join(words)


@cache
def _font(name: str) -> Table:
    try:
        text = resources.files("schem2net").joinpath("profiles", f"{name}_fills.json").read_text()
    except FileNotFoundError:
        return table_of([])
    return table_of([(e["char"], from_json(s)) for e in json.loads(text) for s in e["shapes"]])


def to_json(s: Shape) -> dict:
    return {
        "raster": "".join("1" if v > 0.5 else "0" for v in s.raster),
        "top": round(s.top, 3),
        "bottom": round(s.bottom, 3),
        "width": round(s.width, 3),
    }


def from_json(d: dict) -> Shape:
    return Shape(np.array([float(c) for c in d["raster"]]), d["top"], d["bottom"], d["width"])
