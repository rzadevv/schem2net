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
from schem2net.refdes import is_common_ref
from schem2net.scene import Scene, Shape

TOUCH = 0.03  # mm, on top of half the stroke widths
HALF_GAP = 6.0  # mm between the two halves of a capacitor-like symbol
PIECE_GAP = 2.6  # mm between pieces of one drawn symbol
PIECE_MAX_SIZE = 50.0  # mm; larger drawings without pins are frames and borders
FRAME_HOLDS = 3  # a drawing holding this many symbols is a frame
FRAME_MIN_SIZE = 100.0  # mm, both ways; a frame spans most of the page
EDGE_PIN_LENGTH = 2.54  # mm; how far out a pin with no line is laid along its wire
EDGE_PIN_GAP = 0.5  # mm from a drawn pin within which a wire end is that pin's
FLAG_SIZE = 10.0  # mm; a closed outline smaller than this may be a port flag
PAD_SIZE = 5.0  # mm; a filled outline smaller than this may be a pad a pin leaves
BODY_OVER_FLAG = 3.0  # a body is this many times the size of a flag on a pin's tip
BIT_SIZE = 4.0  # mm; pinless pieces smaller than this may be bits of a neighbour
BIT_GAP = 0.8  # mm between such a bit and the piece drawn next to it
CROSS_LENGTHS = 1.5  # the strokes of a cross mark are about as long as each other
CROSS_MIDDLE = 0.2  # and meet within this share of their length of both middles
MIN_BOX = 1.0  # mm; narrower pinless pieces are lines, not boxes
ENTER_DEPTH = 2.54  # mm a pin crossing into a box ends inside its edge
DRAWN_TOGETHER_GAP = 5.0  # mm between a body and pins drawn with it
DRAWN_TOGETHER_SEQ = 3  # drawing steps between a body and pins drawn with it


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
    apart = sorted(t.seq for t in scene.fields) if profile.fields_follow_symbol else None
    symbols = _merge_halves(_group(scene, index, pins, apart, profile.flags_on_pins))
    runs = Runs(symbols, scene, profile) if profile.fields_follow_symbol else None
    if runs:
        symbols = _without_frames(runs.join_pieces(symbols))
    else:  # a frame spans all the drawing: gone first, so no piece joins it
        symbols = _join_drawn_together(_without_frames(symbols), scene, profile)
    if profile.pins_at_body_edge:
        _add_edge_pins(symbols, scene)
    fields.annotate(symbols, scene, profile, runs)
    return [s for s in symbols if s.ref or s.power]


def _find_pins(scene: Scene, index: GridIndex, profile: Profile) -> dict[int, Pin]:
    wires = GridIndex()
    for k, seg in enumerate(scene.wires):
        wires.add(k, geometry.bbox_of(seg))
    # Reference designators end one symbol's drawing and start the next.
    breaks = sorted(t.seq for t in scene.fields if is_common_ref(t.text))

    lines = [
        s
        for s in scene.shapes
        if _is_pin_like(s, profile, scene.wires, wires) and not _in_cross(s, scene, index)
    ]
    if profile.fields_follow_symbol:
        # Pieces of one pin are drawn with no text at all between them.
        chains = _chains(lines, scene, index, sorted(t.seq for t in scene.fields))
    else:
        chains = [[line] for line in lines]

    pins = {}
    for chain in chains:
        a, b = _chain_ends(chain)
        a_inner = _inner_end(chain, a, b, scene, index, profile, breaks, None)
        if a_inner is None and profile.drawn_by_part:
            # Graphics drawn apart from the pin belong to another symbol.
            a_inner = _inner_end(chain, a, b, scene, index, profile, breaks, breaks)
        if a_inner is None:
            wired_a, wired_b = (_on_wire(p, scene.wires, wires) for p in (a, b))
            if wired_a != wired_b:
                a_inner = wired_b
            elif profile.flags_on_pins:
                a_inner = _flag_on_tip(chain, a, b, scene, index)
            if a_inner is None:
                continue
        pin = Pin(chain[0].id, (a, b) if a_inner else (b, a))
        for shape in chain:
            pins[shape.id] = pin
    return pins


def _inner_end(
    chain: list[Shape],
    a: Point,
    b: Point,
    scene: Scene,
    index: GridIndex,
    profile: Profile,
    breaks: list[int],
    apart: list[int] | None,
) -> bool | None:
    """True if a is the end on the body, False if b is, None if the ends look alike."""
    ids = {s.id for s in chain}
    body_a, tips_a = _contacts(a, ids, scene, index, apart)
    body_b, tips_b = _contacts(b, ids, scene, index, apart)
    if body_a != body_b:
        return body_a
    if body_a:
        return None
    return _inner_by_neighbours(chain[0], tips_a, tips_b, scene, profile, breaks)


def _inner_by_neighbours(
    line: Shape, tips_a: list[int], tips_b: list[int], scene: Scene, profile: Profile, breaks
) -> bool | None:
    """When neither end sits on a body, tell which end belongs to the symbol, if possible.

    With pins in their own colour, the inner end meets body graphics tip to tip.
    Otherwise, with parts drawn one at a time, it meets graphics drawn with it.
    """
    pin_colour = bool(profile.colors.get("pin"))
    if not pin_colour and not profile.drawn_by_part:
        return None

    def own(tips: list[int]) -> bool:
        if pin_colour:
            return any(not profile.is_("pin", scene.shapes[j].color) for j in tips)
        return any(_drawn_together(line, scene.shapes[j], breaks) for j in tips)

    own_a, own_b = own(tips_a), own(tips_b)
    return own_a if own_a != own_b else None


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
                if not continues(line, other, end):
                    continue
                # Only where nothing else meets them, so a pin never runs through a body.
                on_body, others = _contacts(end, {line.id, j}, scene, index)
                inside = any(
                    scene.shapes[k].closed and _inside(end, scene.shapes[k].bbox)
                    for k in index.near(end, 0.0)
                )
                if not on_body and not others and not inside:
                    joined.union(line.id, j)
    return [[scene.shapes[i] for i in group] for group in joined.groups().values()]


def continues(a: Shape, b: Shape, end: Point) -> bool:
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


def _is_pin_like(
    shape: Shape, profile: Profile, wire_segs: list[Segment], wires: GridIndex
) -> bool:
    if len(shape.points) != 2 or shape.width > profile.pin_max_width:
        return False
    # Some libraries draw pins in the body colour; those count only where a wire meets them.
    if (
        profile.colors.get("pin")
        and not profile.is_("pin", shape.color)
        and not any(_on_wire(p, wire_segs, wires) for p in shape.points)
    ):
        return False
    a, b = shape.points
    return geometry.distance(a, b) >= profile.pin_min_length and geometry.is_axis_aligned((a, b))


def _in_cross(shape: Shape, scene: Scene, index: GridIndex) -> bool:
    """Whether the line is one stroke of a cross, as a "+" polarity mark is: another
    line of about its length crosses it, the two meeting at both their middles."""
    a, b = shape.points
    length = geometry.distance(a, b)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    for j in index.near(mid, CROSS_MIDDLE * length):
        other = scene.shapes[j]
        if j == shape.id or len(other.points) != 2:
            continue
        c, d = other.points
        other_mid = ((c[0] + d[0]) / 2, (c[1] + d[1]) / 2)
        ratio = geometry.distance(c, d) / length
        if (
            1 / CROSS_LENGTHS <= ratio <= CROSS_LENGTHS
            and geometry.distance(mid, other_mid) <= CROSS_MIDDLE * length
            and abs(_cosine((a, b), (c, d))) < 0.5
        ):
            return True
    return False


def _cosine(s: Segment, t: Segment) -> float:
    u, v = geometry.unit(*s), geometry.unit(*t)
    return u[0] * v[0] + u[1] * v[1]


def _pad(shape: Shape) -> bool:
    """A small filled outline, as a pad drawn in a symbol is."""
    return shape.filled and shape.closed and _size(shape.bbox) < PAD_SIZE


def _flag(shape) -> bool:
    """A small closed outline, as a port flag is."""
    return shape.closed and _size(shape.bbox) < FLAG_SIZE


def _flag_on_tip(chain, a: Point, b: Point, scene: Scene, index: GridIndex) -> bool | None:
    """Both ends on closed outlines and neither on a wire: a port or label flag set on
    the pin's tip is small beside the body the pin starts from."""
    ids = {s.id for s in chain}
    size_a, size_b = (_body_size(e, ids, scene, index) for e in (a, b))
    if min(size_a, size_b) > 0 and max(size_a, size_b) >= BODY_OVER_FLAG * min(size_a, size_b):
        return size_a > size_b
    return None


def _body_size(end: Point, own: set[int], scene: Scene, index: GridIndex) -> float:
    """The size of the largest closed outline this end lands on, 0 if none."""
    width = max(scene.shapes[i].width for i in own)
    best = 0.0
    for j in index.near(end, 1.0):
        other = scene.shapes[j]
        if j in own or not other.closed:
            continue
        tol = (width + other.width) / 2 + TOUCH
        if any(
            geometry.distance_to_segment(end, seg) <= tol for seg in geometry.segments(other.points)
        ):
            best = max(best, _size(other.bbox))
    return best


def _contacts(
    end: Point, own: set[int], scene: Scene, index: GridIndex, apart: list[int] | None = None
) -> tuple[bool, list[int]]:
    """Whether this end sits on body graphics, and which open shapes it meets tip to tip.

    Meeting another open shape tip to tip says nothing alone: it may be a second
    symbol, such as a power symbol placed on the pin. Landing on the middle of a
    line, on a corner of a polyline or on a closed outline is body. Shapes
    separated from this one by the `apart` breaks in drawing order are ignored.
    """
    tips = []
    width = max(scene.shapes[i].width for i in own)
    first = scene.shapes[min(own)]
    for j in index.near(end, 1.0):
        if j in own:
            continue
        other = scene.shapes[j]
        if apart is not None and not _drawn_together(first, other, apart):
            continue
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


def _group(
    scene: Scene,
    index: GridIndex,
    pins: dict[int, Pin],
    apart: list[int] | None = None,
    flags_apart: bool = False,
) -> list[Symbol]:
    """Join touching graphics into symbols. Graphics with field text drawn between them
    belong to different symbols, though a pin may follow the texts of the pin before."""
    uf = UnionFind()
    stubs: set[int] = set()
    for shape in scene.shapes:
        uf.find(shape.id)
        pin = pins.get(shape.id)
        for v in [pin.line[0]] if pin else shape.points:
            for j in index.near(v, 1.0):
                if j == shape.id or (pin and pins.get(j) is pin):
                    continue
                other = scene.shapes[j]
                tol = (shape.width + other.width) / 2 + TOUCH
                # A pin belongs to a body only through its inner end.
                if j in pins:
                    if geometry.distance(v, pins[j].line[0]) <= tol:
                        uf.union(shape.id, j)
                    elif pin and geometry.distance(v, pins[j].at) <= tol:
                        # A pin starting where another ends: the other is a stub of
                        # the body, which pins of two parts meeting never look like.
                        uf.union(shape.id, j)
                        stubs.add(id(pins[j]))
                    continue
                if not pin and apart is not None and not _drawn_together(shape, other, apart):
                    continue
                if flags_apart and _flag(shape) and _flag(other):
                    continue  # port flags stacked edge to edge name nets of their own
                # A pin may also end inside a filled pad it leaves.
                if any(
                    geometry.distance_to_segment(v, s) <= tol
                    for s in geometry.segments(other.points)
                ) or (pin and _pad(other) and geometry.in_polygon(v, other.points)):
                    uf.union(shape.id, j)

    symbols = []
    for members in uf.groups().values():
        body = [scene.shapes[m] for m in members if m not in pins or id(pins[m]) in stubs]
        body_box = _union([s.bbox for s in body]) if body else None
        # A line that ends inside the body is drawing, not a pin.
        own = list({id(pins[m]): pins[m] for m in members if m in pins}.values())
        own = [p for p in own if id(p) not in stubs]
        own = [p for p in own if not _in_body(p, body)]
        box = _union([scene.shapes[m].bbox for m in members])
        symbols.append(Symbol(sorted(members), box, own, body=body_box))
    return symbols


def _join_drawn_together(symbols: list[Symbol], scene: Scene, profile: Profile) -> list[Symbol]:
    """Without text between symbols to tell them apart, join a body drawn with no pins
    to the pieces with pins drawn along with it, nearby: a connector's box and its
    pins, drawn apart."""
    spans = {
        id(s): (
            min(scene.shapes[i].seq for i in s.shapes),
            max(scene.shapes[i].seq for i in s.shapes),
        )
        for s in symbols
        if s.shapes
    }
    # A box has area; a bare line drawn with no pin found on it is an unwired pin.
    boxes = [
        s
        for s in symbols
        if not s.pins and not s.power and id(s) in spans and min(_sides(s.bbox)) > MIN_BOX
    ]
    pieces = [s for s in symbols if s.pins and not s.power and id(s) in spans]
    joined = UnionFind()
    for s in symbols:
        joined.find(id(s))
    for box in boxes:
        lo, hi = spans[id(box)]
        for piece in pieces:
            a, b = spans[id(piece)]
            drawn_with = a <= hi + DRAWN_TOGETHER_SEQ and lo <= b + DRAWN_TOGETHER_SEQ
            # Near the box's edge: a part drawn well inside a section frame is not its pin.
            near = geometry.bbox_gap(box.bbox, piece.bbox) <= DRAWN_TOGETHER_GAP
            near = near and not _well_inside(piece.bbox, box.bbox)
            if (drawn_with and near) or _enters(piece, box):
                joined.union(id(box), id(piece))
    # Where parts are drawn one at a time, close pieces drawn interleaved are one part
    # drawn in pieces: a MOSFET's gate stands apart from its channel. Eagle draws by
    # layer, so there the drawing of neighbours interleaves. A bare line with no pin
    # found on it is an unwired pin, not a piece of body.
    if profile.drawn_by_part:
        drawn = [s for s in symbols if id(s) in spans and (s.pins or min(_sides(s.bbox)) > MIN_BOX)]
        for i, a in enumerate(drawn):
            seqs = sorted(scene.shapes[k].seq for k in a.shapes)
            for b in drawn[i + 1 :]:
                lo, hi = spans[id(b)]
                k = bisect.bisect_left(seqs, lo)
                interleaved = k < len(seqs) and seqs[k] < hi
                if interleaved and geometry.bbox_gap(a.bbox, b.bbox) <= PIECE_GAP:
                    joined.union(id(a), id(b))
    # Small pinless bits drawn right after or before a neighbour and almost touching it
    # are more of it: the separate bars of a ground sign under its stem.
    small = [s for s in symbols if not s.pins and id(s) in spans and _size(s.bbox) < BIT_SIZE]
    bits = small if profile.symbols_in_pieces else []
    others = [s for s in symbols if id(s) in spans]
    for bit in bits:
        lo, hi = spans[id(bit)]
        for other in others:
            a, b = spans[id(other)]
            if other is bit or not (a <= hi + 1 and lo <= b + 1):
                continue
            if geometry.bbox_gap(bit.bbox, other.bbox) <= BIT_GAP:
                joined.union(id(bit), id(other))
    groups: dict[int, list[Symbol]] = {}
    for s in symbols:
        groups.setdefault(joined.find(id(s)), []).append(s)
    return [_combine(parts) for parts in groups.values()]


def _well_inside(inner: BBox, outer: BBox) -> bool:
    """Inside the outer box and clear of its edges by more than a pin's reach."""
    g = DRAWN_TOGETHER_GAP
    x0, y0, x1, y1 = outer
    return x0 + g < inner[0] and inner[2] < x1 - g and y0 + g < inner[1] and inner[3] < y1 - g


def _enters(piece: Symbol, box: Symbol) -> bool:
    """Every pin of the piece crosses the box's edge, ending just inside it."""
    x0, y0, x1, y1 = box.bbox
    for pin in piece.pins:
        (x, y), outer = pin.line[0], pin.at
        depth = min(x - x0, x1 - x, y - y0, y1 - y)
        if not _inside((x, y), box.bbox) or depth > ENTER_DEPTH or _inside(outer, box.bbox):
            return False
    return True


def _add_edge_pins(symbols: list[Symbol], scene: Scene) -> None:
    """Pins drawn with no line: a wire that ends on a symbol's outline is a pin there.

    The pin is laid along the wire, out to where its number is written.
    """
    index = GridIndex()
    for k, symbol in enumerate(symbols):
        if symbol.body and not symbol.power:
            index.add(k, symbol.body)
    next_id = -1
    for a, b in scene.wires:
        for end, other in ((a, b), (b, a)):
            for k in index.near(end, TOUCH):
                symbol = symbols[k]
                if any(
                    geometry.distance(end, p) <= EDGE_PIN_GAP
                    for pin in symbol.pins
                    for p in pin.line
                ):
                    continue
                on_outline = any(
                    geometry.distance_to_segment(end, seg) <= TOUCH + scene.shapes[i].width
                    for i in symbol.shapes
                    for seg in geometry.segments(scene.shapes[i].points)
                )
                if not on_outline or _inside(other, symbol.body):
                    continue
                out = geometry.unit(end, other)
                length = min(EDGE_PIN_LENGTH, geometry.distance(end, other))
                tip = (end[0] + out[0] * length, end[1] + out[1] * length)
                symbol.pins.append(Pin(next_id, (end, tip)))
                next_id -= 1


def _without_frames(symbols: list[Symbol]) -> list[Symbol]:
    """Drop the page frame and title block: drawings that hold whole symbols."""

    def holds(outer: BBox, inner: BBox) -> bool:
        return (
            outer[0] <= inner[0]
            and outer[1] <= inner[1]
            and inner[2] <= outer[2]
            and inner[3] <= outer[3]
        )

    def frame(s: Symbol) -> bool:
        x0, y0, x1, y1 = s.bbox
        big = min(x1 - x0, y1 - y0) > FRAME_MIN_SIZE
        held = sum(holds(s.bbox, t.bbox) for t in symbols if t is not s)
        return big and held >= max(FRAME_HOLDS, len(symbols) / 2)  # it holds most of the page

    return [s for s in symbols if not frame(s)]


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

    def __init__(self, symbols: list[Symbol], scene: Scene, profile: Profile):
        self.scene = scene
        self.profile = profile
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
        bodies = {id(s): s.body for s in symbols}
        for text in sorted(scene.fields, key=lambda t: t.seq):
            k = bisect.bisect_left(end_seqs, text.seq) - 1
            if k >= 0:
                self.text_run[text.seq] = run = self.run[ends[k][1]]
                # The name of the last pin drawn comes before the fields; it sits inside.
                body = bodies[ends[k][1]]
                if not body or not _inside(geometry.center(text.bbox), body):
                    self.first.setdefault(run, text.seq)

    def join_pieces(self, symbols: list[Symbol]) -> list[Symbol]:
        """Join nearby pieces drawn in one run, such as the bars of a ground symbol."""
        joined = UnionFind()
        by_run: dict[int, list[Symbol]] = {}
        for s in symbols:
            joined.find(id(s))
            by_run.setdefault(self.run[id(s)], []).append(s)
        wires = GridIndex()
        for k, seg in enumerate(self.scene.wires):
            wires.add(k, geometry.bbox_of(seg))
        for parts in by_run.values():
            parts = [p for p in parts if p.pins or _size(p.bbox) <= PIECE_MAX_SIZE]
            # A piece on a wire without real pins is a power port, never part of a symbol
            # with pins. Its stem may pass for a pin drawn in the body colour.
            ports = {id(p) for p in parts if not self._real_pins(p) and self._wired(p, wires)}
            for i, a in enumerate(parts):
                for b in parts[i + 1 :]:
                    if (id(a) in ports and id(b) not in ports and b.pins) or (
                        id(b) in ports and id(a) not in ports and a.pins
                    ):
                        continue
                    if geometry.bbox_gap(a.bbox, b.bbox) <= PIECE_GAP:
                        joined.union(id(a), id(b))

        groups: dict[int, list[Symbol]] = {}
        for s in symbols:
            groups.setdefault(joined.find(id(s)), []).append(s)
        out = []
        for parts in groups.values():
            whole = _combine(parts)
            if len(parts) > 1:
                # A piece's line that ends inside another piece's outline is drawing.
                outlines = [
                    self.scene.shapes[i].bbox for i in whole.shapes if self.scene.shapes[i].closed
                ]
                whole.pins = [p for p in whole.pins if not any(_inside(p.at, b) for b in outlines)]
            self.run[id(whole)] = self.run[id(parts[0])]
            out.append(whole)
        return out

    def _real_pins(self, symbol: Symbol) -> list[Pin]:
        if not self.profile.colors.get("pin"):
            return symbol.pins
        return [p for p in symbol.pins if self.profile.is_("pin", self.scene.shapes[p.shape].color)]

    def _wired(self, symbol: Symbol, wires: GridIndex) -> bool:
        shapes = [self.scene.shapes[i] for i in symbol.shapes]
        ends = [p for shape in shapes for p in (shape.points[0], shape.points[-1])]
        return any(_on_wire(p, self.scene.wires, wires) for p in ends)

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
    return max(_sides(box))


def _sides(box: BBox) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def _in_body(pin: Pin, body: list[Shape]) -> bool:
    """Whether the pin ends inside the body, as a line of drawing does. A closed
    outline the pin starts on counts by its shape, the rest of the body by its box:
    a pin leaving the slanted side of a triangle ends within the triangle's box."""
    starts_on = [
        s
        for s in body
        if s.closed
        and any(
            geometry.distance_to_segment(pin.line[0], seg) <= s.width + TOUCH
            for seg in geometry.segments(s.points)
        )
    ]
    if any(geometry.in_polygon(pin.at, s.points) for s in starts_on):
        return True
    rest = [s.bbox for s in body if s.id not in {t.id for t in starts_on}]
    return bool(rest) and _inside(pin.at, _union(rest))


def _inside(p: Point, box: BBox) -> bool:
    return box[0] + TOUCH < p[0] < box[2] - TOUCH and box[1] + TOUCH < p[1] < box[3] - TOUCH


def _between(sorted_values: list[int], lo: int, hi: int) -> bool:
    k = bisect.bisect_right(sorted_values, lo)
    return k < len(sorted_values) and sorted_values[k] < hi
