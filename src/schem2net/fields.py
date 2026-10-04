"""Stage 6, continued: attach texts to symbols.

Power symbols get their net name, parts get a reference designator and a
value, and pins get their numbers.
"""

from __future__ import annotations

import heapq
import itertools
import re
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import linear_sum_assignment

from schem2net import geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.primitives import BBox, Point, Text
from schem2net.profile import Profile
from schem2net.refdes import (
    COMMON_PREFIXES,
    PART_VALUE,
    REFDES,
    TWO_TERMINAL_PREFIXES,
    is_common_ref,
)
from schem2net.scene import Scene, Shape

if TYPE_CHECKING:
    from schem2net.symbols import Pin, Runs, Symbol

REF_SEARCH = 10.0  # mm around a symbol body
POWER_NAME_GAP = 2.5  # mm between a power symbol and its name
POWER_MAX_SIZE = 8.0  # mm
PIN_NUMBER_GAP = 2.0  # mm between a pin and its number
OTHER_SIDE_COST = 0.5  # mm added for a pin number on its unusual side
PIN_NAME_GAP = 1.5  # mm between a pin's inner end and its name, unless the profile says
INSIDE_BODY_COST = REF_SEARCH  # a designator inside a part's outline, where profiles say
UNKNOWN_PREFIX_COST = REF_SEARCH  # "LM358" looks like a designator but is a value
MANY_PINS_COST = REF_SEARCH  # "L298" by a part of many pins is its value, not an inductor
MANY_PINS = 4  # more pins than a resistor, capacitor or inductor has
OTHER_SYMBOL_COST = REF_SEARCH  # text drawn after a different symbol
LATER_FIELD_COST = 5.0  # where the designator is the first text drawn after its symbol
VALUE_FIRST_COST = REF_SEARCH  # "Z80" drawn right before "U1" is the value
UNPAIRED_COST = 3 * REF_SEARCH + 1
PIECE_GAP = 1.27  # mm between pieces of one drawn symbol; parts sit a grid step apart
CORNER_GAP = 0.1  # mm between lines that meet in a drawing
MIN_GROUND_BASE = 0.5  # mm; a ground triangle's base is a grid step or so wide
ROW_HEAD_REACH = 2.0  # pitches past a row's end pin within which its first number sits
MIN_ROW = 3  # pins in a row numbered from its head
ARROW_SIZE = 4.0  # mm; a transistor's arrowhead is smaller than this
BAR_REACH = 3.0  # mm from a transistor's base or gate pin to its bar
MEET = 0.15  # mm between lines that meet in a symbol's drawing

PAD_COUNT = re.compile(r"\*\d+$")  # Eagle writes a pin on several pads as "A6*2"


def annotate(symbols: list[Symbol], scene: Scene, profile: Profile, runs: Runs | None) -> None:
    texts = _Texts(scene.fields)
    _name_power_symbols(symbols, texts, scene, profile, runs)
    if profile.power_names_in_labels:
        _name_power_from_labels(symbols, scene, profile)
    if profile.unnamed_ground:
        named = [s for s in symbols if s.power]
        for symbol in filter(_could_be_power, symbols):
            # A part with a real pin is a component, such as a mounting hole.
            if not _has_real_pin(symbol, scene, profile) and _looks_like_ground(symbol, scene):
                # A piece drawn beside it may have taken its name.
                piece = [s for s in named if geometry.bbox_gap(s.bbox, symbol.bbox) <= PIECE_GAP]
                symbol.power = piece[0].power if piece else profile.unnamed_ground
                symbol.anchors = _anchors(symbol, scene)
    _assign_refs(symbols, texts, runs, profile, _values_by_order(scene, profile))
    _number_pins(symbols, scene, profile, {id(texts.texts[i]) for i in texts.used})
    _assign_values(symbols, texts, runs, profile.pin_name_gap)


class _Texts:
    """Field texts with a spatial index. Each text is used once."""

    def __init__(self, texts: list[Text]):
        self.texts = texts
        self.used: set[int] = set()
        self.index = GridIndex(cell=5.0)
        for i, t in enumerate(texts):
            self.index.add(i, t.bbox)

    def near(self, box: BBox, radius: float) -> list[tuple[float, int]]:
        grown = (box[0] - radius, box[1] - radius, box[2] + radius, box[3] + radius)
        found = []
        for i in self.index.within(grown):
            gap = geometry.bbox_gap(box, self.texts[i].bbox)
            if gap <= radius and i not in self.used:
                found.append((gap, i))
        return sorted(found)


def _name_power_symbols(
    symbols: list[Symbol], texts: _Texts, scene: Scene, profile: Profile, runs: Runs | None
) -> None:
    """Power symbols are small, have at most one pin and a net name next to them."""
    # A name in line with the symbol first; only then one that overhangs it.
    for loose in (False, True):
        for symbol in filter(_could_be_power, symbols):
            for _, i in texts.near(symbol.bbox, POWER_NAME_GAP):
                text = texts.texts[i]
                if not _is_power_name(text, profile):
                    continue
                # The first text drawn after the symbol, or else one in line with it.
                if runs.first_text(symbol) == text.seq if runs else _in_line(symbol, text, loose):
                    symbol.power = text.text
                    symbol.anchors = _anchors(symbol, scene)
                    texts.used.add(i)
                    break


def _name_power_from_labels(symbols: list[Symbol], scene: Scene, profile: Profile) -> None:
    """Some generators write power port names in the net label colour."""
    local = [label for label in scene.labels if label.kind == "local" and not label.outline]
    pool = _Texts([Text(i, lb.text, lb.bbox, 0.0, lb.angle, None) for i, lb in enumerate(local)])
    for symbol in filter(_could_be_power, symbols):
        for _, i in pool.near(symbol.bbox, POWER_NAME_GAP):
            text = pool.texts[i]
            if _is_power_name(text, profile) and _in_line(symbol, text):
                symbol.power = text.text
                symbol.anchors = _anchors(symbol, scene)
                pool.used.add(i)
                break
    claimed = {id(local[i]) for i in pool.used}
    scene.labels = [label for label in scene.labels if id(label) not in claimed]


def _could_be_power(symbol: Symbol) -> bool:
    x0, y0, x1, y1 = symbol.bbox
    small = max(x1 - x0, y1 - y0) <= POWER_MAX_SIZE
    return not symbol.power and len(symbol.pins) <= 1 and bool(symbol.body) and small


def _is_power_name(text: Text, profile: Profile) -> bool:
    # A designator nearby means a one-pin part, such as a test point. Where designators
    # have a colour of their own, a name in another colour, such as A15, is not one.
    other_colour = (
        bool(profile.colors.get("designator"))
        and text.color is not None
        and not profile.is_("designator", text.color)
    )
    return (
        _is_net_name(text.text)
        and text.text not in profile.not_power_nets
        and (other_colour or not is_common_ref(text.text))
        and not PART_VALUE.match(text.text)
    )


def _has_real_pin(symbol: Symbol, scene: Scene, profile: Profile) -> bool:
    """A pin in the pin colour, or any pin where pins have no colour of their own,
    unless the generator's ground sign has a stem that reads as one."""
    if not profile.colors.get("pin"):
        return bool(symbol.pins) and not profile.ground_stems
    return any(profile.is_("pin", scene.shapes[p.shape].color) for p in symbol.pins)


def _looks_like_ground(symbol: Symbol, scene: Scene) -> bool:
    """The ground sign: shrinking parallel bars, a triangle pointing away from the stem
    or the wire, or a single bar across the stem with its name hidden."""
    return (
        _has_bars(symbol, scene)
        or _has_triangle(symbol, scene)
        or _is_tee(symbol, scene)
        or _bare_triangle_base(symbol, scene) is not None
    )


def _bare_triangle_base(symbol: Symbol, scene: Scene) -> Point | None:
    """The middle of the base of a symbol drawn as a lone triangle, base square to the page."""
    if len(symbol.shapes) != 1:
        return None
    shape = scene.shapes[symbol.shapes[0]]
    corners = list(dict.fromkeys((round(x, 2), round(y, 2)) for x, y in shape.points))
    if not shape.closed or len(corners) != 3:
        return None
    for k in range(3):
        a, b, apex = corners[k], corners[(k + 1) % 3], corners[(k + 2) % 3]
        mid = geometry.center(geometry.bbox_of((a, b)))
        along = geometry.unit(a, b)
        dx, dy = apex[0] - mid[0], apex[1] - mid[1]
        centred = abs(dx * along[0] + dy * along[1]) <= CORNER_GAP
        if geometry.is_axis_aligned((a, b), 0.01) and centred:
            return mid
    return None


def _is_tee(symbol: Symbol, scene: Scene) -> bool:
    lines = [scene.shapes[i].points for i in symbol.shapes]
    if len(lines) != 2 or any(len(ln) != 2 for ln in lines):
        return False
    for bar, stem in (lines, lines[::-1]):
        mid = geometry.center(geometry.bbox_of(bar))
        a, b = geometry.unit(*bar), geometry.unit(*stem)
        square = abs(a[0] * b[0] + a[1] * b[1]) < 0.1
        if square and min(geometry.distance(p, mid) for p in stem) <= CORNER_GAP:
            return True
    return False


def _has_triangle(symbol: Symbol, scene: Scene) -> bool:
    """A stem meeting the middle of a base, with two sides closing at an apex beyond it."""
    # Curves are drawn with many points; a triangle and its stem need few.
    straight = [scene.shapes[i].points for i in symbol.shapes if len(scene.shapes[i].points) <= 8]
    segs = _merge_collinear([seg for points in straight for seg in geometry.segments(points)])
    corners = [p for seg in segs for p in seg]

    def joined(a: Point, b: Point) -> bool:
        return any(
            geometry.distance_to_segment(a, seg) <= CORNER_GAP
            and geometry.distance_to_segment(b, seg) <= CORNER_GAP
            for seg in segs
        )

    for base in segs:
        if geometry.distance(*base) < MIN_GROUND_BASE:
            continue  # within the corner gap of everything near it
        mid = geometry.center(geometry.bbox_of(base))
        along = geometry.unit(*base)
        for stem in segs:
            near, far = sorted(stem, key=lambda p: geometry.distance(p, mid))
            if stem is base or geometry.distance(near, mid) > CORNER_GAP:
                continue
            up = geometry.unit(mid, far)
            if abs(up[0] * along[0] + up[1] * along[1]) > 0.1:
                continue
            for apex in corners:
                dx, dy = apex[0] - mid[0], apex[1] - mid[1]
                beyond = -(dx * up[0] + dy * up[1]) > CORNER_GAP
                centred = abs(dx * along[0] + dy * along[1]) <= CORNER_GAP
                if beyond and centred and joined(base[0], apex) and joined(base[1], apex):
                    return True
    return False


def _merge_collinear(segs: list[Segment]) -> list[Segment]:
    """Join segments that continue each other, such as a base drawn in two halves."""
    segs = list(segs)
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(segs):
            for j in range(i + 1, len(segs)):
                b = segs[j]
                for p, q in ((a[0], a[1]), (a[1], a[0])):
                    for r, t in ((b[0], b[1]), (b[1], b[0])):
                        if geometry.distance(p, r) > CORNER_GAP:
                            continue
                        u, v = geometry.unit(p, q), geometry.unit(r, t)
                        if u[0] * v[0] + u[1] * v[1] < -0.999:  # straight on through p
                            segs[i] = (q, t)
                            del segs[j]
                            merged = True
                            break
                    if merged:
                        break
                if merged:
                    break
            if merged:
                break
    return segs


def _has_bars(symbol: Symbol, scene: Scene) -> bool:
    lines = [scene.shapes[i].points for i in symbol.shapes if len(scene.shapes[i].points) == 2]
    for horizontal in (True, False):
        bars = [ln for ln in lines if geometry.is_horizontal(tuple(ln)) == horizontal]
        across = 1 if horizontal else 0
        by_offset = sorted(bars, key=lambda ln: ln[0][across])
        lengths = [geometry.distance(*ln) for ln in by_offset]
        shrinking = lengths in (sorted(lengths), sorted(lengths, reverse=True))
        distinct = len({round(v, 2) for v in lengths}) == len(lengths)
        # One above another, centred on the stem's axis.
        offsets = [ln[0][across] for ln in by_offset]
        apart = all(b - a > CORNER_GAP for a, b in zip(offsets, offsets[1:], strict=False))
        centres = [(ln[0][1 - across] + ln[1][1 - across]) / 2 for ln in by_offset]
        centred = max(centres, default=0) - min(centres, default=0) <= CORNER_GAP
        if len(lengths) >= 3 and shrinking and distinct and apart and centred:
            return True
    return False


def _anchors(symbol: Symbol, scene: Scene) -> list[Point]:
    """A power symbol connects at its pin, or else at a loose end of its drawing, or
    at the middle of its base when it is a lone triangle; a port flag, a closed outline,
    at the corner its wire ends on."""
    if symbol.pins:
        return [p.at for p in symbol.pins]
    shapes = [scene.shapes[i] for i in symbol.shapes]
    loose = [p for shape in shapes if not shape.closed for p in (shape.points[0], shape.points[-1])]
    base = _bare_triangle_base(symbol, scene)
    if loose or base:
        return loose or [base]
    corners = {p for shape in shapes for p in shape.points}
    ends = [e for wire in scene.wires for e in wire]
    return [c for c in corners if any(geometry.distance(c, e) <= CORNER_GAP for e in ends)]


def _in_line(symbol: Symbol, text: Text, loose: bool = False) -> bool:
    """True if the text sits beyond the symbol along its pin axis, not beside it. Loosely,
    a name anchored at one end may overhang the symbol: it need only cross the pin's axis."""
    x0, y0, x1, y1 = symbol.bbox
    cx, cy = geometry.center(text.bbox)
    above_or_below = x0 - 0.5 <= cx <= x1 + 0.5 and not y0 < cy < y1
    left_or_right = y0 - 0.5 <= cy <= y1 + 0.5 and not x0 < cx < x1
    if not symbol.pins:
        return above_or_below or left_or_right
    (ax, ay), tx0, ty0, tx1, ty1 = symbol.pins[0].at, *text.bbox

    upright = round(text.angle) % 180 == 0

    def overhangs(lo: float, hi: float, axis: float, a: float, b: float) -> bool:
        """Runs across the axis, as a name turned with its symbol does, with one end over
        the symbol, which spans a to b."""
        across = upright != geometry.is_horizontal(symbol.pins[0].line)
        ends = (a - 0.5 <= lo <= b + 0.5) or (a - 0.5 <= hi <= b + 0.5)
        return loose and across and lo - 0.5 <= axis <= hi + 0.5 and ends

    # The name sits past the end away from where the wire meets the pin.
    if geometry.is_horizontal(symbol.pins[0].line):
        far = cx < x0 if ax > (x0 + x1) / 2 else cx > x1
        return (left_or_right or overhangs(ty0, ty1, ay, y0, y1)) and far
    far = cy < y0 if ay > (y0 + y1) / 2 else cy > y1
    return (above_or_below or overhangs(tx0, tx1, ax, x0, x1)) and far


def _assign_refs(
    symbols: list[Symbol],
    texts: _Texts,
    runs: Runs | None,
    profile: Profile,
    values: set[int],
) -> None:
    """`values` holds the ids of texts drawn where a value goes."""
    parts = [s for s in symbols if s.pins and not s.power]
    first_reach = profile.designator_first and runs
    candidates = []
    for si, symbol in enumerate(parts):
        # Where the designator is drawn first, that text may sit further away.
        reach = 3 * REF_SEARCH if first_reach else REF_SEARCH
        for gap, ti in texts.near(symbol.body or symbol.bbox, reach):
            if gap > REF_SEARCH and texts.texts[ti].seq != runs.first_text(symbol):
                continue
            text = texts.texts[ti]
            if profile.colors.get("designator") and not profile.is_("designator", text.color):
                continue  # where designators have a colour of their own, only that
            match = REFDES.match(text.text)
            if not match or is_pin_name(symbol, text, profile.pin_name_gap):
                continue
            cost = gap
            prefix = match.group(1).rstrip("$")
            if prefix not in COMMON_PREFIXES:
                cost += UNKNOWN_PREFIX_COST
            elif prefix in TWO_TERMINAL_PREFIXES and len(symbol.pins) > MANY_PINS:
                cost += MANY_PINS_COST
            if profile.designators_outside and _belongs_to_a_pin(symbol, text, profile):
                cost += INSIDE_BODY_COST
            if id(text) in values:
                cost += VALUE_FIRST_COST
            if runs and not runs.owns(symbol, text.seq):
                cost += OTHER_SYMBOL_COST
            elif runs and profile.designator_first and runs.first_text(symbol) != text.seq:
                cost += LATER_FIELD_COST
            candidates.append((cost, si, ti))
    candidates.sort()

    # One text per symbol, minimising total cost. Then symbols drawn in pieces
    # (diode arrays, relay coils) share the text of the piece that got it.
    taken, used = set(), {}
    for si, ti in _best_pairs(candidates):
        _set_ref(parts[si], texts.texts[ti].text)
        taken.add(si)
        used[ti] = si
    for _, si, ti in candidates:
        if si in taken or ti not in used:
            continue
        # Without drawing order, only a piece right beside the one named can share it.
        beside = geometry.bbox_gap(parts[si].bbox, parts[used[ti]].bbox) <= PIECE_GAP
        if runs.owns(parts[si], texts.texts[ti].seq) if runs else beside:
            _set_ref(parts[si], texts.texts[ti].text)
            taken.add(si)
    texts.used |= set(used)


def _values_by_order(scene: Scene, profile: Profile) -> set[int]:
    """Ids of the texts that drawing order shows are values, where each part's value
    is drawn right before its designator: in a run of designator-coloured texts drawn
    back to back, every second one counting back from the last."""
    if not profile.value_before_designator:
        return set()
    order = sorted(
        [(t.seq, 0, k) for k, t in enumerate(scene.fields)]
        + [(s.seq, 1, k) for k, s in enumerate(scene.shapes)]
    )
    values, run = set(), []
    for _, kind, k in [*order, (0, 1, -1)]:
        if kind == 0 and profile.is_("designator", scene.fields[k].color):
            run.append(scene.fields[k])
            continue
        values |= {id(t) for t in run[-2::-2]}
        run = []
    return values


def _best_pairs(candidates: list[tuple[float, int, int]]) -> list[tuple[int, int]]:
    """Optimal one-to-one pairing, solved separately for each cluster of rivals."""
    clusters = UnionFind()
    for _, si, ti in candidates:
        clusters.union(("s", si), ("t", ti))
    by_cluster: dict = {}
    for cost, si, ti in candidates:
        by_cluster.setdefault(clusters.find(("s", si)), []).append((cost, si, ti))

    pairs = []
    for group in by_cluster.values():
        rows = sorted({si for _, si, _ in group})
        cols = sorted({ti for _, _, ti in group})
        # Extra columns let a symbol stay unpaired at a cost.
        cost = np.full((len(rows), len(cols) + len(rows)), UNPAIRED_COST * 10)
        cost[:, len(cols) :] = UNPAIRED_COST
        for c, si, ti in group:
            cost[rows.index(si), cols.index(ti)] = c
        for r, c in zip(*linear_sum_assignment(cost), strict=True):
            if c < len(cols) and cost[r, c] < UNPAIRED_COST:
                pairs.append((rows[r], cols[c]))
    return pairs


def _set_ref(symbol: Symbol, text: str) -> None:
    prefix, number, unit = REFDES.match(text).groups()
    symbol.ref = prefix + number
    symbol.unit = unit or None


def _number_pins(symbols: list[Symbol], scene: Scene, profile: Profile, taken: set[int]) -> None:
    """Pin numbers from the texts beside pins, leaving out texts already taken as
    designators or net names (`taken` holds their ids)."""
    numbers = [t for t in scene.pin_numbers if id(t) not in taken and not _is_value(t.text)]
    owned = [(p, s) for s in symbols if s.ref for p in s.pins]
    pins = [p for p, _ in owned]
    index = GridIndex()
    for i, pin in enumerate(pins):
        index.add(i, geometry.bbox_of(pin.line))

    options = []
    for t, text in enumerate(numbers):
        vertical_text = round(text.angle) % 180 == 90
        for i in index.near(geometry.center(text.bbox), PIN_NUMBER_GAP + 1):
            if geometry.is_horizontal(pins[i].line) == vertical_text:
                continue
            if _inside_body(owned[i][1], text):
                continue  # a pin name
            gap = _number_gap(text.bbox, pins[i].line, profile.pin_numbers_above)
            if gap is not None:
                options.append((gap, t, i))

    # Each number names one pin and each pin has one number: closest pairs first.
    named, used = set(), set()
    for _, t, i in sorted(options):
        if t not in used and i not in named:
            pins[i].number = PAD_COUNT.sub("", numbers[t].text)  # "A6*2": pin A6, two pads
            named.add(i)
            used.add(t)

    rest = [k for k in range(len(numbers)) if k not in used]
    used |= {rest[k] for k in _number_rows(symbols, [numbers[k] for k in rest])}

    # Small parts often hide pin numbers. Diodes are numbered from one end of
    # the triangle, other parts from the top or bottom, then the left.
    by_ref: dict[str, list[Symbol]] = {}
    for s in symbols:
        if s.ref:
            by_ref.setdefault(s.ref, []).append(s)
    for parts in by_ref.values():
        part_pins = [p for s in parts for p in s.pins]
        if len(part_pins) > 2 or any(p.number for p in part_pins):
            continue
        tips = [v for s in parts for v in _triangle_corners(s, scene)]
        if len(part_pins) == 2 and tips:
            # The cathode meets the triangle's tip, the anode the middle of its base.
            order = sorted(
                part_pins,
                key=lambda p: min(geometry.distance(p.line[0], v) for v in tips),
                reverse=profile.diode_pin_one_is_anode,
            )
        else:
            down = -1 if profile.hidden_pin_one_at_bottom else 1
            order = sorted(part_pins, key=lambda p: (down * p.at[1], p.at[0]))
        for number, pin in enumerate(order, 1):
            pin.number = str(number)

    unused = [t for k, t in enumerate(numbers) if k not in used]
    _name_pins(symbols, unused + scene.fields, profile.pin_name_gap)

    # Last, a transistor with neither numbers nor names shown: its pins by role.
    for parts in by_ref.values():
        if not any(p.number for s in parts for p in s.pins):
            for pin, role in _transistor_roles(parts, scene):
                pin.number = role


def _transistor_roles(parts: list[Symbol], scene: Scene) -> list[tuple[Pin, str]]:
    """Names for the pins of a transistor drawn without numbers. The base or gate is
    the pin square to the other two, leading to the middle of a bar; the emitter or
    source is the one nearer the arrowhead along the drawing, and a body diode, which
    joins both, is not taken for it. A bipolar transistor leaves its bar on slants."""
    pins = [p for s in parts for p in s.pins]
    if len(pins) != 3:
        return []
    own = {p.shape for p in pins}
    body = [scene.shapes[i] for s in parts for i in s.shapes if i not in own]
    lines = [s for s in body if len(s.points) == 2 and not s.closed]
    for k, control in enumerate(pins):
        a, b = (p for j, p in enumerate(pins) if j != k)
        u, v, w = (geometry.unit(*p.line) for p in (control, a, b))
        if abs(v[0] * w[0] + v[1] * w[1]) < 0.99 or abs(u[0] * v[0] + u[1] * v[1]) > 0.1:
            continue
        # Carried on inwards, perhaps along a lead, the pin meets the bar's middle.
        (x, y), (dx, dy) = control.line[0], geometry.unit(control.line[1], control.line[0])
        ahead = [(x + dx * t / 10, y + dy * t / 10) for t in range(int(BAR_REACH * 10) + 1)]
        bars = [s for s in lines if abs(_cos(s.points, control.line)) < 0.1]
        if not any(geometry.is_interior(q, tuple(s.points), 0.1) for q in ahead for s in bars):
            continue
        arrows = [s for s in body if s.closed and len(_corners(s)) in (3, 4)]
        arrows = [s for s in arrows if max(_box_sides(s.bbox)) < ARROW_SIZE]
        best = None
        for arrow in arrows:
            da, db = _path_lengths(body, arrow, (a.line[0], b.line[0]))
            if da != db and (best is None or abs(da - db) > best[0]):
                best = (abs(da - db), a if da < db else b)
        if best is None:
            return []
        emitter = best[1]
        other = b if emitter is a else a
        slants = any(not geometry.is_axis_aligned(tuple(s.points), 0.01) for s in lines)
        names = ("B", "E", "C") if slants else ("G", "S", "D")
        return list(zip((control, emitter, other), names, strict=True))
    return []


def _cos(points: list[Point], line: Segment) -> float:
    u, v = geometry.unit(points[0], points[-1]), geometry.unit(*line)
    return u[0] * v[0] + u[1] * v[1]


def _corners(shape: Shape) -> set[Point]:
    return {(round(x, 2), round(y, 2)) for x, y in shape.points}


def _box_sides(box: BBox) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def _path_lengths(
    body: list[Shape], start: Shape, ends: tuple[Point, Point]
) -> tuple[float, float]:
    """Distances along the drawing's lines from one of its shapes to two points on it."""
    offsets = list(itertools.accumulate((len(s.points) for s in body), initial=0))
    nodes = [p for s in body for p in s.points] + list(ends)
    edges: dict[int, list[tuple[float, int]]] = {k: [] for k in range(len(nodes))}

    def link(i: int, j: int) -> None:
        length = geometry.distance(nodes[i], nodes[j])
        edges[i].append((length, j))
        edges[j].append((length, i))

    segs = [
        (o + n, o + n + 1)
        for s, o in zip(body, offsets[:-1], strict=True)
        for n in range(len(s.points) - 1)
    ]
    heads = [
        (s, o)
        for s, o in zip(body, offsets[:-1], strict=True)
        if s.closed and max(_box_sides(s.bbox)) < ARROW_SIZE
    ]
    for i, j in segs:
        link(i, j)
    for p in range(len(nodes)):
        for i, j in segs:
            if (
                p not in (i, j)
                and geometry.distance_to_segment(nodes[p], (nodes[i], nodes[j])) <= MEET
            ):
                link(p, i)
                link(p, j)
        # A line ending under an arrowhead, inside it, meets it.
        for s, o in heads:
            if geometry.in_polygon(nodes[p], s.points):
                for n in range(o, o + len(s.points)):
                    link(p, n)
    k = body.index(start)
    best = {n: 0.0 for n in range(offsets[k], offsets[k + 1])}
    queue = [(0.0, n) for n in best]
    while queue:
        d, n = heapq.heappop(queue)
        if d > best[n]:
            continue
        for length, m in edges[n]:
            if d + length < best.get(m, float("inf")):
                best[m] = d + length
                heapq.heappush(queue, (d + length, m))
    far = float("inf")
    return best.get(len(nodes) - 2, far), best.get(len(nodes) - 1, far)


def _number_rows(symbols: list[Symbol], numbers: list[Text]) -> set[int]:
    """Number each row of unnumbered pins from the numbers at its ends: card sockets
    and headers may mark only the first pin of a row, past it or as pin 1 beside it,
    or the first and last. With one mark the count goes up from it. Returns the
    indices of the numbers used."""
    used: set[int] = set()
    for symbol in symbols:
        if not symbol.ref:
            continue
        for row in _rows(symbol.pins):
            numbered = [p for p in row if p.number]
            if numbered:
                # Only an end pin numbered, and as the first: its mark sits beside it.
                end = numbered[0]
                if len(numbered) > 1 or end not in (row[0], row[-1]) or end.number != "1":
                    continue
                row = row if end is row[0] else row[::-1]
                a, step = int(end.number), 1
            else:
                first = _row_mark(row, numbers, used)
                last = _row_mark(row[::-1], numbers, used)
                if first is None and last is None:
                    continue
                if first is not None and last is not None:
                    a, b = (int(numbers[k].text) for k in (first, last))
                    if abs(a - b) != len(row) - 1:
                        continue
                    step = 1 if b > a else -1
                else:
                    row = row if first is not None else row[::-1]
                    a, step = int(numbers[first if first is not None else last].text), 1
                used |= {k for k in (first, last) if k is not None}
            for n, pin in enumerate(row):
                pin.number = str(a + step * n)
    return used


def _row_mark(row: list[Pin], numbers: list[Text], used: set[int]) -> int | None:
    """The number set past the first pin of a row, in line with its pins."""
    end, inner = row[0], row[1]
    out = geometry.unit(inner.at, end.at)
    pitch = geometry.distance(inner.at, end.at)
    (x0, y0), (x1, y1) = end.line
    flat = geometry.is_horizontal(end.line)
    lo, hi = sorted((x0, x1) if flat else (y0, y1))
    marks = []
    for k, text in enumerate(numbers):
        if k in used or not text.text.isdigit():
            continue
        cx, cy = geometry.center(text.bbox)
        ahead = (cx - end.at[0]) * out[0] + (cy - end.at[1]) * out[1]
        t0, _, t1, _ = text.bbox if flat else (text.bbox[1], 0, text.bbox[3], 0)
        if 0 < ahead <= ROW_HEAD_REACH * pitch and t0 <= hi and lo <= t1:
            marks.append((ahead, k))
    return min(marks)[1] if marks else None


def _rows(pins: list[Pin]) -> list[list[Pin]]:
    """Evenly spaced pins pointing one way with their ends in line, in order along it."""
    lines: dict[tuple, list[Pin]] = {}
    for pin in pins:
        dx, dy = geometry.unit(*pin.line)
        horizontal = abs(dx) > abs(dy)
        across = pin.at[0] if horizontal else pin.at[1]
        key = (round(dx), round(dy), round(across, 1))
        lines.setdefault(key, []).append(pin)
    rows = []
    for (dx, _, _), row in lines.items():
        row.sort(key=lambda p: p.at[1] if dx else p.at[0])
        steps = [geometry.distance(a.at, b.at) for a, b in zip(row, row[1:], strict=False)]
        if len(row) >= MIN_ROW and max(steps) - min(steps) <= 0.05:
            rows.append(row)
    return rows


def _name_pins(symbols: list[Symbol], texts: list[Text], name_gap: float) -> None:
    """A pin drawn with its name but no number is known by its name."""
    options = []
    for symbol in symbols:
        unnamed = [p for p in symbol.pins if p.number is None]
        if not symbol.ref or not unnamed:
            continue
        for t, text in enumerate(texts):
            if not is_pin_name(symbol, text, name_gap):
                continue
            c = geometry.center(text.bbox)
            for pin in unnamed:
                inward = geometry.unit(pin.line[1], pin.line[0])
                ahead = (c[0] - pin.line[0][0]) * inward[0] + (c[1] - pin.line[0][1]) * inward[1]
                gap = geometry.distance(c, pin.line[0])
                if ahead > 0 and gap <= name_gap + max(_size(text), 1.0):
                    options.append((gap, t, id(pin), pin))
    taken, named = set(), set()
    for _, t, key, pin in sorted(options, key=lambda o: o[0]):
        if t not in taken and key not in named:
            pin.number = texts[t].text
            taken.add(t)
            named.add(key)


def _size(text: Text) -> float:
    return max(text.bbox[2] - text.bbox[0], text.bbox[3] - text.bbox[1])


def _triangle_corners(symbol: Symbol, scene: Scene) -> list[Point]:
    """Corners of closed three-sided outlines, such as the body of a diode."""
    corners = []
    for i in symbol.shapes:
        shape = scene.shapes[i]
        unique = {(round(x, 2), round(y, 2)) for x, y in shape.points}
        if shape.closed and len(unique) == 3:
            corners += list(unique)
    return corners


def _within_outline(symbol: Symbol, text: Text) -> bool:
    if not symbol.body:
        return False
    x0, y0, x1, y1 = symbol.body
    cx, cy = geometry.center(text.bbox)
    return x0 < cx < x1 and y0 < cy < y1


def _belongs_to_a_pin(symbol: Symbol, text: Text, profile: Profile) -> bool:
    """Where designators sit outside the box: a text inside it is a pin name, one by a
    pin outside it a pad number. Two-pin parts are left out, as their designator can
    come near the pin ends."""
    if len(symbol.pins) <= 2:
        return False
    return _within_outline(symbol, text) or _numbers_a_pin(symbol, text, profile)


def _numbers_a_pin(symbol: Symbol, text: Text, profile: Profile) -> bool:
    """True if the text sits where a pin of the part has its number."""
    above = profile.pin_numbers_above
    return any(_number_gap(text.bbox, pin.line, above) is not None for pin in symbol.pins)


def _number_gap(box: BBox, line: tuple[Point, Point], above: bool) -> float | None:
    """Distance from a pin to a number placed beside it, or None if it is not beside it.

    With `above`, numbers usually sit above horizontal pins and left of vertical
    ones; mirrored symbols put them on the other side, at a small extra cost.
    """
    (ax, ay), (bx, by) = line
    if geometry.is_horizontal(line):
        along, lo, hi, at = (box[0] + box[2]) / 2, min(ax, bx), max(ax, bx), ay
        near, far = at - box[3], box[1] - at
    else:
        along, lo, hi, at = (box[1] + box[3]) / 2, min(ay, by), max(ay, by), ax
        near, far = at - box[2], box[0] - at
    if not lo - 0.5 <= along <= hi + 0.5:
        return None
    if not above:
        gap = min(abs(near), abs(far))
    elif near >= -0.3:
        gap = near
    elif far >= -0.3:
        gap = far + OTHER_SIDE_COST
    else:  # across the pin's line: written over the pin
        gap = OTHER_SIDE_COST
    return gap if -0.3 <= gap <= PIN_NUMBER_GAP else None


def _assign_values(
    symbols: list[Symbol], texts: _Texts, runs: Runs | None, name_gap: float
) -> None:
    """The value is the next text drawn after the designator, or else the nearest one."""
    for symbol in symbols:
        if not symbol.ref:
            continue
        options = [
            (text.seq if runs else gap, i)
            for gap, i in texts.near(symbol.bbox, REF_SEARCH / 2)
            if not is_pin_name(symbol, text := texts.texts[i], name_gap)
            and (not runs or runs.owns(symbol, text.seq))
        ]
        if options:
            _, i = min(options)
            symbol.value = texts.texts[i].text
            texts.used.add(i)


def _inside_body(symbol: Symbol, text: Text) -> bool:
    """Inside the edge the pins start from, which markers drawn outside it do not move."""
    if len(symbol.pins) <= 2 or not symbol.body:
        return False
    x0, y0, x1, y1 = geometry.bbox_of(p.line[0] for p in symbol.pins)
    if x1 - x0 < 1:
        x0, x1 = symbol.body[0], symbol.body[2]
    if y1 - y0 < 1:
        y0, y1 = symbol.body[1], symbol.body[3]
    cx, cy = geometry.center(text.bbox)
    return x0 + 0.3 <= cx <= x1 - 0.3 and y0 + 0.3 <= cy <= y1 - 0.3


def _is_value(text: str) -> bool:
    """A part value with a unit or a decimal point, such as 10k or 0.1uF: never a pad."""
    return bool(PART_VALUE.match(text)) and not text.isdigit()


def _is_net_name(text: str) -> bool:
    return any(c.isalpha() for c in text)


def is_pin_name(symbol: Symbol, text: Text, gap: float = PIN_NAME_GAP) -> bool:
    """Pin names sit inside the body, next to the inner end of a pin, written along it."""
    if len(symbol.pins) <= 2 or not symbol.body:
        return False
    c = geometry.center(text.bbox)
    x0, y0, x1, y1 = symbol.body
    if not (x0 + 0.3 <= c[0] <= x1 - 0.3 and y0 + 0.3 <= c[1] <= y1 - 0.3):
        return False
    reach = gap + max(text.bbox[2] - text.bbox[0], text.bbox[3] - text.bbox[1]) / 2
    vertical_text = round(text.angle) % 180 == 90
    return any(
        geometry.distance(c, pin.line[0]) <= reach
        and geometry.is_horizontal(pin.line) != vertical_text
        for pin in symbol.pins
    )
