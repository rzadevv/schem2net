"""Build the table of stroke-font glyph shapes from Eagle PDFs and their .sch files.

The .sch says which texts are on a sheet and where. Its sheet is laid over the
PDF page by the wires both share; each stroked line of text in the PDF is then
paired with the sheet text of the same length nearest to it, and every glyph
becomes a labelled sample. Samples of each character are grouped by shape, and
the shapes seen often enough make the table.
"""

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from schem2net import geometry, pdf, strokes

PAIR_DISTANCE = 1.0  # mm between a sheet text's anchor and a stroked line
SAME_SHAPE = 0.06  # glyph distance within one group of samples
MIN_SHARE = 0.1  # a group must hold this share of a character's samples
VARIANT = 0.55  # glyph distance from a character's usual shape still taken as it
ONE_STROKE = set("-_/\\|.,'`")  # characters drawn with a single stroke


def samples(sch: Path, pdf_file: Path) -> list[tuple[str, strokes.Shape]]:
    root = ET.parse(sch).getroot()
    texts = _sheet_texts(root)
    found = []
    for index, page in enumerate(pdf.read(pdf_file).pages):
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
            near = sorted(
                (geometry.bbox_gap(box, (x, y, x, y)), t)
                for t, x, y in placed
                if len(t) == len(line.glyphs)
            )
            near = [n for n in near if n[0] < PAIR_DISTANCE]
            if not near or (
                len(near) > 1 and near[1][1] != near[0][1] and near[1][0] - near[0][0] < 0.2
            ):
                continue
            for glyph, char in zip(line.glyphs, near[0][1], strict=True):
                found.append((char, strokes.normalise(glyph, line)))
    return found


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


def samples_of(job: tuple[Path, Path]) -> list[tuple[str, strokes.Shape]]:
    try:
        return samples(*job)
    except (ET.ParseError, ValueError, KeyError):
        return []


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
    # A variant far from a character's usual shape, or with a very different number of
    # strokes, is a fragment that happened to pair with the right number of letters.
    table: dict[str, list] = defaultdict(list)
    usual: dict[str, strokes.Shape] = {}
    for char, shape, _ in kept:
        usual.setdefault(char, shape)
        if len(usual[char]) == 1 and char not in ONE_STROKE:
            continue
        ratio = len(shape) / len(usual[char])
        if strokes.distance(shape, usual[char]) < VARIANT and 0.6 <= ratio <= 1.6:
            table[char].append([[round4(p) for p in seg] for seg in shape])
    return [{"char": char, "shapes": shapes} for char, shapes in sorted(table.items())]


def round4(p: tuple[float, float]) -> tuple[float, float]:
    return round(p[0], 4), round(p[1], 4)


def _sheet_texts(root: ET.Element) -> dict[int, list[tuple[str, float, float]]]:
    """Texts on each sheet with their anchor in sheet coordinates: net labels, plain
    text, part names and values, and the fixed text inside symbols."""
    symbols, gates = {}, {}
    for lib in root.iterfind(".//libraries/library"):
        key = (lib.get("name"), lib.get("urn"))
        for sym in lib.iterfind("symbols/symbol"):
            symbols[(*key, sym.get("name"))] = sym
        for ds in lib.iterfind("devicesets/deviceset"):
            for gate in ds.iterfind("gates/gate"):
                gates[(*key, ds.get("name"), gate.get("name"))] = gate.get("symbol")
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
    return out


def _offset(root: ET.Element, index: int, page) -> tuple[float, float] | None:
    """Where the sheet's origin falls on the page, voted on by wire ends (printed 1:1)."""
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
    best, count = votes.most_common(1)[0]
    return best if count >= 0.4 * min(len(ends), 150) else None


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
