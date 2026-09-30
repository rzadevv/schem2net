"""Stage 6: find pins and group symbol graphics into symbols.

A pin is a straight line with one end on its symbol's body and the other end
free. The free end is where it connects. Symbols are groups of graphics that
touch, but never through a pin's free end, so a power symbol placed directly
on a resistor pin stays a separate symbol.
"""

import bisect
from dataclasses import dataclass, field

from schem2net import fields, geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.primitives import BBox, Point
from schem2net.profile import Profile
from schem2net.scene import Scene, Shape

TOUCH = 0.03  # mm, on top of half the stroke widths
HALF_GAP = 6.0  # mm between the two halves of a capacitor-like symbol
PIECE_GAP = 2.6  # mm between pieces of one drawn symbol
PIECE_MAX_SIZE = 50.0  # mm; larger drawings without pins are frames and borders


@dataclass(slots=True)
class Pin:
    shape: int
    line: Segment  # from the body to the connection point
    number: str | None = None

    @property
    def at(self) -> Point:
        return self.line[1]


@dataclass
class Symbol:
    shapes: list[int]
    bbox: BBox
    pins: list[Pin] = field(default_factory=list)
    body: BBox | None = None  # graphics without pins
    ref: str | None = None
    unit: str | None = None
    value: str | None = None
    power: str | None = None  # net name, for power symbols
    anchors: list[Point] = field(default_factory=list)  # where a power symbol connects


def find(scene: Scene, profile: Profile) -> list[Symbol]:
    index = GridIndex()
    for shape in scene.shapes:
        index.add(shape.id, shape.bbox)

    pins = _find_pins(scene, index, profile)
    symbols = _merge_halves(_group(scene, index, pins))
    if profile.fields_follow_symbol:
        runs = Runs(symbols, scene)
        symbols = runs.join_pieces(symbols)
    else:
        runs = None
    fields.annotate(symbols, scene, profile, runs)
    return [s for s in symbols if s.ref or s.power]


def _find_pins(scene: Scene, index: GridIndex, profile: Profile) -> dict[int, Pin]:
    wires = GridIndex()
    for k, seg in enumerate(scene.wires):
        wires.add(k, geometry.bbox_of(seg))
    # Reference designators end one symbol's drawing and start the next.
    breaks = sorted(t.seq for t in scene.fields if fields.is_common_ref(t.text))

    lines = [s for s in scene.shapes if _is_pin_like(s, profile)]
    if profile.fields_follow_symbol:
        # Pieces of one pin are drawn with no text at all between them.
        chains = _chains(lines, scene, index, sorted(t.seq for t in scene.fields))
    else:
        chains = [[line] for line in lines]

    pins = {}
    for chain in chains:
        a, b = _chain_ends(chain)
        ids = {s.id for s in chain}
        body_a, tips_a = _contacts(a, ids, scene, index)
        body_b, tips_b = _contacts(b, ids, scene, index)
        if body_a and body_b:
            continue
        if body_a != body_b:
            a_inner = body_a
        else:
            # Neither end is on a body: decide by drawing order, then by wires.
            a_inner = None
            if profile.fields_follow_symbol:
                own_a = any(_drawn_together(chain[0], scene.shapes[j], breaks) for j in tips_a)
                own_b = any(_drawn_together(chain[0], scene.shapes[j], breaks) for j in tips_b)
                if own_a != own_b:
                    a_inner = own_a
            if a_inner is None:
                wired_a, wired_b = (_on_wire(p, scene.wires, wires) for p in (a, b))
                if wired_a == wired_b:
                    continue
                a_inner = wired_b
        pin = Pin(chain[0].id, (a, b) if a_inner else (b, a))
        for shape in chain:
            pins[shape.id] = pin
    return pins


def _chains(
    lines: list[Shape], scene: Scene, index: GridIndex, breaks: list[int]
) -> list[list[Shape]]:
    """Join straight pieces that continue each other, such as a pin drawn in two parts."""
    ids = {s.id for s in lines}
    joined = UnionFind()
    for line in lines:
        joined.find(line.id)
        for end in line.points:
            for j in index.near(end, TOUCH):
                other = scene.shapes[j]
                if j <= line.id or j not in ids or not _drawn_together(line, other, breaks):
                    continue
                if not _continues(line, other, end):
                    continue
                # Only where nothing else meets them, so a pin never runs through a body.
                on_body, others = _contacts(end, {line.id, j}, scene, index)
                if not on_body and not others:
                    joined.union(line.id, j)
    return [[scene.shapes[i] for i in group] for group in joined.groups().values()]


def _continues(a: Shape, b: Shape, end: Point) -> bool:
    """True if b starts where a ends and carries on in the same direction."""
    far_a = a.points[1] if geometry.distance(a.points[0], end) <= TOUCH else a.points[0]
    near_b, far_b = b.points if geometry.distance(b.points[0], end) <= TOUCH else b.points[::-1]
    if geometry.distance(near_b, end) > TOUCH:
        return False
    d, e = geometry.unit(far_a, end), geometry.unit(end, far_b)
    return d[0] * e[0] + d[1] * e[1] > 0.999


def _chain_ends(chain: list[Shape]) -> tuple[Point, Point]:
    points = [p for s in chain for p in s.points]
    a = max(points, key=lambda p: geometry.distance(p, chain[0].points[0]))
    b = max(points, key=lambda p: geometry.distance(p, a))
    return a, b


def _is_pin_like(shape: Shape, profile: Profile) -> bool:
    if len(shape.points) != 2 or shape.width > profile.pin_max_width:
        return False
    a, b = shape.points
    return geometry.distance(a, b) >= profile.pin_min_length and geometry.is_axis_aligned((a, b))


def _contacts(end: Point, own: set[int], scene: Scene, index: GridIndex) -> tuple[bool, list[int]]:
    """Whether this end sits on body graphics, and which open shapes it meets tip to tip.

    Meeting another open shape tip to tip says nothing alone: it may be a second
    symbol, such as a power symbol placed on the pin. Landing on the middle of a
    line, on a corner of a polyline or on a closed outline is body.
    """
    tips = []
    width = max(scene.shapes[i].width for i in own)
    for j in index.near(end, 1.0):
        if j in own:
            continue
        other = scene.shapes[j]
        tol = (width + other.width) / 2 + TOUCH
        for seg in geometry.segments(other.points):
            if geometry.distance_to_segment(end, seg) > tol:
                continue
            at_vertex = min(geometry.distance(end, seg[0]), geometry.distance(end, seg[1])) <= tol
            at_tip = (
                min(geometry.distance(end, p) for p in (other.points[0], other.points[-1])) <= tol
            )
            if not at_vertex or other.closed or not at_tip:
                return True, []
            tips.append(j)
    return False, tips


def _drawn_together(a: Shape, b: Shape, breaks: list[int]) -> bool:
    lo, hi = sorted((a.seq, b.seq))
    return not _between(breaks, lo, hi)


def _on_wire(p: Point, wires: list[Segment], index: GridIndex) -> bool:
    return any(geometry.distance_to_segment(p, wires[k]) <= TOUCH for k in index.near(p, TOUCH))


def _group(scene: Scene, index: GridIndex, pins: dict[int, Pin]) -> list[Symbol]:
    uf = UnionFind()
    for shape in scene.shapes:
        uf.find(shape.id)
        pin = pins.get(shape.id)
        for v in [pin.line[0]] if pin else shape.points:
            for j in index.near(v, 1.0):
                if j == shape.id:
                    continue
                other = scene.shapes[j]
                tol = (shape.width + other.width) / 2 + TOUCH
                if j in pins and geometry.distance(v, pins[j].at) <= tol:
                    continue
                if any(
                    geometry.distance_to_segment(v, s) <= tol
                    for s in geometry.segments(other.points)
                ):
                    uf.union(shape.id, j)

    symbols = []
    for members in uf.groups().values():
        body = [scene.shapes[m].bbox for m in members if m not in pins]
        body_box = _union(body) if body else None
        # A line that ends inside the body is drawing, not a pin.
        own = list({id(pins[m]): pins[m] for m in members if m in pins}.values())
        own = [p for p in own if not body_box or not _inside(p.at, body_box)]
        box = _union([scene.shapes[m].bbox for m in members])
        symbols.append(Symbol(sorted(members), box, own, body=body_box))
    return symbols


def _merge_halves(symbols: list[Symbol]) -> list[Symbol]:
    """Join two-pin parts drawn as two separate pieces, such as capacitor plates.

    The halves have one pin each, on the same axis, pointing away from each other.
    """
    singles = [s for s in symbols if len(s.pins) == 1]
    pairs = []
    for i, a in enumerate(singles):
        for b in singles[i + 1 :]:
            (a0, _), (b0, _) = a.pins[0].line, b.pins[0].line
            out, back = geometry.unit(*a.pins[0].line), geometry.unit(*b.pins[0].line)
            gap = (b0[0] - a0[0], b0[1] - a0[1])
            length = geometry.distance(a0, b0)
            opposite = out[0] * back[0] + out[1] * back[1] < -0.99
            on_axis = abs(out[0] * gap[1] - out[1] * gap[0]) <= 0.05
            behind = out[0] * gap[0] + out[1] * gap[1] < 0
            if length <= HALF_GAP and opposite and on_axis and behind:
                pairs.append((length, i, id(a), id(b)))

    merged: set[int] = set()
    by_id = {id(s): s for s in singles}
    out = [s for s in symbols if len(s.pins) != 1]
    for _, _, ia, ib in sorted(pairs):
        if ia not in merged and ib not in merged:
            merged |= {ia, ib}
            out.append(_combine([by_id[ia], by_id[ib]]))
    return out + [s for s in singles if id(s) not in merged]


class Runs:
    """Symbols drawn back to back, with no field text between them.

    Some generators draw each symbol's texts right after its graphics. Drawing
    order then ties texts to symbols, and rejoins symbols drawn in pieces.
    """

    def __init__(self, symbols: list[Symbol], scene: Scene):
        spans = sorted(
            (min(seqs), max(seqs), id(s))
            for s in symbols
            if (seqs := [scene.shapes[i].seq for i in s.shapes])
        )
        text_seqs = sorted(t.seq for t in scene.fields)

        self.run: dict[int, int] = {}
        run, last_end = -1, None
        for start, end, key in spans:
            if last_end is None or _between(text_seqs, last_end, start):
                run += 1
            self.run[key] = run
            last_end = end

        ends = sorted((end, key) for _, end, key in spans)
        end_seqs = [e for e, _ in ends]
        self.text_run: dict[int, int] = {}  # by text seq
        self.first: dict[int, int] = {}  # seq of the first text after each run
        for text in sorted(scene.fields, key=lambda t: t.seq):
            k = bisect.bisect_left(end_seqs, text.seq) - 1
            if k >= 0:
                self.text_run[text.seq] = run = self.run[ends[k][1]]
                self.first.setdefault(run, text.seq)

    def join_pieces(self, symbols: list[Symbol]) -> list[Symbol]:
        """Join nearby pieces drawn in one run, such as the bars of a ground symbol."""
        joined = UnionFind()
        by_run: dict[int, list[Symbol]] = {}
        for s in symbols:
            joined.find(id(s))
            by_run.setdefault(self.run[id(s)], []).append(s)
        for parts in by_run.values():
            parts = [p for p in parts if p.pins or _size(p.bbox) <= PIECE_MAX_SIZE]
            for i, a in enumerate(parts):
                for b in parts[i + 1 :]:
                    if geometry.bbox_gap(a.bbox, b.bbox) <= PIECE_GAP:
                        joined.union(id(a), id(b))

        groups: dict[int, list[Symbol]] = {}
        for s in symbols:
            groups.setdefault(joined.find(id(s)), []).append(s)
        out = []
        for parts in groups.values():
            whole = _combine(parts)
            self.run[id(whole)] = self.run[id(parts[0])]
            out.append(whole)
        return out

    def owns(self, symbol: Symbol, text_seq: int) -> bool:
        return self.text_run.get(text_seq) == self.run[id(symbol)]

    def first_text(self, symbol: Symbol) -> int | None:
        return self.first.get(self.run[id(symbol)])


def _combine(parts: list[Symbol]) -> Symbol:
    if len(parts) == 1:
        return parts[0]
    bodies = [p.body for p in parts if p.body]
    return Symbol(
        shapes=[i for p in parts for i in p.shapes],
        bbox=_union([p.bbox for p in parts]),
        pins=[pin for p in parts for pin in p.pins],
        body=_union(bodies) if bodies else None,
    )


def _union(boxes: list[BBox]) -> BBox:
    box = boxes[0]
    for other in boxes[1:]:
        box = geometry.union_bbox(box, other)
    return box


def _size(box: BBox) -> float:
    return max(box[2] - box[0], box[3] - box[1])


def _inside(p: Point, box: BBox) -> bool:
    return box[0] + TOUCH < p[0] < box[2] - TOUCH and box[1] + TOUCH < p[1] < box[3] - TOUCH


def _between(sorted_values: list[int], lo: int, hi: int) -> bool:
    k = bisect.bisect_right(sorted_values, lo)
    return k < len(sorted_values) and sorted_values[k] < hi
