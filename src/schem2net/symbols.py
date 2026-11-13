"""Stage 6: find pins and group symbol graphics into symbols.

A pin is a straight line with one end on its symbol's body and the other end
free. The free end is where it connects. Symbols are groups of graphics that
touch, but never through a pin's free end, so a power symbol placed directly
on a resistor pin stays a separate symbol.
"""

import bisect
from dataclasses import dataclass, field, replace
from functools import cache

import numpy as np

from schem2net import designators, fields, geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.primitives import BBox, Point
from schem2net.profile import Profile, learned_arrays, learned_file
from schem2net.refdes import PART_VALUE, is_common_ref
from schem2net.scene import Scene, Shape, recover_labels

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
BRIDGE_STEPS = 10  # points along a line tested for lying in a pad
BODY_OVER_FLAG = 3.0  # a body is this many times the size of a flag on a pin's tip
BIT_SIZE = 4.0  # mm; pinless pieces smaller than this may be bits of a neighbour
BIT_GAP = 0.8  # mm between such a bit and the piece drawn next to it
CROSS_LENGTHS = 1.5  # the strokes of a cross mark are about as long as each other
CROSS_MIDDLE = 0.2  # and meet within this share of their length of both middles
MIN_BOX = 1.0  # mm; narrower pinless pieces are lines, not boxes
ENTER_DEPTH = 2.54  # mm a pin crossing into a box ends inside its edge
DRAWN_TOGETHER_GAP = 5.0  # mm between a body and pins drawn with it
DRAWN_TOGETHER_SEQ = 3  # drawing steps between a body and pins drawn with it
DASH_VARIATION = 1.15  # maximum length/gap ratio in a regular dashed body edge
BETWEEN_MAX = 60  # shapes drawn between two of a piece's own, when looking for its other pieces

# A group the rules made stays whole where a learned model links its shapes this surely.
GROUP_LINK = 0.5
LINK_BATCH = 20_000  # pairs judged at once
GROUP_REACH = 1.0  # mm between shapes for a pair the model judges, or
GROUP_STEPS, GROUP_STEP_REACH = 6, 5.0  # drawing steps apart within this many mm
GROUPS_FILE = "groups.npz"


@dataclass(slots=True)
class Pin:
    shape: int
    line: Segment  # from the body to the connection point
    number: str | None = None
    # How the number was found: read beside the pin, counted along a "row" from its
    # marks, its "name", a "library" symbol, the generator's "pad names" for a diode, or,
    # where the drawing shows none, the diode's "polarity", a transistor's "role" or
    # the pin's "position".
    how: str | None = None
    name: str | None = None  # drawn beside a pin that shows no pad number, or its role

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
    power_hidden: bool = False  # no name was read: use the generator's usual one
    anchors: list[Point] = field(default_factory=list)  # where a power symbol connects
    power_ambiguous: bool = False  # an unread name on a bare tee could be another supply


def find(scene: Scene, profile: Profile) -> list[Symbol]:
    index = GridIndex()
    for shape in scene.shapes:
        index.add(shape.id, shape.bbox)

    pins = _find_pins(scene, index, profile)
    apart = _text_seqs(scene, profile) if profile.fields_follow_symbol else None
    symbols = _merge_halves(_group(scene, index, pins, apart, profile.flags_on_pins))
    runs = Runs(symbols, scene, profile) if profile.fields_follow_symbol else None
    if runs:
        symbols = _without_frames(runs.join_pieces(symbols))
    else:  # a frame spans all the drawing: gone first, so no piece joins it
        symbols = _join_drawn_together(_without_frames(symbols), scene, profile)
    if profile.learned_grouping and (model := _grouping_model(profile.name)):
        symbols = _split_unlinked(symbols, scene, model, pins)
    if profile.labels_in_outlines and profile.labels_on_wires:
        recover_labels(scene, [geometry.grown(s.bbox, TOUCH) for s in symbols])
    if profile.pins_at_body_edge:
        _add_edge_pins(symbols, scene, profile if profile.pinless_at_body_edge else None)
    fields.annotate(symbols, scene, profile, runs)
    symbols = _join_dashed_bodies(symbols, scene, profile)
    kept = [s for s in symbols if s.ref or s.power]
    found = _drawn_over(symbols, scene, lambda: designators.likelihood(scene, kept, runs, profile))
    return [s for s in found if s.ref or s.power]


def _join_dashed_bodies(symbols: list[Symbol], scene: Scene, profile: Profile) -> list[Symbol]:
    """Sections of one outline separated by matching dashed sides are one body.

    Both sides must continue between equally wide bodies, with at least three
    regular dashes per side. A lone dashed annotation cannot join components.
    """
    bodies = [
        s
        for s in symbols
        if s.pins and s.shapes and not s.power and s.body and min(_sides(s.body)) > MIN_BOX
    ]
    index = GridIndex()
    for shape in scene.shapes:
        if len(shape.points) == 2 and not shape.filled:
            index.add(shape.id, shape.bbox)
    joined = UnionFind()
    for k in range(len(symbols)):
        joined.find(k)
    owner = {i: k for k, s in enumerate(symbols) for i in s.shapes}

    def dashes(axis, cross, lo, hi):
        ends = ((lo, cross), (hi, cross)) if axis == 0 else ((cross, lo), (cross, hi))
        found = []
        for i in index.within(geometry.grown(geometry.bbox_of(ends), TOUCH)):
            if i not in owner:
                continue  # frames and other discarded graphics have no symbol
            shape = scene.shapes[i]
            a, b = sorted(p[axis] for p in shape.points)
            if (
                lo + TOUCH < a < b < hi - TOUCH
                and all(abs(p[1 - axis] - cross) <= TOUCH for p in shape.points)
                and not symbols[owner[i]].pins
                and not symbols[owner[i]].power
            ):
                found.append((a, b, i))
        found.sort()
        if len(found) < 3:
            return []
        lengths = [b - a for a, b, _ in found]
        gaps = [found[0][0] - lo, hi - found[-1][1]]
        gaps += [b[0] - a[1] for a, b in zip(found, found[1:], strict=False)]
        if (
            min(gaps) <= TOUCH
            or max(gaps) > min(lengths)
            or max(lengths) > DASH_VARIATION * min(lengths)
            or max(gaps) > DASH_VARIATION * min(gaps)
        ):
            return []
        return found

    for k, a in enumerate(bodies):
        for b in bodies[k + 1 :]:
            for axis in (0, 1):
                cross = 1 - axis
                if any(abs(a.body[j] - b.body[j]) > TOUCH for j in (cross, cross + 2)):
                    continue
                first, last = sorted((a, b), key=lambda s: s.body[axis])
                lo, hi = first.body[axis + 2], last.body[axis]
                if not TOUCH < hi - lo < min(_sides(first.body) + _sides(last.body)):
                    continue
                left = dashes(axis, a.body[cross], lo, hi)
                right = dashes(axis, a.body[cross + 2], lo, hi)
                if not left or len(left) != len(right):
                    continue
                if any(
                    abs(u - v) > TOUCH
                    for dash, other in zip(left, right, strict=True)
                    for u, v in zip(dash[:2], other[:2], strict=True)
                ):
                    continue
                strokes = [scene.shapes[i] for _, _, i in left + right]
                if len({s.color for s in strokes}) > 1 or max(
                    s.width for s in strokes
                ) > DASH_VARIATION * min(s.width for s in strokes):
                    continue
                together = [owner[a.shapes[0]], owner[b.shapes[0]], *[owner[s.id] for s in strokes]]
                for i in together[1:]:
                    joined.union(together[0], i)
    groups = {}
    for k, s in enumerate(symbols):
        groups.setdefault(joined.find(k), []).append(s)
    out = []
    for parts in groups.values():
        if len(parts) == 1:
            out.extend(parts)
            continue
        whole = _combine(parts)
        # The reference for an outlined part sits beyond the whole outline.
        # Labels along a section's pins must not become component references.
        axis = (
            0
            if _sides(whole.body)[0] > max(_sides(p.body)[0] for p in parts if p.body) + TOUCH
            else 1
        )
        names = [
            (part, t)
            for part in parts
            if part.ref
            for t in scene.fields
            if t.text.strip() == part.ref
            and (t.bbox[axis + 2] < part.bbox[axis] or t.bbox[axis] > part.bbox[axis + 2])
        ]
        if len({part.ref for part, _ in names}) != 1 or not all(
            t.bbox[axis + 2] < whole.bbox[axis] or t.bbox[axis] > whole.bbox[axis + 2]
            for _, t in names
        ):
            out.extend(parts)
            continue
        source = names[0][0]
        whole.ref, whole.unit, whole.value = source.ref, source.unit, source.value
        taken = {id(t) for _, t in names}
        for pin in whole.pins:
            pin.number = pin.how = pin.name = None
        fields._number_pins([whole], scene, profile, taken)
        out.append(whole)
    return out


def _drawn_over(symbols: list[Symbol], scene: Scene, chances) -> list[Symbol]:
    """A part drawn several times over itself, as alternative parts for one place, with a
    name for each stacked by its own: one part per name, on the same pins. A name is a
    text the designator model, `chances()`, finds likely, or of the usual form where no
    model was learned."""
    # A part's value is no name, though a printer that draws everything twice writes
    # it by its designator.
    references = {s.ref for s in symbols if s.ref}
    claimed = references | {s.value for s in symbols if s.value}
    written: dict[str, list] = {}
    for t in scene.fields:
        written.setdefault(t.text.strip(), []).append(t)
    out, likely = list(symbols), None
    for symbol in symbols:
        if not symbol.ref or symbol.power or not symbol.shapes:
            continue
        times = min(scene.shapes[i].copies for i in symbol.shapes)
        own = written.get(symbol.ref)
        if times < 2 or not own:
            continue
        here = min(own, key=lambda t: geometry.bbox_gap(t.bbox, symbol.bbox))
        stacked = [
            t
            for t in _stacked(here, scene.fields, references)
            if all(
                geometry.bbox_gap(t.bbox, symbol.body or symbol.bbox)
                <= geometry.bbox_gap(t.bbox, other.body) + TOUCH
                for other in symbols
                if other is not symbol and other.body and other.pins and not other.power
            )
        ]
        # A complete column of related names accounts for every drawing copy.
        # Values may have taken one of these names before the copies were restored.
        names = [here, *stacked]
        stems = {t.text.strip().split("_", 1)[0] for t in names}
        complete = (
            len(names) == times
            and len({t.text.strip() for t in names}) == times
            and len(stems) == 1
            and all("_" in t.text and fields._name_like(t.text.strip()) for t in names)
            and all(geometry.bbox_gap(t.bbox, symbol.body or symbol.bbox) > 0 for t in names)
            and all(
                t.text.strip() not in claimed or t.text.strip() == symbol.value for t in stacked
            )
        )
        if stacked and likely is None:
            likely = chances() or {}
        stacked = [
            t
            for t in stacked
            if complete
            or (
                t.text.strip() not in claimed
                and (
                    likely.get(id(t), 0.0) >= fields.WORD_FLOOR if likely else is_common_ref(t.text)
                )
            )
        ]
        for text in stacked[: times - 1]:
            name = text.text.strip()
            pins = [replace(p) for p in symbol.pins]
            out.append(Symbol(symbol.shapes, symbol.bbox, pins, body=symbol.body, ref=name))
            claimed.add(name)
            references.add(name)
            if symbol.value == name:
                symbol.value = None
    return out


def _stacked(text, texts, claimed: set[str]) -> list:
    """Unclaimed texts of one size and colour written in a column with this one, a line
    apart, nearest first."""
    alike = [
        t
        for t in texts
        if t is not text
        and t.color == text.color
        and abs(t.size - text.size) <= 0.1 * text.size
        and abs(t.bbox[0] - text.bbox[0]) <= 0.5
    ]
    out, top, bottom = [], text.bbox[1], text.bbox[3]
    while True:
        gaps = [
            (min(g for g in (top - t.bbox[3], t.bbox[1] - bottom) if g >= 0), k)
            for k, t in enumerate(alike)
            if t not in out and (top - t.bbox[3] >= 0 or t.bbox[1] - bottom >= 0)
        ]
        gap, k = min(gaps, default=(None, None))
        if gap is None or gap > 1.5 * text.size:
            break
        out.append(alike[k])
        top, bottom = min(top, alike[k].bbox[1]), max(bottom, alike[k].bbox[3])
    return [
        t for t in out if t.text.strip() not in claimed and not PART_VALUE.match(t.text.strip())
    ]


def _split_unlinked(
    symbols: list[Symbol], scene: Scene, model, candidates: dict[int, Pin] | None = None
) -> list[Symbol]:
    """Each group split where the learned model links none of its shapes across: two
    parts drawn touching, as a supply sign set on a part's pin, are two."""
    pins = {p.shape: p.line for s in symbols for p in s.pins}
    owner = {i: k for k, s in enumerate(symbols) for i in s.shapes}
    # A reconstructed pin is one object even when its lines were drawn apart.
    # Keep only candidates that survived grouping as real pins.
    for i, pin in (candidates or {}).items():
        if pin.shape in pins and owner.get(i) == owner.get(pin.shape):
            pins[i] = pin.line
    pairs = [(i, j) for i, j in near_pairs(scene) if i in owner and owner[i] == owner.get(j)]
    linked = UnionFind()
    for i, pin in (candidates or {}).items():
        if i in pins and owner.get(i) == owner.get(pin.shape):
            linked.union(i, pin.shape)
    seqs = [t.seq for t in scene.fields]
    # In batches, leaving out pairs earlier ones already linked: they cannot change which
    # shapes are linked, and a group of thousands of shapes has millions of pairs.
    for start in range(0, len(pairs), LINK_BATCH):
        batch = [
            (i, j) for i, j in pairs[start : start + LINK_BATCH] if linked.find(i) != linked.find(j)
        ]
        if not batch:
            continue
        rows = np.array([pair_features(scene, pins, i, j, seqs) for i, j in batch])
        for (i, j), p in zip(batch, designators.probability(model, rows), strict=True):
            if p >= GROUP_LINK:
                linked.union(i, j)
    out = []
    for symbol in symbols:
        pieces: dict[int, list[int]] = {}
        for i in symbol.shapes:
            pieces.setdefault(linked.find(i), []).append(i)
        if len(pieces) == 1:
            out.append(symbol)
            continue
        for shapes in pieces.values():
            body = [scene.shapes[i].bbox for i in shapes if i not in pins]
            out.append(
                Symbol(
                    sorted(shapes),
                    _union([scene.shapes[i].bbox for i in shapes]),
                    [p for p in symbol.pins if p.shape in shapes],
                    body=_union(body) if body else None,
                )
            )
    return out


def near_pairs(scene: Scene) -> list[tuple[int, int]]:
    """Pairs of shapes the grouping model judges: close together, or drawn a few steps
    apart and near."""
    index = GridIndex(cell=2.0)
    for s in scene.shapes:
        index.add(s.id, s.bbox)
    out = set()
    for s in scene.shapes:
        x0, y0, x1, y1 = s.bbox
        for j in index.within(
            (x0 - GROUP_REACH, y0 - GROUP_REACH, x1 + GROUP_REACH, y1 + GROUP_REACH)
        ):
            if j != s.id:
                out.add((min(s.id, j), max(s.id, j)))
    by_seq = sorted(scene.shapes, key=lambda s: s.seq)
    for k, s in enumerate(by_seq):
        for t in by_seq[k + 1 : k + 1 + GROUP_STEPS]:
            if geometry.bbox_gap(s.bbox, t.bbox) <= GROUP_STEP_REACH:
                out.add((min(s.id, t.id), max(s.id, t.id)))
    return sorted(out)


def pair_features(scene: Scene, pins: dict, i: int, j: int, seqs: list[int]) -> list[float]:
    """What the grouping model sees of two shapes: how close, how they touch, how far
    apart they were drawn and with how many texts between, and what each is."""
    a, b = scene.shapes[i], scene.shapes[j]
    ends_a, ends_b = (a.points[0], a.points[-1]), (b.points[0], b.points[-1])
    lo, hi = sorted((a.seq, b.seq))

    def tip_on(pin: int, other: Shape) -> bool:
        line = pins.get(pin)
        return line is not None and min(geometry.distance(line[1], q) for q in other.points) <= 0.1

    return [
        min(_reach(a, b), _reach(b, a)),
        min(geometry.distance(p, q) for p in ends_a for q in ends_b),
        abs(a.seq - b.seq),
        bisect.bisect_left(seqs, hi) - bisect.bisect_right(seqs, lo),  # seqs are sorted
        float(a.color == b.color),
        min(a.width, b.width) / max(a.width, b.width, 1e-6),
        geometry.distance(a.bbox[:2], a.bbox[2:]),
        geometry.distance(b.bbox[:2], b.bbox[2:]),
        float(a.closed),
        float(b.closed),
        float(i in pins),
        float(j in pins),
        float(tip_on(i, b) or tip_on(j, a)),
        len(a.points),
        len(b.points),
    ]


def _reach(a: Shape, b: Shape) -> float:
    """How far the points of one shape lie from the other's lines, at the closest."""
    segs = list(geometry.segments(b.points)) or [(b.points[0], b.points[0])]
    return min(geometry.distance_to_segment(p, s) for p in a.points for s in segs)


def _grouping_model(generator: str):
    return _forest(learned_file(GROUPS_FILE), generator)


@cache
def _forest(path, generator: str):
    arrays = learned_arrays(path)
    return designators.Forest(arrays, generator) if f"{generator}.classes" in arrays else None


def _text_seqs(scene: Scene, profile: Profile) -> list[int]:
    """Where the texts that end one symbol's drawing are drawn: its fields, and the
    names of flags where each is drawn right after its flag."""
    labels = scene.label_seqs if profile.labels_follow_flags else []
    return sorted([t.seq for t in scene.fields] + labels)


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
    # Only where drawing order keeps neighbouring symbols apart, so the lines made
    # body join nothing of another symbol.
    if profile.fields_follow_symbol:
        return _without_bodies(pins, scene, index, breaks)
    return _continued_pins(pins, scene, index, wires, profile)


def _continued_pins(
    pins: dict[int, Pin], scene: Scene, index: GridIndex, wires: GridIndex, profile: Profile
) -> dict[int, Pin]:
    """A pin can be drawn before a collinear extension that reaches its wire.

    A printed pad number anchors the pin. Follow only an unbranched chain from
    body graphics to a wire; a connection between two bodies is not such a chain.
    """
    numbers = fields._Texts([t for t in scene.pin_numbers if t.text.strip().isdecimal()])
    for first in list(pins.values()):
        if pins.get(first.shape) is not first or _on_wire(first.at, scene.wires, wires):
            continue
        own = {first.shape}
        if not _contacts(first.line[0], own, scene, index)[0] or not any(
            fields._number_gap(
                numbers.texts[i].bbox,
                first.line,
                profile.pin_numbers_above,
                profile.pin_numbers_overhang,
            )
            is not None
            for _, i in numbers.near(geometry.bbox_of(first.line), fields.PIN_NUMBER_GAP)
        ):
            continue
        end, last = first.at, scene.shapes[first.shape]
        extended = False
        while not _on_wire(end, scene.wires, wires):
            body, neighbours = _contacts(end, own, scene, index)
            if body or len(neighbours) != 1:
                break
            other = scene.shapes[neighbours[0]]
            if (
                len(other.points) != 2
                or other.width > profile.pin_max_width
                or not continues(last, other, end)
            ):
                break
            own.add(other.id)
            a, b = other.points
            end = b if geometry.distance(a, end) <= TOUCH else a
            last, extended = other, True
        if (
            extended
            and _on_wire(end, scene.wires, wires)
            and not _contacts(end, own, scene, index)[0]
        ):
            first.line = (first.line[0], end)
            for i in own:
                pins[i] = first
    return pins


def _without_bodies(
    pins: dict[int, Pin], scene: Scene, index: GridIndex, breaks: list[int]
) -> dict[int, Pin]:
    """A line another pin starts on square, at its middle, is body when it was only
    taken for a pin by starting on a line it runs along: the plate of a capacitor whose
    end overlaps its neighbour's plate, the parts set a grid step apart. The same
    applies to a plate ending on a closed body drawn after another reference."""
    started = set()
    for k, pin in pins.items():
        for j in index.near(pin.line[0], TOUCH):
            square = j in pins and abs(_cosine(pin.line, pins[j].line)) < 0.1
            if j != k and square and pins[j] is not pin and _starts_on(pin, scene, k, j):
                started.add(j)
    body = set()
    for k in started:
        pin = pins[k]
        for j in index.near(pin.line[0], TOUCH):
            other = scene.shapes[j]
            along = len(other.points) == 2 and abs(_cosine(pin.line, tuple(other.points))) > 0.99
            separate = other.closed and not _drawn_together(scene.shapes[k], other, breaks)
            if j != k and (along or separate) and _starts_on(pin, scene, k, j):
                body.add(id(pin))
    return {k: p for k, p in pins.items() if id(p) not in body}


def _starts_on(pin: Pin, scene: Scene, k: int, j: int) -> bool:
    """Whether pin k starts inside a segment of shape j."""
    tol = (scene.shapes[k].width + scene.shapes[j].width) / 2 + TOUCH
    return any(
        geometry.is_interior(pin.line[0], line, tol)
        for line in geometry.segments(scene.shapes[j].points)
    )


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
        if not _near_box(end, other.bbox, tol):
            continue
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
    for shape in scene.shapes:  # groups come out in the order of their first shape
        uf.find(shape.id)
    for shape in scene.shapes:
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
                if not _near_box(v, other.bbox, tol) or uf.find(shape.id) == uf.find(j):
                    continue  # joined already, or too far from all of it to touch
                # A pin may also end inside a filled pad it leaves.
                if any(
                    geometry.distance_to_segment(v, s) <= tol
                    for s in geometry.segments(other.points)
                ) or (pin and _pad(other) and geometry.in_polygon(v, other.points)):
                    uf.union(shape.id, j)
        if pin or len(shape.points) != 2:
            continue
        # A line from one filled pad into another is drawn with them and any pad it
        # crosses, as the bridge of a solder jumper is with its pads.
        pads = [
            j
            for j in index.within(shape.bbox)
            if j != shape.id
            and j not in pins
            and _pad(scene.shapes[j])
            and (apart is None or _drawn_together(shape, scene.shapes[j], apart))
        ]
        ends = [
            {j for j in pads if geometry.in_polygon(v, scene.shapes[j].points)}
            for v in shape.points
        ]
        if all(ends) and ends[0] != ends[1]:
            for j in pads:
                if _runs_into(shape.points, scene.shapes[j].points):
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


def _runs_into(line: list[Point], outline: list[Point]) -> bool:
    (x0, y0), (x1, y1) = line
    steps = [k / BRIDGE_STEPS for k in range(BRIDGE_STEPS + 1)]
    return any(
        geometry.in_polygon((x0 + t * (x1 - x0), y0 + t * (y1 - y0)), outline) for t in steps
    )


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
    index = GridIndex()
    for k, s in enumerate(symbols):
        index.add(k, s.bbox)

    def around(s: Symbol, gap: float, among) -> list[Symbol]:
        """The symbols of ids `among` whose boxes may lie within `gap` of the symbol's."""
        found = index.within(geometry.grown(s.bbox, gap))
        return [symbols[k] for k in sorted(found) if id(symbols[k]) in among]

    piece_ids = {id(p) for p in pieces}
    for box in boxes:
        lo, hi = spans[id(box)]
        # A piece that enters the box overlaps it, so it is near too.
        for piece in around(box, DRAWN_TOGETHER_GAP, piece_ids):
            a, b = spans[id(piece)]
            drawn_with = a <= hi + DRAWN_TOGETHER_SEQ and lo <= b + DRAWN_TOGETHER_SEQ
            # Near the box's edge. A box's pins connect outside it: a part whose pins all
            # end inside a section frame is not the frame's.
            near = geometry.bbox_gap(box.bbox, piece.bbox) <= DRAWN_TOGETHER_GAP
            near = near and not all(_inside(p.at, box.bbox) for p in piece.pins)
            if (drawn_with and near) or _enters(piece, box):
                joined.union(id(box), id(piece))
    # Where parts are drawn one at a time, close pieces drawn interleaved are one part
    # drawn in pieces: a MOSFET's gate stands apart from its channel. Eagle draws by
    # layer, so there the drawing of neighbours interleaves. A bare line with no pin
    # found on it is an unwired pin, not a piece of body.
    if profile.drawn_by_part:
        drawn = [s for s in symbols if id(s) in spans and (s.pins or min(_sides(s.bbox)) > MIN_BOX)]
        order = {id(s): i for i, s in enumerate(drawn)}
        for i, a in enumerate(drawn):
            seqs = sorted(scene.shapes[k].seq for k in a.shapes)
            for b in (b for b in around(a, PIECE_GAP, order.keys()) if order[id(b)] > i):
                lo, hi = spans[id(b)]
                k = bisect.bisect_left(seqs, lo)
                interleaved = k < len(seqs) and seqs[k] < hi
                if interleaved and geometry.bbox_gap(a.bbox, b.bbox) <= PIECE_GAP:
                    joined.union(id(a), id(b))
    else:
        woven = _woven(symbols, scene)
        for a, b in woven:
            joined.union(id(a), id(b))
    # Small pinless bits drawn right after or before a neighbour and almost touching it
    # are more of it: the separate bars of a ground sign under its stem.
    small = [s for s in symbols if not s.pins and id(s) in spans and _size(s.bbox) < BIT_SIZE]
    bits = small if profile.symbols_in_pieces else []
    for bit in bits:
        lo, hi = spans[id(bit)]
        for other in around(bit, BIT_GAP, spans.keys()):
            a, b = spans[id(other)]
            if other is bit or not (a <= hi + 1 and lo <= b + 1):
                continue
            if geometry.bbox_gap(bit.bbox, other.bbox) <= BIT_GAP:
                joined.union(id(bit), id(other))
    groups: dict[int, list[Symbol]] = {}
    for s in symbols:
        groups.setdefault(joined.find(id(s)), []).append(s)
    if profile.drawn_by_part:
        return [_combine(parts) for parts in groups.values()]
    whole = {id(s) for pair in woven for s in pair}
    wires = GridIndex()
    for k, seg in enumerate(scene.wires):
        wires.add(k, geometry.bbox_of(seg))
    out = []
    for parts in groups.values():
        symbol = _combine(parts)
        if len(parts) > 1 and any(id(p) in whole for p in parts):
            # Lines taken for pins of a piece that end within the whole drawing, on no
            # wire, are drawing: an arrow's stem, the lead of a body diode.
            own = {pin.shape for pin in symbol.pins}
            body = _union([scene.shapes[i].bbox for i in symbol.shapes if i not in own])
            symbol.pins = [
                pin
                for pin in symbol.pins
                if not _inside(pin.at, body) or _on_wire(pin.at, scene.wires, wires)
            ]
        out.append(symbol)
    return out


def _woven(symbols: list[Symbol], scene: Scene) -> list[tuple[Symbol, Symbol]]:
    """Pieces of one part where drawing goes layer by layer: between two shapes of a
    piece, only shapes of pieces close to it were drawn, as a MOSFET's gate, channel
    and arrow are drawn in turn. Pins drawn in a pass of their own, after every body,
    have the rest of the page between them and their body, so nothing is joined."""
    order = sorted(
        (scene.shapes[i].seq, k) for k, s in enumerate(symbols) if not s.power for i in s.shapes
    )
    places: dict[int, list[int]] = {}
    for at, (_, k) in enumerate(order):
        places.setdefault(k, []).append(at)
    pairs = []
    for k, at in places.items():
        piece = symbols[k]
        for lo, hi in zip(at, at[1:], strict=False):
            if not 1 < hi - lo <= BETWEEN_MAX:
                continue
            between = {order[j][1] for j in range(lo + 1, hi)}
            if all(geometry.bbox_gap(piece.bbox, symbols[j].bbox) <= PIECE_GAP for j in between):
                pairs += [(piece, symbols[j]) for j in between]
    return pairs


def _enters(piece: Symbol, box: Symbol) -> bool:
    """Every pin of the piece crosses the box's edge, ending just inside it."""
    x0, y0, x1, y1 = box.bbox
    for pin in piece.pins:
        (x, y), outer = pin.line[0], pin.at
        depth = min(x - x0, x1 - x, y - y0, y1 - y)
        if not _inside((x, y), box.bbox) or depth > ENTER_DEPTH or _inside(outer, box.bbox):
            return False
    return True


def _add_edge_pins(symbols: list[Symbol], scene: Scene, pinless: Profile | None = None) -> None:
    """Pins drawn with no line: a wire that ends on a symbol's outline is a pin there,
    on any symbol or, given a profile (`pinless`), only on parts drawn in body colours
    with no pin at all, as a test point is; power symbols there share the pin colour.

    The pin is laid along the wire, out to where its number is written.
    """

    def body_only(symbol: Symbol) -> bool:
        colours = {scene.shapes[i].color for i in symbol.shapes}
        return not symbol.pins and not any(pinless.is_("pin", c) for c in colours)

    index = GridIndex()
    for k, symbol in enumerate(symbols):
        if symbol.body and not symbol.power and (pinless is None or body_only(symbol)):
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
        # Whole parts inside a pinless outline establish that it is a section
        # border. Single-pin fragments can be drawing inside a transistor's body.
        if (
            not s.pins
            and min(x1 - x0, y1 - y0) > MIN_BOX
            and sum(len(t.pins) > 1 and holds(s.bbox, t.bbox) for t in symbols if t is not s)
            >= FRAME_HOLDS
        ):
            return True
        if min(x1 - x0, y1 - y0) <= FRAME_MIN_SIZE:
            return False
        held = sum(holds(s.bbox, t.bbox) for t in symbols if t is not s)
        return held >= max(FRAME_HOLDS, len(symbols) / 2)  # it holds most of the page

    return [s for s in symbols if not frame(s)]


def _merge_halves(symbols: list[Symbol]) -> list[Symbol]:
    """Join two-pin parts drawn as two separate pieces, such as capacitor plates.

    The halves have one pin each, on the same axis, pointing away from each other.
    """
    singles = [s for s in symbols if len(s.pins) == 1]
    index = GridIndex(HALF_GAP)
    for k, s in enumerate(singles):
        index.add(k, (*s.pins[0].line[0], *s.pins[0].line[0]))
    pairs = []
    for i, a in enumerate(singles):
        for b in (singles[j] for j in sorted(index.near(a.pins[0].line[0], HALF_GAP)) if j > i):
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
            if (seqs := [scene.shapes[i].seq for i in self._drawn_first(s)])
        )
        text_seqs = _text_seqs(scene, profile)

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

    def _drawn_first(self, symbol: Symbol) -> list[int]:
        """The shapes drawn before the symbol's texts: all, or its body where the pins
        come after the texts."""
        if not self.profile.pins_after_fields:
            return symbol.shapes
        pins = {p.shape for p in symbol.pins}
        return [i for i in symbol.shapes if i not in pins] or symbol.shapes

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


def _near_box(p: Point, box: BBox, tol: float) -> bool:
    """Whether p lies within tol of the box: no point of a shape is nearer than its box."""
    return box[0] - tol <= p[0] <= box[2] + tol and box[1] - tol <= p[1] <= box[3] + tol


def _inside(p: Point, box: BBox) -> bool:
    return box[0] + TOUCH < p[0] < box[2] - TOUCH and box[1] + TOUCH < p[1] < box[3] - TOUCH


def _between(sorted_values: list[int], lo: int, hi: int) -> bool:
    k = bisect.bisect_right(sorted_values, lo)
    return k < len(sorted_values) and sorted_values[k] < hi
