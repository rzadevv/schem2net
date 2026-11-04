"""Stage 6, continued: attach texts to symbols.

Power symbols get their net name, parts get a reference designator and a
value, and pins get their numbers.
"""

from __future__ import annotations

import bisect
import functools
import heapq
import itertools
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from schem2net import designators, geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.primitives import BBox, Point, Text
from schem2net.profile import Profile
from schem2net.refdes import (
    COMMON_PREFIXES,
    PART_VALUE,
    REFDES,
    TWO_TERMINAL_PREFIXES,
    is_common_ref,
    split_ref,
)
from schem2net.scene import Scene, Shape, values_run

if TYPE_CHECKING:
    from schem2net.symbols import Pin, Runs, Symbol

REF_SEARCH = 10.0  # mm around a symbol body
POWER_NAME_GAP = 2.5  # mm between a power symbol and its name
FLAG_CLEAR = 0.5  # mm by which a flag's own name is plainly nearer than any other
ORDER_VOTES = 3  # flags that must show which side of its mark a name is drawn
ORDER_SHARE = 0.8  # of them, the share that must agree
POWER_MAX_SIZE = 8.0  # mm
PIN_NUMBER_GAP = 2.0  # mm between a pin and its number
MAX_OVERHANG = 1.0  # mm by which a pin number's middle may lie past the pin's end
MAX_VALUE_WORDS = 4  # a longer text beside a part is a note, not its value
OTHER_SIDE_COST = 0.5  # mm added for a pin number on its unusual side
PIN_NAME_GAP = 1.5  # mm between a pin's inner end and its name, unless the profile says
SIDE_BEARING = 0.15  # of the text size, the most a letter's ink may fall short of its box
INSIDE_BODY_COST = REF_SEARCH  # a designator inside a part's outline, where profiles say
UNKNOWN_PREFIX_COST = REF_SEARCH  # "LM358" looks like a designator but is a value
MANY_PINS_COST = REF_SEARCH  # "L298" by a part of many pins is its value, not an inductor
MANY_PINS = 4  # more pins than a resistor, capacitor or inductor has
OTHER_SYMBOL_COST = REF_SEARCH  # text drawn after a different symbol
LATER_FIELD_COST = 5.0  # where the designator is the first text drawn after its symbol
VALUE_FIRST_COST = REF_SEARCH  # "Z80" drawn right before "U1" is the value
UNLIKELY_COST = REF_SEARCH  # for a text the learned model is sure is no designator
SURE_DESIGNATOR = 0.9  # the model's certainty that admits a name of no usual form
UNUSUAL_FORM_COST = 1.0  # mm; a name of no usual form gives way at the same distance
WORD_FLOOR = 0.1  # the model's belief below which a word of no usual form names no part
AMONG_VALUES_COST = 2.5  # mm; "A20" drawn among values is likely one too
FUNCTION_NAME_GAP = 5.0  # mm from a part to a name such as I2C or PWR
LAYER_NEIGHBOURS = 6  # texts drawn either side of a name, among which other names are
UNPAIRED_COST = 3 * REF_SEARCH + 1
PIECE_GAP = 1.27  # mm between pieces of one drawn symbol; parts sit a grid step apart
CORNER_GAP = 0.1  # mm between lines that meet in a drawing
MIN_GROUND_BASE = 0.5  # mm; a ground triangle's base is a grid step or so wide
ROW_HEAD_REACH = 2.0  # pitches past a row's end pin within which its first number sits
MIN_ROW = 3  # pins in a row numbered from its head
# A row's numbers follow a progression, a + k * step, when this share of its pins do;
# the rest are then filled from it. Steps of two are the rows of a two-row header.
ROW_FIT = 0.8
ROW_STEPS = (1, -1, 2, -2)
ARROW_SIZE = 4.0  # mm; a transistor's arrowhead is smaller than this
BAR_REACH = 3.0  # mm from a transistor's base or gate pin to its bar
MEET = 0.15  # mm between lines that meet in a symbol's drawing

# A tolerance, voltage, power or current rating; "1A" may name a pad, "1.5A" does not.
RATING = re.compile(r"^\d+([./]\d+)?\s*(%|[mkuμµ]?[VW])$|^\d+[./]\d+\s*[muμµ]?A$")
PAD_COUNT = re.compile(r"\*\d+$")  # Eagle writes a pin on several pads as "A6*2"
# Pins labelled by these are known by a name, not by a pad number.
NAMED = ("name", "role")


def annotate(symbols: list[Symbol], scene: Scene, profile: Profile, runs: Runs | None) -> None:
    texts = _Texts(scene.fields)
    _name_power_symbols(symbols, texts, scene, profile, runs)
    if profile.power_names_in_labels:
        if profile.labels_follow_flags:
            _name_flags_by_labels_after(symbols, scene, profile)
        _name_power_from_labels(symbols, scene, profile, _could_be_power)
    elif profile.labels_on_wires:
        # Over a wire, a label may lie beside any small drawing, such as a piece of a part
        # read apart from it: only a flag or a ground sign takes it.
        def takes(symbol: Symbol) -> bool:
            return _could_be_power(symbol) and _is_flag_or_ground(symbol, scene)

        _name_power_from_labels(symbols, scene, profile, takes)
    if profile.unnamed_ground:
        named = {id(s): s.power for s in symbols if s.power}
        # Bars and other pinless bits of one sign, each beside the next.
        pieces = _pieces([s for s in symbols if not s.pins and (s.power or _could_be_power(s))])
        for symbol in filter(_could_be_power, symbols):
            # A part with a real pin is a component, such as a mounting hole.
            if not _has_real_pin(symbol, scene, profile) and _looks_like_ground(symbol, scene):
                # A piece drawn beside it, or further along its bits, may have taken its name.
                near = [s for s in symbols if geometry.bbox_gap(s.bbox, symbol.bbox) <= PIECE_GAP]
                along = [k for s in near for k in [id(s), *pieces.get(id(s), ())]]
                taken = [named[k] for k in along if k in named and k != id(symbol)]
                if taken:
                    symbol.power = taken[0]
                else:
                    symbol.power = _ground_name(symbol, scene, profile)
                    symbol.power_hidden = True
        if profile.labels_on_wires:
            _name_grounds_from_labels(symbols, scene, profile, pieces)
    # Drawn like a power symbol but joining nothing by name, as PWR_FLAG: named last, so
    # it takes no symbol another name or the usual ground's would.
    if profile.not_power_nets:
        _name_by_texts(symbols, texts, profile, runs, lambda t: t.text in profile.not_power_nets)
    # Where each power symbol connects; a flag may sit straight on a part's pin.
    wired = [end for wire in scene.wires for end in wire]
    ends = wired + [p.at for s in symbols if not s.power for p in s.pins]
    index = GridIndex()
    for k, end in enumerate(ends):
        index.add(k, (*end, *end))
    for symbol in symbols:
        if symbol.power:
            symbol.anchors = _anchors(symbol, scene, ends, len(wired), index)
    values = _values_by_order(scene, profile)
    likely = designators.likelihood(scene, symbols, runs, profile)
    ordered = _designators_by_order(symbols, scene, profile)
    named_by = _assign_refs(
        symbols, texts, runs, profile, values, _among_values(scene, profile), likely, ordered
    )
    _number_pins(symbols, scene, profile, {id(texts.texts[i]) for i in texts.used})
    _assign_values(symbols, texts, runs, profile.pin_name_gap, profile, named_by, values)


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
    if profile.drawn_by_part and not runs:
        _name_flags_by_order(symbols, texts, scene, profile)
    _name_by_texts(symbols, texts, profile, runs, lambda text: _is_power_name(text, profile))


def _name_by_texts(
    symbols: list[Symbol],
    texts: _Texts,
    profile: Profile,
    runs: Runs | None,
    names: Callable[[Text], bool],
) -> None:
    """Each symbol that may be a power symbol named by a text `names` accepts beside it:
    a name in line with the symbol first; only then one that overhangs it. Each name
    goes to the nearest symbol it may name: a printer may draw two in one path."""
    reach = profile.power_name_gap or POWER_NAME_GAP
    for loose in (False, True):
        options = []
        for k, symbol in enumerate(symbols):
            if not _could_be_power(symbol):
                continue
            for gap, i in texts.near(symbol.bbox, reach):
                text = texts.texts[i]
                if not names(text):
                    continue
                # The first text drawn after the symbol, or else one in line with it.
                if runs.first_text(symbol) == text.seq if runs else _in_line(symbol, text, loose):
                    options.append((gap, k, i))
        for _, k, i in sorted(options):
            if not symbols[k].power and i not in texts.used:
                symbols[k].power = texts.texts[i].text
                texts.used.add(i)


def _name_power_from_labels(
    symbols: list[Symbol], scene: Scene, profile: Profile, takes: Callable[[Symbol], bool]
) -> None:
    """A power symbol's name may have been read as a net label: some generators write
    it in the net label colour, and where labels are names laid along wires, a name set
    past its symbol over a wire passing there reads as one. Each symbol that `takes`
    a name takes the first such label in line with it."""
    for symbol, name in _labels_in_line(symbols, scene, profile, takes):
        symbol.power = name


def _name_flags_by_labels_after(symbols: list[Symbol], scene: Scene, profile: Profile) -> None:
    """Where each flag's name is drawn right after it, in the label colour, as an off-page
    connector's is in OrCAD, the label drawn right after a flag and in line with it names
    it, though it may sit farther off than a name found by distance alone."""
    seqs = sorted([t.seq for t in scene.fields] + [lb.seq for lb in scene.labels])
    after = {lb.seq: lb for lb in scene.labels if lb.kind == "local" and not lb.outline}
    claimed = set()
    for symbol in filter(_could_be_power, symbols):
        k = bisect.bisect_right(seqs, max(scene.shapes[i].seq for i in symbol.shapes))
        label = after.get(seqs[k]) if k < len(seqs) else None
        if label is None or id(label) in claimed:
            continue
        text = Text(0, label.text, label.bbox, 0.0, label.angle, None)
        near = geometry.bbox_gap(symbol.bbox, label.bbox) <= REF_SEARCH
        if near and _is_power_name(text, profile) and _in_line(symbol, text):
            symbol.power = label.text
            claimed.add(id(label))
    scene.labels = [label for label in scene.labels if id(label) not in claimed]


def _name_grounds_from_labels(
    symbols: list[Symbol], scene: Scene, profile: Profile, pieces: dict[int, list[int]]
) -> None:
    """A ground sign given the usual name may show its own past it, read as a label on a
    wire passing there: the name is the sign's. A sign drawn in pieces, a stem and bars
    apart, is judged and named whole."""
    loose = [s for s in symbols if not s.pins and (s.power_hidden or _could_be_power(s))]
    signs: dict[int, tuple[Symbol, list[Symbol]]] = {}
    for symbol in symbols:
        if not symbol.power_hidden or not symbol.pins:
            continue  # the pieces of a sign are found from its stem
        near = [s for s in loose if geometry.bbox_gap(s.bbox, symbol.bbox) <= PIECE_GAP]
        ids = {k for s in near for k in [id(s), *pieces.get(id(s), ())]}
        members = [symbol, *(s for s in loose if id(s) in ids)]
        shapes = sorted({i for s in members for i in s.shapes})
        box = functools.reduce(geometry.union_bbox, (s.bbox for s in members))
        whole = replace(symbol, shapes=shapes, bbox=box)
        if _is_flag_or_ground(whole, scene):
            signs[id(whole)] = whole, members
    wholes = [whole for whole, _ in signs.values()]
    for whole, name in _labels_in_line(wholes, scene, profile, lambda _: True):
        for member in signs[id(whole)][1]:
            if member.power_hidden:
                member.power, member.power_hidden = name, False


def _labels_in_line(
    symbols: list[Symbol], scene: Scene, profile: Profile, takes: Callable[[Symbol], bool]
) -> list[tuple[Symbol, str]]:
    """Each symbol that `takes` a name, with the first unclaimed outline-less net label
    that may name it, in line with it; the labels taken are no labels any more."""
    local = [label for label in scene.labels if label.kind == "local" and not label.outline]
    pool = _Texts([Text(i, lb.text, lb.bbox, 0.0, lb.angle, None) for i, lb in enumerate(local)])
    found = []
    for symbol in filter(takes, symbols):
        for _, i in pool.near(symbol.bbox, profile.label_name_gap or POWER_NAME_GAP):
            text = pool.texts[i]
            if _is_power_name(text, profile) and _in_line(symbol, text):
                found.append((symbol, text.text))
                pool.used.add(i)
                break
    claimed = {id(local[i]) for i in pool.used}
    scene.labels = [label for label in scene.labels if id(label) not in claimed]
    return found


def _is_flag_or_ground(symbol: Symbol, scene: Scene) -> bool:
    """A pinless closed outline, or a ground sign of more than a bar across a stem, which
    two lines of any small drawing may make."""
    if not symbol.pins and any(scene.shapes[i].closed for i in symbol.shapes):
        return True
    return _looks_like_ground(symbol, scene) and not _is_tee(symbol, scene)


def _name_flags_by_order(
    symbols: list[Symbol], texts: _Texts, scene: Scene, profile: Profile
) -> None:
    """Drawn one at a time, a flag's name comes right before its mark or right after
    it: EasyEDA draws a net label's text and then the cross where it meets the wire,
    and another export the other way round. The cross sits by the text's corner, as
    near the next label's text as its own, so the order names it. Which way round the
    page draws is told by the flags whose name is plain by distance."""
    by_seq = {t.seq: i for i, t in enumerate(texts.texts)}
    flags = []
    for symbol in filter(_could_be_power, symbols):
        seqs = [scene.shapes[k].seq for k in symbol.shapes]
        sides = {"before": by_seq.get(min(seqs) - 1), "after": by_seq.get(max(seqs) + 1)}
        sides = {
            side: i
            for side, i in sides.items()
            if i is not None
            and _is_power_name(texts.texts[i], profile)
            and geometry.bbox_gap(symbol.bbox, texts.texts[i].bbox) <= POWER_NAME_GAP
        }
        if sides:
            flags.append((symbol, sides))
    votes = Counter()
    for symbol, sides in flags:
        gaps = sorted(
            (geometry.bbox_gap(symbol.bbox, texts.texts[i].bbox), i)
            for _, i in texts.near(symbol.bbox, POWER_NAME_GAP)
            if _is_power_name(texts.texts[i], profile)
        )
        if len(gaps) == 1 or (len(gaps) > 1 and gaps[1][0] > 2 * gaps[0][0] + FLAG_CLEAR):
            for side, i in sides.items():
                votes[side] += i == gaps[0][1]
    side, count = max(votes.items(), key=lambda kv: kv[1], default=("", 0))
    if count < ORDER_VOTES or count < ORDER_SHARE * sum(votes.values()):
        return
    for symbol, sides in flags:
        i = sides.get(side)
        if i is not None and i not in texts.used:
            symbol.power = texts.texts[i].text
            texts.used.add(i)


def _pieces(symbols: list[Symbol]) -> dict[int, list[int]]:
    """By symbol id, the ids of the symbols it is drawn in pieces with: a chain of small
    symbols each beside the next, as the bars of a ground sign under its stem are."""
    joined = UnionFind()
    index = GridIndex()
    for k, symbol in enumerate(symbols):
        joined.find(k)
        index.add(k, symbol.bbox)
    for k, symbol in enumerate(symbols):
        x0, y0, x1, y1 = symbol.bbox
        near = (x0 - PIECE_GAP, y0 - PIECE_GAP, x1 + PIECE_GAP, y1 + PIECE_GAP)
        for j in index.within(near):
            if geometry.bbox_gap(symbol.bbox, symbols[j].bbox) <= PIECE_GAP:
                joined.union(k, j)
    return {
        id(symbols[k]): [id(symbols[j]) for j in group if j != k]
        for group in joined.groups().values()
        for k in group
    }


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


def _ground_name(symbol: Symbol, scene: Scene, profile: Profile) -> str | None:
    """The net of a ground sign whose name is hidden: the generator's usual ground, or
    the name its library gives that sign, where it names signs apart."""
    signs = profile.ground_signs
    if "triangle" in signs and (
        _has_triangle(symbol, scene) or _bare_triangle_base(symbol, scene) is not None
    ):
        return signs["triangle"]
    if "rake" in signs and _is_rake(symbol, scene):
        return signs["rake"]
    return profile.unnamed_ground


def _looks_like_ground(symbol: Symbol, scene: Scene) -> bool:
    """The ground sign: shrinking parallel bars, a triangle pointing away from the stem
    or the wire, a chassis rake, or a single bar across the stem with its name hidden."""
    return (
        _has_bars(symbol, scene)
        or _has_triangle(symbol, scene)
        or _is_rake(symbol, scene)
        or _is_tee(symbol, scene)
        or _bare_triangle_base(symbol, scene) is not None
    )


def _is_rake(symbol: Symbol, scene: Scene) -> bool:
    """The chassis sign: a bar with short parallel strokes slanting from one side of it."""
    segs = [seg for i in symbol.shapes for seg in geometry.segments(scene.shapes[i].points)]
    bar = max(segs, key=lambda seg: geometry.distance(*seg), default=None)
    if bar is None or not geometry.is_axis_aligned(bar, 0.01):
        return False
    along = geometry.unit(*bar)
    normal = (-along[1], along[0])
    strokes, sides = [], set()
    for seg in segs:
        if seg is bar or geometry.is_axis_aligned(seg, 0.01):
            continue
        on, off = sorted(seg, key=lambda p: geometry.distance_to_segment(p, bar))
        if geometry.distance_to_segment(on, bar) > CORNER_GAP:
            return False
        if geometry.distance(*seg) >= geometry.distance(*bar):
            return False
        strokes.append(geometry.unit(on, off))
        sides.add((off[0] - on[0]) * normal[0] + (off[1] - on[1]) * normal[1] > 0)
    parallel = all(abs(a[0] * b[0] + a[1] * b[1]) > 0.99 for a in strokes for b in strokes)
    return len(strokes) >= 2 and len(sides) == 1 and parallel


def _bare_triangle_base(symbol: Symbol, scene: Scene) -> Point | None:
    """The middle of the base of a symbol drawn as a lone triangle, base square to the
    page: one closed outline, or three lines meeting at three corners."""
    segs = [seg for i in symbol.shapes for seg in geometry.segments(scene.shapes[i].points)]
    corners = list(dict.fromkeys((round(x, 2), round(y, 2)) for seg in segs for x, y in seg))
    if len(segs) != 3 or len(corners) != 3:
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
    segs: list[Segment | None] = list(segs)
    merged = True
    while merged:
        merged = False
        ends = GridIndex(cell=1.0)
        for k, seg in enumerate(segs):
            for p in seg:
                ends.add(k, (p[0], p[1], p[0], p[1]))
        for i in range(len(segs)):
            if segs[i] is None:
                continue  # joined to an earlier one in this pass
            for j in sorted(ends.near(segs[i][0], CORNER_GAP) | ends.near(segs[i][1], CORNER_GAP)):
                if j <= i or segs[j] is None:
                    continue
                joined = _straight_on(segs[i], segs[j])
                if joined:
                    segs[i], segs[j], merged = joined, None, True
        segs = [seg for seg in segs if seg is not None]
    return segs


def _straight_on(a: Segment, b: Segment) -> Segment | None:
    """The two as one segment, where b carries straight on from an end of a."""
    for p, q in ((a[0], a[1]), (a[1], a[0])):
        for r, t in ((b[0], b[1]), (b[1], b[0])):
            if geometry.distance(p, r) > CORNER_GAP:
                continue
            u, v = geometry.unit(p, q), geometry.unit(r, t)
            if u[0] * v[0] + u[1] * v[1] < -0.999:  # straight on through p
                return (q, t)
    return None


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


def _anchors(
    symbol: Symbol, scene: Scene, ends: list[Point], wired: int, index: GridIndex
) -> list[Point]:
    """A power symbol connects at its pin, or else at a loose end of its drawing, or
    at the middle of its base when it is a lone triangle; a port flag, a closed outline,
    at the corner its wire ends on, or the corner set on a pin's tip. `ends` are the wire
    ends, the first `wired`, then the pin tips, in `index`."""
    if symbol.pins:
        return [p.at for p in symbol.pins]
    shapes = [scene.shapes[i] for i in symbol.shapes]
    # A wire ending on it, as on the middle of a ground's top bar or in the mouth of an
    # off-page arrow: at one point, for a symbol with wires at two is no power symbol.
    x0, y0, x1, y1 = box = geometry.grown(symbol.bbox, CORNER_GAP)
    landed = [
        end
        for end in (ends[k] for k in sorted(index.within(box)) if k < wired)
        if x0 <= end[0] <= x1 and y0 <= end[1] <= y1
    ]
    if landed and all(geometry.distance(end, landed[0]) <= CORNER_GAP for end in landed):
        return landed[:1]
    loose = [p for shape in shapes if not shape.closed for p in (shape.points[0], shape.points[-1])]
    base = _bare_triangle_base(symbol, scene)
    if loose or base:
        return loose or [base]
    corners = {p for shape in shapes for p in shape.points}
    return [
        c
        for c in corners
        if any(geometry.distance(c, ends[k]) <= CORNER_GAP for k in index.near(c, CORNER_GAP))
    ]


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
    among_values: set[int],
    likely: dict[int, float] | None = None,
    ordered: dict | None = None,
) -> dict[int, int]:
    """Returns, by part id, the index of the text that names it.

    `values` holds the ids of texts drawn where a value goes, `among_values` those
    of texts drawn among values, and `likely`, by id, how likely each text is to be a
    designator, where a model was learned for the generator."""
    parts = [s for s in symbols if s.pins and not s.power]
    first_reach = profile.designator_first and runs
    candidates = []

    def _own_ref(symbol: Symbol) -> bool:
        return any(
            split_ref(texts.texts[ti].text) and runs.owns(symbol, texts.texts[ti].seq)
            for _, ti in texts.near(symbol.body or symbol.bbox, 3 * REF_SEARCH)
        )

    def _usual_nearby(symbol: Symbol) -> bool:
        """A designator of the usual form near the part that the model finds likely."""
        return any(
            split_ref(texts.texts[ti].text)
            and likely.get(id(texts.texts[ti]), 1.0) >= 0.5
            and not is_pin_name(symbol, texts.texts[ti], profile.pin_name_gap)
            for _, ti in texts.near(symbol.body or symbol.bbox, REF_SEARCH)
        )

    for si, symbol in enumerate(parts):
        # Where the designator is drawn first, that text may sit further away.
        reach = 3 * REF_SEARCH if first_reach else REF_SEARCH
        for gap, ti in texts.near(symbol.body or symbol.bbox, reach):
            if gap > REF_SEARCH and texts.texts[ti].seq != runs.first_text(symbol):
                continue
            text = texts.texts[ti]
            if profile.colors.get("designator") and not profile.is_("designator", text.color):
                continue  # where designators have a colour of their own, only that
            if is_pin_name(symbol, text, profile.pin_name_gap):
                continue
            match = split_ref(text.text)
            # Where the designator is drawn first, the first text after a part names it,
            # whatever its form: GPIO1-1, USB-Serial/JTAG1.
            # Clear of the part: a text on it is drawing, such as a connector's caption.
            # And only where the part's own texts hold no usual designator: a unit with
            # its own reference may draw a pin name such as V+ first.
            first = first_reach and runs.first_text(symbol) == text.seq and gap > 0
            p = likely.get(id(text)) if likely else None
            # A name of no usual form the model is sure of, for a part with no likely
            # designator of the usual form beside it: LCD_CON, not a net name by U1.
            surely = p is not None and p >= SURE_DESIGNATOR and gap > 0
            surely = surely and not match and not _usual_nearby(symbol)
            # Where each part is drawn right after its designator, that text names it
            # whatever its form: MOUSE, KEYBOARD.
            first = first or (ordered or {}).get(id(symbol)) is text
            # Any other word the model gives some chance competes too, at the cost of its
            # doubt: LCD_CON beside its connector, against LCD_D1, a net name there.
            weighed = p is not None and p >= WORD_FLOOR and gap > 0
            if not match and not (
                _name_like(text.text)
                and (surely or weighed or (first and not (runs and _own_ref(symbol))))
            ):
                continue
            cost = gap
            prefix = match.group(1).rstrip("$") if match else None
            if p is not None:  # the model weighs what the text says, and how it sits
                # Only its doubt counts: certain designators keep the distances they have.
                cost += UNLIKELY_COST * max(0.0, 1 - 2 * p)
                if not match:  # at one distance, the usual form first
                    cost += UNUSUAL_FORM_COST
            elif prefix not in COMMON_PREFIXES:  # a pin name may be drawn first too
                cost += UNKNOWN_PREFIX_COST
                if not match:  # never ahead of a usual designator at the same distance
                    cost += LATER_FIELD_COST
            if prefix in TWO_TERMINAL_PREFIXES and len(symbol.pins) > MANY_PINS:
                cost += MANY_PINS_COST
            if profile.designators_outside and _belongs_to_a_pin(symbol, text, profile, texts):
                cost += INSIDE_BODY_COST
            if id(text) in values:
                cost += VALUE_FIRST_COST
            if id(text) in among_values:
                cost += AMONG_VALUES_COST
            if runs and not runs.owns(symbol, text.seq):
                cost += OTHER_SYMBOL_COST
            elif runs and profile.designator_first and runs.first_text(symbol) != text.seq:
                cost += LATER_FIELD_COST
            candidates.append((cost, si, ti))
    candidates.sort()

    # One text per symbol, minimising total cost. Then symbols drawn in pieces
    # (diode arrays, relay coils) share the text of the piece that got it.
    taken, used = set(), {}
    for si, ti in geometry.best_pairs(candidates, UNPAIRED_COST):
        _set_ref(parts[si], texts.texts[ti].text)
        taken.add(si)
        used[ti] = si
    for _, si, ti in candidates:
        if si in taken or ti not in used:
            continue
        # Body pieces can share a reference; separate parts touching through their
        # pin tips cannot. Include pins only where a piece has no body graphics.
        other = parts[used[ti]]
        beside = (
            geometry.bbox_gap(parts[si].body or parts[si].bbox, other.body or other.bbox)
            <= PIECE_GAP
        )
        if runs.owns(parts[si], texts.texts[ti].seq) if runs else beside:
            _set_ref(parts[si], texts.texts[ti].text)
            taken.add(si)
    texts.used |= set(used)
    if profile.names_by_layer:
        unnamed = [p for k, p in enumerate(parts) if k not in taken]
        _name_by_function(unnamed, texts, profile, among_values, likely or {})
    return {id(parts[si]): ti for ti, si in used.items()}


def _name_by_function(
    parts: list[Symbol],
    texts: _Texts,
    profile: Profile,
    among_values: set[int],
    likely: dict[int, float],
) -> None:
    """Eagle takes any name for a part, and designers name jumpers and connectors by
    what they do: I2C, PWR, LCD_CON. A part left without a designator takes an unused
    word beside it that is not one of its pin names, a value, a number or a note: the
    one the designator model finds likeliest by an order of magnitude, as HDMI is against
    its connector's part number HDMI-SWM-19, and the nearest of those alike."""
    options = []
    for si, symbol in enumerate(parts):
        if len(symbol.pins) < 2:
            continue
        for gap, ti in texts.near(symbol.body or symbol.bbox, FUNCTION_NAME_GAP):
            text = texts.texts[ti]
            word = text.text
            if (
                not _name_like(word)
                or word[:1].isdigit()
                or id(text) in among_values
                or _within_outline(symbol, text)
                or is_pin_name(symbol, text, profile.pin_name_gap)
            ):
                continue
            odds = round(math.log10(likely.get(id(text), 0.0) + 1e-12))
            options.append((-odds, gap, si, ti))
    named = set()
    for _, _, si, ti in sorted(options):
        if si in named or ti in texts.used:
            continue
        parts[si].ref = texts.texts[ti].text
        named.add(si)
        texts.used.add(ti)


def _designators_by_order(symbols: list[Symbol], scene: Scene, profile: Profile) -> dict:
    """By part id, the text in the designators' colour drawn right before the part's
    drawing, with nothing drawn between, where the generator draws each part's value,
    then its designator, then the part."""
    if not profile.value_before_designator:
        return {}
    drawn = sorted(s.seq for s in scene.shapes)
    named = sorted(
        (t.seq, k) for k, t in enumerate(scene.fields) if profile.is_("designator", t.color)
    )
    seqs = [seq for seq, _ in named]
    out = {}
    for part in symbols:
        if not part.pins or part.power or not part.shapes:
            continue
        start = min(scene.shapes[i].seq for i in part.shapes)
        k = bisect.bisect_left(seqs, start) - 1
        if k < 0:
            continue
        seq, i = named[k]
        j = bisect.bisect_right(drawn, seq)
        if j < len(drawn) and drawn[j] < start:
            continue  # other drawing came between
        out[id(part)] = scene.fields[i]
    return out


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


def _among_values(scene: Scene, profile: Profile) -> set[int]:
    """Where all part names are drawn together, and all values, as Eagle draws layer by
    layer: ids of texts that look like designators but are drawn among values, as A20
    is among 10k and 3.3V."""
    if not profile.names_by_layer:
        return set()
    run = values_run(scene.fields, LAYER_NEIGHBOURS)
    return {id(t) for t in scene.fields if id(t) in run and is_common_ref(t.text)}


def _set_ref(symbol: Symbol, text: str) -> None:
    match = split_ref(text)
    if not match:  # a name of the designer's own, taken whole
        symbol.ref, symbol.unit = text, None
        return
    prefix, number, unit = match.groups()
    symbol.ref = prefix + number
    symbol.unit = unit or None


def _name_like(word: str) -> bool:
    """One word with a letter in it that is not a value or a lone letter, as a pin
    name such as K is: it may name a part."""
    return (
        len(word) > 1
        and any(c.isalpha() for c in word)
        and not any(c.isspace() for c in word)
        and not PART_VALUE.match(word)
    )


def whole_names(pages: list[list[Symbol]]) -> None:
    """A designator of no usual prefix with a unit after its number is a name, such as
    I2C or GPIO1-1, unless the document shows it in other units too, as CM1A and CM1B. Units
    of one part share no pads, so where every unit shows the same pin numbers, as R11A
    and R11B do, each is a part of its own."""
    units: dict[str, dict[str, set[str]]] = {}
    for symbols in pages:
        for s in symbols:
            if s.ref and s.unit:
                numbers = units.setdefault(s.ref, {}).setdefault(s.unit, set())
                numbers |= {p.number for p in s.pins if p.number}
    for symbols in pages:
        for s in symbols:
            if not (s.ref and s.unit):
                continue
            drawn = list(units[s.ref].values())
            if len(drawn) > 1:
                if drawn[0] and all(numbers == drawn[0] for numbers in drawn):
                    s.ref, s.unit = s.ref + s.unit, None
                continue
            match = REFDES.match(s.ref)
            if match and match.group(1).rstrip("$") not in COMMON_PREFIXES:
                s.ref, s.unit = s.ref + s.unit, None


def _number_pins(symbols: list[Symbol], scene: Scene, profile: Profile, taken: set[int]) -> None:
    """Pin numbers from the texts beside pins, leaving out texts already taken as
    designators or net names (`taken` holds their ids)."""
    texts = [t for t in scene.pin_numbers if id(t) not in taken and not _is_value(t.text)]
    # Where pads are always numbered, a sign or a word by a pin is its name.
    numbered = not profile.pin_numbers_have_digits
    numbers = [t for t in texts if numbered or any(c.isdigit() for c in t.text)]
    words = [t for t in texts if not (numbered or any(c.isdigit() for c in t.text))]
    owned = [(p, s) for s in symbols if s.ref for p in s.pins]
    pins = [p for p, _ in owned]
    index = GridIndex()
    for i, pin in enumerate(pins):
        index.add(i, geometry.bbox_of(pin.line))

    options = []
    for t, text in enumerate(numbers):
        vertical_text = round(text.angle) % 180 == 90
        for i in index.near(geometry.center(text.bbox), PIN_NUMBER_GAP + 1):
            if _inside_body(owned[i][1], text):
                continue  # a pin name
            gap = _number_gap(
                text.bbox, pins[i].line, profile.pin_numbers_above, profile.pin_numbers_overhang
            )
            if gap is not None:
                # A number usually reads along its pin; one turned across it costs more.
                across = geometry.is_horizontal(pins[i].line) == vertical_text
                options.append((gap + OTHER_SIDE_COST * across, i, t))

    # Each number names one pin and each pin has one number: the pairing of least total
    # gap, so a number between two pins goes where it leaves no other unpaired.
    named, used = set(), set()
    for i, t in geometry.best_pairs(options, UNPAIRED_COST):
        pins[i].number = PAD_COUNT.sub("", numbers[t].text)  # "A6*2": pin A6, two pads
        pins[i].how = "read"
        named.add(i)
        used.add(t)

    # A part that shows pad numbers shows them on its pins alike: a number by one pin
    # only of a two-pin part is its value, as 33 printed over a resistor's end is.
    count: dict[str, list[int]] = {}
    for i, (_, symbol) in enumerate(owned):
        count.setdefault(symbol.ref, []).append(i)
    for mine in count.values():
        read = [i for i in mine if i in named]
        if len(mine) == 2 and len(read) == 1:
            pins[read[0]].number = pins[read[0]].how = None
            named.discard(read[0])

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
            if profile.diode_pin_names:  # pads named for the cathode and the anode
                cathode, anode = order[::-1] if profile.diode_pin_one_is_anode else order
                cathode.number, anode.number = profile.diode_pin_names
                cathode.how = anode.how = "pad names"
                continue
        else:
            down = -1 if profile.hidden_pin_one_at_bottom else 1
            order = sorted(part_pins, key=lambda p: (down * p.at[1], p.at[0]))
        for number, pin in enumerate(order, 1):
            pin.number = str(number)
            pin.how = "polarity" if len(part_pins) == 2 and tips else "position"

    unused = [t for k, t in enumerate(numbers) if k not in used] + words
    # Texts in a colour both roles share are in both lists; each names one pin at most.
    seen = {id(t) for t in unused}
    _name_pins(
        symbols, unused + [t for t in scene.fields if id(t) not in seen], profile.pin_name_gap
    )

    # Last, a transistor with neither numbers nor names shown: its pins by role. A
    # potentiometer or a three-way jumper has two ends facing apart and a wiper or
    # common pad square to them, which is pin 2; its ends count as two-pin parts do.
    down = -1 if profile.hidden_pin_one_at_bottom else 1
    for parts in by_ref.values():
        part_pins = [p for s in parts for p in s.pins]
        if any(p.number for p in part_pins):
            continue
        roles = _transistor_roles(parts, scene)
        how = "role"
        package = _package(parts[0].value, profile.pin_roles)
        if roles and package:  # a package whose pads the profile knows by role
            roles = [(pin, package[role]) for pin, role in roles if role in package]
            how = "package"
        middle = _middle_pin(part_pins) if not roles else None
        own = {p.shape for p in part_pins}
        body = [scene.shapes[i] for s in parts for i in s.shapes if i not in own]
        lines = [s for s in body if len(s.points) == 2]
        pads = [s for s in body if s.filled and s.closed]
        if middle and not _leads_to_bar(middle, lines, pads):  # a transistor's is its control
            ends = sorted(
                (p for p in part_pins if p is not middle), key=lambda p: (down * p.at[1], p.at[0])
            )
            roles = [(ends[0], "1"), (middle, "2"), (ends[1], "3")]
            how = "position"
            # A solder jumper's ends lie in pads alike: which is 1 depends on how it was
            # turned. A wrong guess joins nets wrongly, so only the common pad is named.
            if all(_in_any(p.line[0], pads) for p in ends):
                roles = [(middle, "2")]
        for pin, role in roles:
            pin.number = role
            pin.how = how


def _package(value: str | None, packages: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """The pads by role of the first package named in a part's value, if any."""
    value = (value or "").casefold()
    return next((pads for name, pads in packages.items() if name.casefold() in value), None)


def names_apart(symbols: list[Symbol]) -> None:
    """A pin known by the name drawn beside it, or by a transistor's role, shows no pad
    number: the name is kept as its name and its number left unknown, for a netlist
    that a board is read with must not give it a pad that may not exist."""
    for symbol in symbols:
        for pin in symbol.pins:
            if pin.how in NAMED:
                pin.name, pin.number, pin.how = pin.number, None, None


def _middle_pin(pins: list[Pin]) -> Pin | None:
    """Of three pins, the one square to the other two, which face apart on one axis."""
    if len(pins) != 3:
        return None
    for k, middle in enumerate(pins):
        a, b = (p for j, p in enumerate(pins) if j != k)
        u, v, w = (geometry.unit(*p.line) for p in (middle, a, b))
        apart = v[0] * w[0] + v[1] * w[1] < -0.99
        on_axis = abs(v[0] * (b.at[1] - a.at[1]) - v[1] * (b.at[0] - a.at[0])) < 0.1
        if apart and on_axis and abs(u[0] * v[0] + u[1] * v[1]) < 0.1:
            return middle
    return None


def _transistor_roles(parts: list[Symbol], scene: Scene) -> list[tuple[Pin, str]]:
    """Names for the pins of a transistor drawn without numbers. The base or gate is
    the pin square to the other two, leading to a bar; the emitter or
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
        if not _leads_to_bar(control, lines, [s for s in body if s.filled and s.closed]):
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
        # A bipolar transistor's emitter and collector leave its base bar on slants. A
        # MOSFET has slants too, in its arrowhead and body diode, but none on its gate.
        bars = _bars_ahead(control, lines, [s for s in body if s.filled and s.closed])
        slants = any(
            not geometry.is_axis_aligned(tuple(s.points), 0.01)
            and any(geometry.distance_to_segment(p, bar) <= 0.1 for p in s.points for bar in bars)
            for s in lines
        )
        names = ("B", "E", "C") if slants else ("G", "S", "D")
        return list(zip((control, emitter, other), names, strict=True))
    return []


def _leads_to_bar(pin: Pin, lines: list[Shape], pads: list[Shape]) -> bool:
    """Carried on inwards, perhaps along a lead, the pin meets a bar square to it, as a
    transistor's base or gate does, in its middle or at its end."""
    return bool(_bars_ahead(pin, lines, pads))


def _bars_ahead(pin: Pin, lines: list[Shape], pads: list[Shape]) -> list[tuple[Point, ...]]:
    """The bars square to the pin that it meets when carried on inwards."""
    (x, y), (dx, dy) = pin.line[0], geometry.unit(pin.line[1], pin.line[0])
    ahead = [(x + dx * t / 10, y + dy * t / 10) for t in range(int(BAR_REACH * 10) + 1)]
    bars = [tuple(s.points) for s in lines if abs(_cos(s.points, pin.line)) < 0.1]
    # The edge of a filled pad, drawn over its outline, is no bar.
    edges = [seg for s in pads for seg in geometry.segments(s.points)]
    bars = [b for b in bars if not all(_on_any(p, edges) for p in b)]
    # Nor is the bridge of a solder jumper, which runs from one pad into another.
    bars = [b for b in bars if not _bridges(b, pads)]
    return [bar for bar in bars if any(geometry.distance_to_segment(q, bar) <= 0.1 for q in ahead)]


def _in_any(p: Point, pads: list[Shape]) -> bool:
    return any(geometry.in_polygon(p, s.points) for s in pads)


def _bridges(line: tuple[Point, ...], pads: list[Shape]) -> bool:
    """Whether a line's two ends lie in two different pads."""
    ends = [{k for k, s in enumerate(pads) if geometry.in_polygon(p, s.points)} for p in line]
    return all(ends) and len(ends[0] | ends[1]) >= 2 and ends[0] != ends[1]


def _on_any(p: Point, segs: list[Segment]) -> bool:
    return any(geometry.distance_to_segment(p, seg) <= MEET for seg in segs)


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
            if len(numbered) >= 2:
                _fill_row(row, symbol, numbers, used)
                continue
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
                pin.how = "row"
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


def _row_fit(row: list[Pin]) -> tuple[int, int, int] | None:
    """The progression a + k * step most of a row's numbers follow, as (a, step, how
    many follow it), tried through each pair of numbered pins; None for no pair."""
    known = [(k, int(p.number)) for k, p in enumerate(row) if p.number and p.number.isdigit()]
    best = None
    for (i, x), (j, y) in itertools.combinations(known, 2):
        step, off = divmod(y - x, j - i)
        if off or step not in ROW_STEPS:
            continue
        a = x - step * i
        fits = sum(n == a + step * k for k, n in known)
        if best is None or fits > best[2]:
            best = (a, step, fits)
    return best


def _fill_row(row: list[Pin], symbol: Symbol, numbers: list[Text], used: set[int]) -> None:
    """Number the pins of a row whose numbers mostly follow a progression: a pin read with
    none takes its place in it, and one read otherwise takes it where an unused text of
    that number lies beside it."""
    fit = _row_fit(row)
    if fit is None or fit[2] < MIN_ROW or fit[2] < ROW_FIT * len(row):
        return
    a, step, _ = fit
    taken = {p.number for p in symbol.pins if p.number}
    for k, pin in enumerate(row):
        want = str(a + step * k)
        if pin.number == want or a + step * k < 1 or want in taken:
            continue
        if pin.number is None:
            pin.number, pin.how = want, "row"
            taken.add(want)
            continue
        beside = [
            t
            for t, text in enumerate(numbers)
            if t not in used
            and text.text == want
            and geometry.distance_to_segment(geometry.center(text.bbox), pin.line) <= PIN_NUMBER_GAP
        ]
        if beside:
            taken.discard(pin.number)
            pin.number = want
            taken.add(want)
            used.add(beside[0])


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
    index = GridIndex()
    for t, text in enumerate(texts):
        index.add(t, text.bbox)
    reach = name_gap + max((_size(t) for t in texts), default=1.0) + 1.0
    options = []
    for symbol in symbols:
        unnamed = [p for p in symbol.pins if p.number is None]
        if not symbol.ref or not unnamed:
            continue
        ends = geometry.bbox_of([p.line[0] for p in symbol.pins])
        near = index.within(geometry.grown(ends, reach))
        for t in sorted(near):
            text = texts[t]
            if not is_pin_name(symbol, text, name_gap):
                continue
            c = geometry.center(text.bbox)
            for pin in symbol.pins:
                inward = geometry.unit(pin.line[1], pin.line[0])
                ahead = (c[0] - pin.line[0][0]) * inward[0] + (c[1] - pin.line[0][1]) * inward[1]
                gap = geometry.distance(c, pin.line[0])
                if ahead > 0 and gap <= name_gap + max(_size(text), 1.0):
                    options.append((gap, t, id(pin), pin))
    taken, named = set(), set()
    for _, t, key, pin in sorted(options, key=lambda o: o[0]):
        if t not in taken and key not in named:
            # A numbered pin still owns its printed name. Reserving it prevents
            # an unnumbered neighbour from taking that name instead of its own.
            if pin.number is None:
                pin.number = texts[t].text
                pin.how = "name"
            taken.add(t)
            named.add(key)


def _size(text: Text) -> float:
    return max(text.bbox[2] - text.bbox[0], text.bbox[3] - text.bbox[1])


def _triangle_corners(symbol: Symbol, scene: Scene) -> list[Point]:
    """Corners of closed three-sided outlines, such as the body of a diode, or of three
    lines that meet end to end, as a printer may draw one."""
    corners = []
    for i in symbol.shapes:
        shape = scene.shapes[i]
        unique = {(round(x, 2), round(y, 2)) for x, y in shape.points}
        if shape.closed and len(unique) == 3:
            corners += list(unique)
    if corners:
        return corners
    lines = [
        tuple(scene.shapes[i].points) for i in symbol.shapes if len(scene.shapes[i].points) == 2
    ]
    lines = [ln for ln in lines if geometry.distance(*ln) > MIN_GROUND_BASE]

    def meet(p: Point, q: Point) -> bool:
        return geometry.distance(p, q) <= CORNER_GAP

    # Two lines meeting at one end, and a third joining their other ends.
    for i, first in enumerate(lines):
        for second in lines[i + 1 :]:
            shared = [(p, q) for p in first for q in second if meet(p, q)]
            if len(shared) != 1:
                continue
            apex = shared[0][0]
            e1 = next(p for p in first if not meet(p, apex))
            e2 = next(q for q in second if not meet(q, apex))
            for third in lines:
                c, d = third
                closes = (meet(c, e1) and meet(d, e2)) or (meet(c, e2) and meet(d, e1))
                if closes and _on_axis(
                    symbol.pins, apex, geometry.center(geometry.bbox_of((e1, e2)))
                ):
                    return [apex, e1, e2]
    return corners


def _on_axis(pins: list[Pin], apex: Point, base: Point) -> bool:
    """A diode's two pins start at its triangle's tip and at the middle of its base."""
    if len(pins) != 2:
        return False
    a, b = (p.line[0] for p in pins)
    near = 2 * CORNER_GAP
    return (geometry.distance(a, apex) <= near and geometry.distance(b, base) <= near) or (
        geometry.distance(b, apex) <= near and geometry.distance(a, base) <= near
    )


def _within_outline(symbol: Symbol, text: Text) -> bool:
    if not symbol.body:
        return False
    x0, y0, x1, y1 = symbol.body
    cx, cy = geometry.center(text.bbox)
    return x0 < cx < x1 and y0 < cy < y1


def _belongs_to_a_pin(symbol: Symbol, text: Text, profile: Profile, texts: _Texts) -> bool:
    """Where designators sit outside the box: a text inside it is a pin name, one by a
    pin outside it a pad number. Two-pin parts are left out, as their designator can
    come near the pin ends."""
    if len(symbol.pins) <= 2:
        return False
    return _within_outline(symbol, text) or _numbers_a_pin(symbol, text, profile, texts)


def _numbers_a_pin(symbol: Symbol, text: Text, profile: Profile, texts: _Texts) -> bool:
    """True if the text sits where a pin of the part has its number, and another pin
    has a text where its own goes: a part that shows pad numbers shows them on its pins
    alike, so a lone text by one pin of a transistor is its designator."""
    above = profile.pin_numbers_above
    mine = [p for p in symbol.pins if _number_gap(text.bbox, p.line, above) is not None]
    if not mine:
        return False
    around = (symbol.bbox[0] - 5, symbol.bbox[1] - 5, symbol.bbox[2] + 5, symbol.bbox[3] + 5)
    others = [texts.texts[i] for i in texts.index.within(around) if texts.texts[i] is not text]
    return any(
        _number_gap(other.bbox, pin.line, above) is not None
        for pin in symbol.pins
        if pin not in mine
        for other in others
    )


def _number_gap(
    box: BBox, line: tuple[Point, Point], above: bool, overhang_ok: bool = False
) -> float | None:
    """Distance from a pin to a number placed beside it, or None if it is not beside it.

    With `above`, numbers usually sit above horizontal pins and left of vertical
    ones; mirrored symbols put them on the other side, at a small extra cost. With
    `overhang_ok`, a number on a short pin may overhang its tip a little; by how much
    its middle does counts against it.
    """
    (ax, ay), (bx, by) = line
    if geometry.is_horizontal(line):
        start, end, lo, hi, at = box[0], box[2], min(ax, bx), max(ax, bx), ay
        near, far = at - box[3], box[1] - at
    else:
        start, end, lo, hi, at = box[1], box[3], min(ay, by), max(ay, by), ax
        near, far = at - box[2], box[0] - at
    along = (start + end) / 2
    overhang = max(lo - 0.5 - along, along - hi - 0.5, 0.0)
    limit = MAX_OVERHANG if overhang_ok else 0.0
    if overhang > limit or (overhang and (end < lo or start > hi)):
        return None
    gap = _side_gap(near, far, above)
    return gap + overhang if gap is not None else None


def _side_gap(near: float, far: float, above: bool) -> float | None:
    """The gap across the pin to its number, by the side the number is on."""
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
    symbols: list[Symbol],
    texts: _Texts,
    runs: Runs | None,
    name_gap: float,
    profile: Profile | None = None,
    named_by: dict[int, int] | None = None,
    values: set[int] = frozenset(),
) -> None:
    """The value is the next text drawn after the designator, or else the nearest one,
    each text the value of one part. A pin's name or number is no value, nor is a note
    written as a sentence. Where designators have a colour of their own, values share
    it; where each part's value is drawn right before its designator, that text is it."""
    named = [s for s in symbols if s.ref]
    if profile and profile.value_before_designator and named_by:
        by_seq = {t.seq: i for i, t in enumerate(texts.texts)}
        for symbol in named:
            ti = named_by.get(id(symbol))
            vi = by_seq.get(texts.texts[ti].seq - 1) if ti is not None else None
            if vi is not None and vi not in texts.used and id(texts.texts[vi]) in values:
                symbol.value = texts.texts[vi].text
                texts.used.add(vi)
        named = [s for s in named if not s.value]
    own_colour = bool(profile and profile.colors.get("designator"))
    candidates = []
    for si, symbol in enumerate(named):
        for gap, ti in texts.near(symbol.bbox, REF_SEARCH / 2):
            text = texts.texts[ti]
            if own_colour and not profile.is_("designator", text.color):
                continue
            if is_pin_name(symbol, text, name_gap) or _read_as_number(symbol, text):
                continue
            if len(text.text.split()) > MAX_VALUE_WORDS:
                continue
            if runs and not runs.owns(symbol, text.seq):
                continue
            candidates.append((text.seq if runs else gap, si, ti))
    if runs:  # drawn in turn: the first text after the designator, part by part
        pairs = []
        for si in range(len(named)):
            mine = [(cost, ti) for cost, sj, ti in candidates if sj == si and ti not in texts.used]
            if mine:
                _, ti = min(mine)
                pairs.append((si, ti))
                texts.used.add(ti)
    else:
        pairs = geometry.best_pairs(sorted(candidates), UNPAIRED_COST)
    for si, ti in pairs:
        named[si].value = texts.texts[ti].text
        texts.used.add(ti)


def _read_as_number(symbol: Symbol, text: Text) -> bool:
    """Whether the text labels one of the part's pins beside it: the number read for
    it, or a single sign such as a diode's A and K or a capacitor's +."""
    c = geometry.center(text.bbox)
    word = text.text.strip()
    return any(
        (pin.number == word or len(word) == 1)
        and geometry.distance_to_segment(c, pin.line) <= PIN_NUMBER_GAP + _size(text)
        for pin in symbol.pins
    )


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
    """A part value with a unit or a decimal point, such as 10k or 0.1uF, or a rating,
    such as 5%, 50V or 1/10W: never a pad."""
    return (bool(PART_VALUE.match(text)) and not text.isdigit()) or bool(RATING.match(text))


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
    # The ink of a narrow last letter, such as 1, stops short of where the text is set.
    reach = gap + SIDE_BEARING * text.size + _size(text) / 2
    vertical_text = round(text.angle) % 180 == 90
    return any(
        geometry.distance(c, pin.line[0]) <= reach
        and geometry.is_horizontal(pin.line) != vertical_text
        for pin in symbol.pins
    )
