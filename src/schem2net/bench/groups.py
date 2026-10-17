"""Learn which shapes of a page belong to one part, from the dev designs.

Each part's drawing in the source, an Eagle `.sch` or an EasyEDA `.json`, is laid
over its page: every shape drawn on a part's lines is that part's. Pairs of nearby
shapes are labelled alike or apart, and trees are fitted to tell them, one model per
generator, for `symbols.find` to split groups the rules made where nothing links
them. Logos and frames, which have no pins, are left out.
"""

import itertools
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import numpy as np

from schem2net import fields, geometry, pipeline, symbols
from schem2net.bench.font import PIN_LENGTHS, _offset, _place, _rotation
from schem2net.bench.roles import _fit

TOL = 0.15  # mm from a shape's points to its symbol's lines


def rows(design: Path) -> tuple[str, np.ndarray, np.ndarray]:
    """The generator, and the features and labels of the pairs of shapes on each page of
    a design where at least one of the pair lies on a part: 1 alike, 0 apart, -1 not
    known."""
    eagle = (design / "schematic.sch").is_file()
    if eagle:
        root = ET.parse(design / "schematic.sch").getroot()
        graphics = _graphics(root)
    else:
        sheets, wires = _easyeda(design / "schematic.json")
    pages = {}
    annotate = fields.annotate

    def capture(found, scene, profile, runs):
        pages[id(scene)] = {p.shape: p.line for s in found for p in s.pins}
        return annotate(found, scene, profile, runs)

    fields.annotate = capture
    try:
        read = pipeline.run(design / "schematic.pdf", embedded=False)
    finally:
        fields.annotate = annotate
    xs, ys = [], []
    for index, result in enumerate(read.pages):
        if id(result.scene) not in pages:  # a page skipped, or read but not kept
            continue
        scene, pins = result.scene, pages[id(result.scene)]
        if eagle:
            placed = _shifted(graphics.get(index, {}), _offset(root, index, result.page))
        else:
            placed = _laid_over(sheets.get(index, {}), wires.get(index, []), scene)
        owner = _owners(scene, placed)
        seqs = [t.seq for t in scene.fields]
        for i, j in symbols.near_pairs(scene):
            if i in owner or j in owner:
                xs.append(symbols.pair_features(scene, pins, i, j, seqs))
                ys.append(-1 if i not in owner or j not in owner else int(owner[i] == owner[j]))
    x = np.array(xs, dtype=float) if xs else np.zeros((0, 0))
    return ("eagle" if eagle else "easyeda"), x, np.array(ys, dtype=int)


def train(examples: list[tuple[str, np.ndarray, np.ndarray]]) -> dict[str, np.ndarray]:
    arrays = {}
    for generator in sorted({g for g, _, _ in examples}):
        mine = [(x[y >= 0], y[y >= 0]) for g, x, y in examples if g == generator and (y >= 0).any()]
        if mine:
            arrays |= {f"{generator}.{name}": value for name, value in _fit(mine).items()}
    return arrays


def _shifted(graphics: dict, shift) -> dict[str, list]:
    """An Eagle sheet's part lines on its page: its y runs up, from where it was laid."""
    if shift is None:
        return {}
    dx, dy = shift
    return {
        name: [((a[0] + dx, dy - a[1]), (b[0] + dx, dy - b[1])) for a, b in lines]
        for name, lines in graphics.items()
    }


# The sizes of an EasyEDA unit on a page tried: 10 mil as exported, or a point.
EASYEDA_UNITS = (0.254, 25.4 / 72)


def _laid_over(parts: dict, wires: list, scene) -> dict[str, list]:
    """An EasyEDA sheet's part lines on its page, at the size and place where most of
    its wire ends meet the page's."""
    drawn = {(round(x, 1), round(y, 1)) for seg in scene.wires for x, y in seg}
    ends = [p for w in wires[:150] for p in w]
    best, most = None, 0
    for unit in EASYEDA_UNITS:
        votes = Counter(
            (round(X - unit * x, 1), round(Y - unit * y, 1)) for x, y in ends for X, Y in drawn
        )
        if votes:
            shift, n = votes.most_common(1)[0]
            if n > most:
                best, most = (unit, shift), n
    if best is None or most < 0.4 * len(ends):
        return {}
    unit, (dx, dy) = best
    return {
        name: [((unit * a[0] + dx, unit * a[1] + dy), (unit * b[0] + dx, unit * b[1] + dy))
               for a, b in lines]
        for name, lines in parts.items()
    }  # fmt: skip


def _easyeda(path: Path) -> tuple[dict[int, dict[str, list]], dict[int, list]]:
    """For each sheet of an EasyEDA (Std) design, the lines of each part that has pins
    and of each flag, and its wires, in EasyEDA units."""
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, {}  # an EasyEDA Pro archive, which places no part's lines here
    parts: dict[int, dict[str, list]] = {}
    wires: dict[int, list] = {}
    for k, sheet in enumerate(data.get("schematics") or [data]):
        shapes = sheet["dataStr"]["shape"] if "dataStr" in sheet else sheet.get("shape", [])
        for shape in shapes:
            if shape.startswith("W~"):
                points = _numbers(shape.split("~")[1])
                wires.setdefault(k, []).extend(itertools.pairwise(points))
            elif shape.startswith(("LIB~", "F~")):  # a part, or a flag, as a supply sign
                items = shape.split("#@$" if shape.startswith("LIB~") else "^^")[1:]
                lines = [seg for item in items for seg in _easyeda_lines(item)]
                if shape.startswith("F~") or any(item.startswith("P~") for item in items):
                    parts.setdefault(k, {})[f"{len(parts.get(k, {}))}"] = lines
    return parts, wires


def _easyeda_lines(item: str) -> list:
    f = item.split("~")
    if f[0] in ("PL", "PG"):
        points = _numbers(f[1])
        return list(itertools.pairwise(points + points[:1] if f[0] == "PG" else points))
    if f[0] == "R" and len(f) > 6:
        x, y, w, h = float(f[1]), float(f[2]), float(f[5] or 0), float(f[6] or 0)
        c = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        return list(itertools.pairwise(c))
    if f[0] == "E":
        cx, cy, rx, ry = (float(v) for v in f[1:5])
        ring = [
            (cx + rx * math.cos(t * math.pi / 12), cy + ry * math.sin(t * math.pi / 12))
            for t in range(25)
        ]
        return list(itertools.pairwise(ring))
    if f[0] in ("PT", "A"):
        return _path_segments(f[1])
    if f[0] == "P":
        parts = item.split("^^")
        if len(parts) > 2:
            return _path_segments(parts[2].split("~")[0])
    return []


def _numbers(text: str) -> list:
    values = [float(v) for v in text.split()]
    return list(zip(values[0::2], values[1::2], strict=False))


def _path_segments(path: str) -> list:
    """The lines of an SVG path of straight moves (M, L, H, V and their relative forms);
    an arc is taken as the line to its end."""
    out: list = []
    at = start = (0.0, 0.0)
    tokens = path.replace(",", " ").split()
    k = 0
    while k < len(tokens):
        cmd = tokens[k]
        k += 1
        if cmd == "M":
            at = (float(tokens[k]), float(tokens[k + 1]))
            k += 2
            continue
        start = at
        if cmd == "L":
            at = (float(tokens[k]), float(tokens[k + 1]))
            k += 2
        elif cmd in ("h", "H"):
            at = (at[0] + float(tokens[k]) if cmd == "h" else float(tokens[k]), at[1])
            k += 1
        elif cmd in ("v", "V"):
            at = (at[0], at[1] + float(tokens[k]) if cmd == "v" else float(tokens[k]))
            k += 1
        elif cmd == "A":
            at = (float(tokens[k + 5]), float(tokens[k + 6]))
            k += 7
        else:
            continue
        out.append((start, at))
    return out


def _owners(scene, placed: dict[str, list]) -> dict[int, str]:
    """The part whose lines, on the page, each shape is drawn on, by most of its points."""
    index = geometry.GridIndex(cell=2.0)
    segs = []
    for name, lines in placed.items():
        for seg in lines:
            index.add(len(segs), geometry.bbox_of(seg))
            segs.append((seg, name))
    owner = {}
    for shape in scene.shapes:
        votes = Counter()
        for p in shape.points:
            near = {
                segs[k][1]
                for k in index.near(p, TOL)
                if geometry.distance_to_segment(p, segs[k][0]) <= TOL
            }
            votes.update(near)
        if votes:
            name, n = votes.most_common(1)[0]
            if n >= 0.8 * len(shape.points):
                owner[shape.id] = name
    return owner


def _graphics(root: ET.Element) -> dict[int, dict[str, list]]:
    """For each sheet, the lines of each placed symbol that has pins, in sheet units."""
    found, gates = {}, {}
    for lib in root.iterfind(".//libraries/library"):
        key = (lib.get("name"), lib.get("urn"))
        for sym in lib.iterfind("symbols/symbol"):
            found[(*key, sym.get("name"))] = sym
        for ds in lib.iterfind("devicesets/deviceset"):
            for gate in ds.iterfind("gates/gate"):
                gates[(*key, ds.get("name"), gate.get("name"))] = gate.get("symbol")
    parts = {p.get("name"): p for p in root.iterfind(".//parts/part")}
    out: dict[int, dict[str, list]] = {}
    for index, sheet in enumerate(root.iterfind(".//sheets/sheet")):
        for inst in sheet.iterfind("instances/instance"):
            part = parts.get(inst.get("part"))
            if part is None:
                continue
            lib = (part.get("library"), part.get("library_urn"))
            sym = found.get((*lib, gates.get((*lib, part.get("deviceset"), inst.get("gate")))))
            if sym is None or sym.find("pin") is None:
                continue
            angle, mirror = _rotation(inst.get("rot"))
            origin = float(inst.get("x")), float(inst.get("y"))
            name = f"{inst.get('part')}:{inst.get('gate')}"
            out.setdefault(index, {})[name] = [
                (_place(*a, origin, angle, mirror), _place(*b, origin, angle, mirror))
                for a, b in _lines(sym)
            ]
    return out


def _lines(sym: ET.Element) -> list:
    """A library symbol's drawing as line segments: wires, arcs, rectangles, circles,
    polygons and pins."""
    out = []
    for w in sym.iterfind("wire"):
        a, b = (float(w.get("x1")), float(w.get("y1"))), (float(w.get("x2")), float(w.get("y2")))
        points = _arc(a, b, float(w.get("curve", 0)))
        out += list(itertools.pairwise(points))
    for r in sym.iterfind("rectangle"):
        x1, y1, x2, y2 = (float(r.get(k)) for k in ("x1", "y1", "x2", "y2"))
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
        out += list(itertools.pairwise(corners))
    for c in sym.iterfind("circle"):
        cx, cy, r = float(c.get("x")), float(c.get("y")), float(c.get("radius"))
        ring = [
            (cx + r * math.cos(k * math.pi / 12), cy + r * math.sin(k * math.pi / 12))
            for k in range(25)
        ]
        out += list(itertools.pairwise(ring))
    for poly in sym.iterfind("polygon"):
        v = [(float(p.get("x")), float(p.get("y"))) for p in poly.iterfind("vertex")]
        out += list(itertools.pairwise(v + v[:1]))
    for pin in sym.iterfind("pin"):
        length = PIN_LENGTHS.get(pin.get("length", "long"), 7.62)
        if length:
            turn = math.radians(_rotation(pin.get("rot"))[0])
            x, y = float(pin.get("x")), float(pin.get("y"))
            out.append(((x, y), (x + length * math.cos(turn), y + length * math.sin(turn))))
    return out


def _arc(a, b, curve: float) -> list:
    """An Eagle wire bent through `curve` degrees, as points along it."""
    if not curve:
        return [a, b]
    chord = math.dist(a, b)
    t = math.radians(curve)
    r = chord / (2 * math.sin(t / 2))
    h = r * math.cos(t / 2)
    ux, uy = (b[0] - a[0]) / chord, (b[1] - a[1]) / chord
    cx, cy = (a[0] + b[0]) / 2 - uy * h, (a[1] + b[1]) / 2 + ux * h
    start = math.atan2(a[1] - cy, a[0] - cx)
    return [
        (cx + r * math.cos(start + t * k / 12), cy + r * math.sin(start + t * k / 12))
        for k in range(13)
    ]
