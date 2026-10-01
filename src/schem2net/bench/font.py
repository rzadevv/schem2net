"""Build the tables of Eagle's glyph shapes from PDFs and their .sch files.

The .sch says which texts are on a sheet and where, pin names and pad numbers
included. Its sheet is laid over the PDF page by the wires both share; each line
of text in the PDF, stroked or filled, is then paired with the sheet text of the
same length nearest to it, and every glyph becomes a labelled sample. Samples of
each character are grouped by shape, and the shapes seen often enough make the
table: one for the stroke font, one for letters printed as filled outlines.
"""

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from schem2net import fills, geometry, grid, pdf, profile, strokes

PAIR_DISTANCE = 1.0  # mm between a sheet text's anchor and a stroked line
SAME_SHAPE = 0.06  # glyph distance within one group of samples
MIN_SHARE = 0.1  # a group must hold this share of a character's samples
VARIANT = 0.55  # glyph distance from a character's usual shape still taken as it
COMMON_VARIANT = 0.25  # a shape seen this often, against the usual one, is kept anyway
ONE_STROKE = set("-_/\\|.,'`")  # characters drawn with a single stroke
SAME_OUTLINE = 0.07  # filled-letter distance within one group of samples
PIN_LENGTHS = {"point": 0.0, "short": 2.54, "middle": 5.08, "long": 7.62}  # mm
PAD_RISE = 1.3  # mm from a pin's line to the middle of its pad number
NAME_START = 2.3  # mm past a pin's inner end where its name begins

Sample = tuple[str, strokes.Shape]
FillSample = tuple[str, fills.Shape]


def samples(sch: Path, pdf_file: Path) -> tuple[list[Sample], list[FillSample]]:
    """Labelled glyphs of the stroke font and of filled outlines."""
    root = ET.parse(sch).getroot()
    texts = _sheet_texts(root)
    stroked, outlined = [], []
    rules = profile.load("eagle")
    for index, page in enumerate(pdf.read(pdf_file).pages):
        page = grid.rescale(page, 1 / grid.scale(page, rules))  # the sheet's own size
        shift = _offset(root, index, page)
        if shift is None:
            continue
        dx, dy = shift
        placed = [
            (t.replace(" ", ""), x + dx, dy - y) for t, x, y in texts.get(index, []) if t.strip()
        ]
        for line in strokes.runs_and_lines(page.paths):
            box = geometry.bbox_of(
                [p for g in line.glyphs for s in g.strokes for p in s.subpaths[0]]
            )
            text = _pair(box, len(line.glyphs), placed)
            if text:
                stroked += [
                    (c, strokes.normalise(g, line)) for g, c in zip(line.glyphs, text, strict=True)
                ]
        for line in fills.lines(page.paths):
            text = _pair(fills.box(line), len(line.glyphs), placed)
            if text:
                outlined += [
                    (c, fills.shape(g, line)) for g, c in zip(line.glyphs, text, strict=True)
                ]
    return stroked, outlined


def _pair(box, count: int, placed: list[tuple[str, float, float]]) -> str | None:
    """The sheet text of this many letters placed at the box, unless two fit as well."""
    near = sorted(
        (geometry.bbox_gap(box, (x, y, x, y)), t) for t, x, y in placed if len(t) == count
    )
    near = [n for n in near if n[0] < PAIR_DISTANCE]
    if not near or (len(near) > 1 and near[1][1] != near[0][1] and near[1][0] - near[0][0] < 0.2):
        return None
    return near[0][1]


def gap_samples(
    sch: Path, pdf_file: Path, shapes: list[tuple[str, strokes.Shape]]
) -> list[tuple[str, strokes.Shape]]:
    """Glyphs the table does not know yet, read from lines where only they are missing.

    A line read with one unknown glyph, whose other letters fit exactly one text of
    the .sch, says what that glyph is.
    """
    root = ET.parse(sch).getroot()
    known = {t.replace(" ", "") for texts in _sheet_texts(root).values() for t, _, _ in texts}
    found = []
    for page in pdf.read(pdf_file).pages:
        for line in strokes.runs_and_lines(page.paths):
            if len(line.glyphs) < 2:
                continue
            glyph_shapes = [strokes.normalise(g, line) for g in line.glyphs]
            chars = [strokes.match(sh, shapes) for sh in glyph_shapes]
            if chars.count(None) != 1:
                continue
            gap = chars.index(None)
            fits = [
                t
                for t in known
                if len(t) == len(chars) and all(c is None or c == t[i] for i, c in enumerate(chars))
            ]
            if len(fits) == 1:
                found.append((fits[0][gap], glyph_shapes[gap]))
    return found


def samples_of(job: tuple[Path, Path]) -> tuple[list[Sample], list[FillSample]]:
    try:
        return samples(*job)
    except (ET.ParseError, ValueError, KeyError):
        return [], []


def gap_samples_of(job: tuple) -> list[tuple[str, strokes.Shape]]:
    try:
        return gap_samples(*job)
    except (ET.ParseError, ValueError, KeyError):
        return []


def build(found: list[tuple[str, strokes.Shape]]) -> list[dict]:
    """A few typical shapes for each character."""
    by_char: dict[str, list[strokes.Shape]] = defaultdict(list)
    for char, shape in found:
        by_char[char].append(shape)
    groups = []  # (char, medoid, size)
    for char, shapes in by_char.items():
        clusters: list[list[strokes.Shape]] = []
        for shape in shapes:
            for c in clusters:
                if strokes.distance(c[0], shape) < SAME_SHAPE:
                    c.append(shape)
                    break
            else:
                clusters.append([shape])
        for c in clusters:
            if len(c) >= 2 and len(c) >= MIN_SHARE * len(shapes):
                medoid = min(c[:50], key=lambda s: sum(strokes.distance(s, t) for t in c[:50]))
                groups.append((char, medoid, len(c)))
    # A shape seen under two characters belongs to the one it was seen with more.
    kept = []
    for char, shape, size in sorted(groups, key=lambda g: -g[2]):
        if all(strokes.distance(shape, other) >= SAME_SHAPE for _, other, _ in kept):
            kept.append((char, shape, size))
    # A rare variant far from a character's usual shape, or with far fewer strokes, is a
    # fragment that happened to pair with the right number of letters. A common one is
    # another style of the font: Eagle has two, and draws some letters differently.
    table: dict[str, list] = defaultdict(list)
    usual: dict[str, tuple[strokes.Shape, int]] = {}
    for char, shape, size in kept:
        first, seen = usual.setdefault(char, (shape, size))
        if len(first) == 1 and char not in ONE_STROKE:
            continue
        near = strokes.distance(shape, first) < VARIANT and len(shape) >= 0.6 * len(first)
        if near or size >= COMMON_VARIANT * seen:
            table[char].append([[round4(p) for p in seg] for seg in shape])
    return [{"char": char, "shapes": shapes} for char, shapes in sorted(table.items())]


def build_fills(found: list[FillSample]) -> list[dict]:
    """A few typical filled shapes for each character, as for the stroke font."""
    by_char: dict[str, list[fills.Shape]] = defaultdict(list)
    for char, shape in found:
        by_char[char].append(shape)
    groups = []  # (char, medoid, size)
    for char, shapes in by_char.items():
        clusters: list[list[fills.Shape]] = []
        for shape in shapes:
            for c in clusters:
                if fills.distance(c[0], shape) < SAME_OUTLINE:
                    c.append(shape)
                    break
            else:
                clusters.append([shape])
        for c in clusters:
            if len(c) >= 2 and len(c) >= MIN_SHARE * len(shapes):
                medoid = min(c[:50], key=lambda s: sum(fills.distance(s, t) for t in c[:50]))
                groups.append((char, medoid, len(c)))
    table: dict[str, list] = defaultdict(list)
    kept: list[fills.Shape] = []
    for char, shape, _ in sorted(groups, key=lambda g: -g[2]):
        if all(fills.distance(shape, other) >= SAME_OUTLINE for other in kept):
            kept.append(shape)
            table[char].append(fills.to_json(shape))
    return [{"char": char, "shapes": shapes} for char, shapes in sorted(table.items())]


def round4(p: tuple[float, float]) -> tuple[float, float]:
    return round(p[0], 4), round(p[1], 4)


def _sheet_texts(root: ET.Element) -> dict[int, list[tuple[str, float, float]]]:
    """Texts on each sheet with their anchor in sheet coordinates: net labels, plain
    text, part names and values, the fixed text inside symbols, and pin names and pad
    numbers."""
    symbols, gates, devices = {}, {}, {}
    for lib in root.iterfind(".//libraries/library"):
        key = (lib.get("name"), lib.get("urn"))
        for sym in lib.iterfind("symbols/symbol"):
            symbols[(*key, sym.get("name"))] = sym
        for ds in lib.iterfind("devicesets/deviceset"):
            for gate in ds.iterfind("gates/gate"):
                gates[(*key, ds.get("name"), gate.get("name"))] = gate.get("symbol")
            for device in ds.iterfind("devices/device"):
                devices[(*key, ds.get("name"), device.get("name"))] = {
                    (c.get("gate"), c.get("pin")): c.get("pad", "").split()
                    for c in device.iterfind("connects/connect")
                }
    parts = {p.get("name"): p for p in root.iterfind(".//parts/part")}

    out: dict[int, list] = defaultdict(list)
    for index, sheet in enumerate(root.iterfind(".//sheets/sheet")):
        for net in sheet.iterfind("nets/net"):
            for label in net.iterfind("segment/label"):
                out[index].append((net.get("name"), float(label.get("x")), float(label.get("y"))))
        for text in sheet.iterfind("plain/text"):
            for line in (text.text or "").split("\n"):
                out[index].append((line, float(text.get("x")), float(text.get("y"))))
        for inst in sheet.iterfind("instances/instance"):
            part = parts.get(inst.get("part"))
            if part is None:
                continue
            values = {"NAME": part.get("name"), "VALUE": part.get("value") or part.get("deviceset")}
            smashed = {
                a.get("name"): (float(a.get("x")), float(a.get("y")))
                for a in inst.iterfind("attribute")
                if a.get("name") in values and a.get("x")
            }
            out[index] += [(values[k], x, y) for k, (x, y) in smashed.items()]
            lib = (part.get("library"), part.get("library_urn"))
            sym = symbols.get((*lib, gates.get((*lib, part.get("deviceset"), inst.get("gate")))))
            if sym is None:
                continue
            angle, mirror = _rotation(inst.get("rot"))
            origin = float(inst.get("x")), float(inst.get("y"))
            for text in sym.iterfind("text"):
                content = (text.text or "").strip()
                if content.startswith(">"):
                    key = content[1:]
                    if key not in values or key in smashed:
                        continue
                    content = values[key]
                if content:
                    x, y = _place(float(text.get("x")), float(text.get("y")), origin, angle, mirror)
                    out[index].append((content, x, y))
            pads = devices.get((*lib, part.get("deviceset"), part.get("device")), {})
            for pin in sym.iterfind("pin"):
                connected = pads.get((inst.get("gate"), pin.get("name")), [])
                out[index] += _pin_texts(pin, connected, origin, angle, mirror)
    return out


def _pin_texts(pin: ET.Element, pads: list[str], origin, angle: float, mirror: bool) -> list:
    """A pin's name and pad number, anchored where Eagle draws them: the number above the
    middle of the pin, the name a little past its inner end."""
    length = PIN_LENGTHS.get(pin.get("length", "long"), 7.62)
    if not length:
        return []
    turn, _ = _rotation(pin.get("rot"))
    x, y = float(pin.get("x")), float(pin.get("y"))
    ax, ay = _place(x, y, origin, angle, mirror)
    bx, by = _place(
        x + length * math.cos(math.radians(turn)),
        y + length * math.sin(math.radians(turn)),
        origin,
        angle,
        mirror,
    )
    ux, uy = (bx - ax) / length, (by - ay) / length
    up = (0.0, PAD_RISE) if abs(ux) > 0.5 else (-PAD_RISE, 0.0)  # turned text: to the left
    shown = pin.get("visible", "both")
    out = []
    if shown in ("pad", "both") and pads:
        pad = pads[0] + (f"*{len(pads)}" if len(pads) > 1 else "")
        out.append((pad, (ax + bx) / 2 + up[0], (ay + by) / 2 + up[1]))
    name = pin.get("name", "").split("@")[0]
    if shown in ("pin", "both") and name and "!" not in name:  # "!" draws a bar, no letter
        out.append((name, bx + NAME_START * ux, by + NAME_START * uy))
    return out


def _offset(root: ET.Element, index: int, page) -> tuple[float, float] | None:
    """Where the sheet's origin falls on the page, voted on by wire ends (at 1:1)."""
    sheets = root.findall(".//sheets/sheet")
    if index >= len(sheets):
        return None
    ends = []
    for w in sheets[index].iterfind("nets/net/segment/wire"):
        ends += [(float(w.get("x1")), float(w.get("y1"))), (float(w.get("x2")), float(w.get("y2")))]
    drawn = {
        (round(x, 1), round(y, 1))
        for p in page.paths
        if p.fill is None and len(p.subpaths) == 1 and len(p.subpaths[0]) == 2 and p.width > 0.1
        for x, y in p.subpaths[0]
    }
    votes = Counter((round(X - x, 1), round(Y + y, 1)) for x, y in ends[:150] for X, Y in drawn)
    if not votes:
        return None

    def support(shift: tuple[float, float]) -> int:
        """Votes for a shift and the bins beside it: a shift ending in 5 rounds both ways."""
        return sum(
            votes.get((round(shift[0] + i / 10, 1), round(shift[1] + j / 10, 1)), 0)
            for i in (-1, 0, 1)
            for j in (-1, 0, 1)
        )

    best = max((s for s, _ in votes.most_common(20)), key=support)
    return best if support(best) >= 0.4 * min(len(ends), 150) else None


def _rotation(text: str | None) -> tuple[float, bool]:
    match = re.search(r"R(\d+(?:\.\d+)?)", text or "")
    return (float(match.group(1)) if match else 0.0), "M" in (text or "")


def _place(x: float, y: float, origin: tuple[float, float], angle: float, mirror: bool):
    if mirror:
        x = -x
    a = math.radians(angle)
    return origin[0] + x * math.cos(a) - y * math.sin(a), origin[1] + x * math.sin(
        a
    ) + y * math.cos(a)


def write(table: list[dict], path: Path) -> None:
    path.write_text(json.dumps(table, separators=(",", ":")) + "\n")
