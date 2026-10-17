"""Learn which shapes of an Eagle page belong to one part, from the dev designs.

Each part's symbol in the `.sch` is laid over its page, as the font is: every shape
drawn on a symbol's lines is that part's. Pairs of nearby shapes are labelled alike
or apart, and trees are fitted to tell them, for `symbols.find` to split groups the
rules made where nothing links them. Logos and frames, which have no pins, are left
out.
"""

import itertools
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import numpy as np

from schem2net import fields, geometry, pipeline, symbols
from schem2net.bench.font import PIN_LENGTHS, _offset, _place, _rotation
from schem2net.bench.roles import _fit

TOL = 0.15  # mm from a shape's points to its symbol's lines


def rows(design: Path) -> tuple[np.ndarray, np.ndarray]:
    """Features and labels of the pairs of shapes on each page of an Eagle design, where
    at least one of the pair lies on a part's symbol: 1 alike, 0 apart, -1 not known."""
    root = ET.parse(design / "schematic.sch").getroot()
    graphics = _graphics(root)
    pages = {}
    annotate = fields.annotate

    def capture(found, scene, profile, runs):
        pages[scene.page] = (scene, {p.shape: p.line for s in found for p in s.pins})
        return annotate(found, scene, profile, runs)

    fields.annotate = capture
    try:
        read = pipeline.run(design / "schematic.pdf", embedded=False)
    finally:
        fields.annotate = annotate
    xs, ys = [], []
    for index, result in enumerate(read.pages):
        if result.scene is None or result.page.number not in pages:
            continue
        scene, pins = pages[result.page.number]
        owner = _owners(scene, graphics.get(index, {}), _offset(root, index, result.page))
        seqs = [t.seq for t in scene.fields]
        for i, j in symbols.near_pairs(scene):
            if i in owner or j in owner:
                xs.append(symbols.pair_features(scene, pins, i, j, seqs))
                ys.append(-1 if i not in owner or j not in owner else int(owner[i] == owner[j]))
    return np.array(xs, dtype=float) if xs else np.zeros((0, 0)), np.array(ys, dtype=int)


def train(examples: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, np.ndarray]:
    mine = [(x[y >= 0], y[y >= 0]) for x, y in examples if (y >= 0).any()]
    return {f"eagle.{name}": value for name, value in _fit(mine).items()}


def _owners(scene, graphics: dict, shift) -> dict[int, str]:
    """The part whose symbol each shape is drawn on, by most of its points."""
    if shift is None:
        return {}
    dx, dy = shift
    index = geometry.GridIndex(cell=2.0)
    segs = []
    for name, lines in graphics.items():
        for a, b in lines:
            seg = ((a[0] + dx, dy - a[1]), (b[0] + dx, dy - b[1]))
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
