"""Stage 6, continued: attach texts to symbols.

Power symbols get their net name, parts get a reference designator and a
value, and pins get their numbers.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import linear_sum_assignment

from schem2net import geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.primitives import BBox, Point, Text
from schem2net.profile import Profile
from schem2net.refdes import COMMON_PREFIXES, REFDES, is_common_ref
from schem2net.scene import Scene

if TYPE_CHECKING:
    from schem2net.symbols import Runs, Symbol

REF_SEARCH = 10.0  # mm around a symbol body
POWER_NAME_GAP = 2.5  # mm between a power symbol and its name
POWER_MAX_SIZE = 8.0  # mm
PIN_NUMBER_GAP = 2.0  # mm between a pin and its number
OTHER_SIDE_COST = 0.5  # mm added for a pin number on its unusual side
PIN_NAME_GAP = 1.5  # mm between a pin's inner end and its name
UNKNOWN_PREFIX_COST = REF_SEARCH  # "LM358" looks like a designator but is a value
OTHER_SYMBOL_COST = REF_SEARCH  # text drawn after a different symbol
LATER_FIELD_COST = 5.0  # where the designator is the first text drawn after its symbol
UNPAIRED_COST = 3 * REF_SEARCH + 1
CORNER_GAP = 0.1  # mm between lines that meet in a drawing

# A part value such as 100nF, 4.7uH, 10k or 0R, which is never a power net.
PART_VALUE = re.compile(r"^\d+([.,]\d+)?\s*[pnuμµmkKMG]?\s*(F|H|R|Ω|ohms?)?$")


def annotate(symbols: list[Symbol], scene: Scene, profile: Profile, runs: Runs | None) -> None:
    texts = _Texts(scene.fields)
    _name_power_symbols(symbols, texts, scene, profile, runs)
    if profile.power_names_in_labels:
        _name_power_from_labels(symbols, scene, profile)
    if profile.unnamed_ground:
        for symbol in filter(_could_be_power, symbols):
            # A part with a real pin is a component, such as a mounting hole.
            if not _has_real_pin(symbol, scene, profile) and _looks_like_ground(symbol, scene):
                symbol.power = profile.unnamed_ground
                symbol.anchors = _anchors(symbol, scene)
    _assign_refs(symbols, texts, runs, profile)
    _number_pins(symbols, scene, profile)
    _assign_values(symbols, texts, runs)


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
    for symbol in filter(_could_be_power, symbols):
        for _, i in texts.near(symbol.bbox, POWER_NAME_GAP):
            text = texts.texts[i]
            if not _is_power_name(text.text, profile):
                continue
            # The name is the first text drawn after the symbol, or else sits in line with it.
            if runs.first_text(symbol) == text.seq if runs else _in_line(symbol, text):
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
            if _is_power_name(text.text, profile) and _in_line(symbol, text):
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


def _is_power_name(text: str, profile: Profile) -> bool:
    # A designator nearby means a one-pin part, such as a test point.
    return (
        _is_net_name(text)
        and text not in profile.not_power_nets
        and not is_common_ref(text)
        and not PART_VALUE.match(text)
    )


def _has_real_pin(symbol: Symbol, scene: Scene, profile: Profile) -> bool:
    """A pin in the pin colour, or any pin where pins have no colour of their own."""
    if not profile.colors.get("pin"):
        return bool(symbol.pins)
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
        if len(lengths) >= 3 and shrinking and distinct:
            return True
    return False


def _anchors(symbol: Symbol, scene: Scene) -> list[Point]:
    """A power symbol connects at its pin, or else at a loose end of its drawing, or
    at the middle of its base when it is a lone triangle."""
    if symbol.pins:
        return [p.at for p in symbol.pins]
    shapes = (scene.shapes[i] for i in symbol.shapes)
    loose = [p for shape in shapes if not shape.closed for p in (shape.points[0], shape.points[-1])]
    base = _bare_triangle_base(symbol, scene)
    return loose or ([base] if base else [])


def _in_line(symbol: Symbol, text: Text) -> bool:
    """True if the text sits beyond the symbol along its pin axis, not beside it."""
    x0, y0, x1, y1 = symbol.bbox
    cx, cy = geometry.center(text.bbox)
    above_or_below = x0 - 0.5 <= cx <= x1 + 0.5 and not y0 < cy < y1
    left_or_right = y0 - 0.5 <= cy <= y1 + 0.5 and not x0 < cx < x1
    if not symbol.pins:
        return above_or_below or left_or_right
    return left_or_right if geometry.is_horizontal(symbol.pins[0].line) else above_or_below


def _assign_refs(symbols: list[Symbol], texts: _Texts, runs: Runs | None, profile: Profile) -> None:
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
            match = REFDES.match(text.text)
            if not match or _is_pin_name(symbol, text):
                continue
            cost = gap
            if match.group(1) not in COMMON_PREFIXES:
                cost += UNKNOWN_PREFIX_COST
            if runs and not runs.owns(symbol, text.seq):
                cost += OTHER_SYMBOL_COST
            elif runs and profile.designator_first and runs.first_text(symbol) != text.seq:
                cost += LATER_FIELD_COST
            candidates.append((cost, si, ti))
    candidates.sort()

    # One text per symbol, minimising total cost. Then symbols drawn in pieces
    # (diode arrays, relay coils) share the text of the piece that got it.
    taken, used = set(), set()
    for si, ti in _best_pairs(candidates):
        _set_ref(parts[si], texts.texts[ti].text)
        taken.add(si)
        used.add(ti)
    for cost, si, ti in candidates:
        if si in taken or ti not in used:
            continue
        if runs.owns(parts[si], texts.texts[ti].seq) if runs else cost < REF_SEARCH:
            _set_ref(parts[si], texts.texts[ti].text)
            taken.add(si)
    texts.used |= used


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


def _number_pins(symbols: list[Symbol], scene: Scene, profile: Profile) -> None:
    numbers = scene.pin_numbers
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
            pins[i].number = numbers[t].text
            named.add(i)
            used.add(t)

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


def _triangle_corners(symbol: Symbol, scene: Scene) -> list[Point]:
    """Corners of closed three-sided outlines, such as the body of a diode."""
    corners = []
    for i in symbol.shapes:
        shape = scene.shapes[i]
        unique = {(round(x, 2), round(y, 2)) for x, y in shape.points}
        if shape.closed and len(unique) == 3:
            corners += list(unique)
    return corners


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
    else:
        gap = far + OTHER_SIDE_COST
    return gap if -0.3 <= gap <= PIN_NUMBER_GAP else None


def _assign_values(symbols: list[Symbol], texts: _Texts, runs: Runs | None) -> None:
    """The value is the next text drawn after the designator, or else the nearest one."""
    for symbol in symbols:
        if not symbol.ref:
            continue
        options = [
            (text.seq if runs else gap, i)
            for gap, i in texts.near(symbol.bbox, REF_SEARCH / 2)
            if not _is_pin_name(symbol, text := texts.texts[i])
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


def _is_net_name(text: str) -> bool:
    return any(c.isalpha() for c in text)


def _is_pin_name(symbol: Symbol, text: Text) -> bool:
    """Pin names sit inside the body, next to the inner end of a pin, written along it."""
    if len(symbol.pins) <= 2 or not symbol.body:
        return False
    c = geometry.center(text.bbox)
    x0, y0, x1, y1 = symbol.body
    if not (x0 + 0.3 <= c[0] <= x1 - 0.3 and y0 + 0.3 <= c[1] <= y1 - 0.3):
        return False
    reach = PIN_NAME_GAP + max(text.bbox[2] - text.bbox[0], text.bbox[3] - text.bbox[1]) / 2
    vertical_text = round(text.angle) % 180 == 90
    return any(
        geometry.distance(c, pin.line[0]) <= reach
        and geometry.is_horizontal(pin.line) != vertical_text
        for pin in symbol.pins
    )
