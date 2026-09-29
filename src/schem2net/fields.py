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
from schem2net.geometry import GridIndex, UnionFind
from schem2net.primitives import BBox, Point, Text
from schem2net.profile import Profile
from schem2net.scene import Scene

if TYPE_CHECKING:
    from schem2net.symbols import Pin, Runs, Symbol

REF_SEARCH = 10.0  # mm around a symbol body
POWER_NAME_GAP = 2.5  # mm between a power symbol and its name
POWER_MAX_SIZE = 8.0  # mm
PIN_NUMBER_GAP = 2.0  # mm between a pin and its number
PIN_NAME_GAP = 1.5  # mm between a pin's inner end and its name
UNKNOWN_PREFIX_COST = REF_SEARCH  # "LM358" looks like a designator but is a value
OTHER_SYMBOL_COST = REF_SEARCH  # text drawn after a different symbol
UNPAIRED_COST = 3 * REF_SEARCH + 1

# Prefix, number, optional unit letter: "R12", "U5A", "SW_POWER0", "Bat+1".
REFDES = re.compile(r"^([A-Za-z][A-Za-z_+\-]*?)(\d+)([A-Z]?)$")
COMMON_PREFIXES = {
    "A", "BT", "C", "CN", "CON", "D", "DS", "F", "FB", "FID", "H", "IC", "J", "JP", "K", "L",
    "LED", "LS", "M", "MH", "P", "Q", "R", "RN", "RV", "S", "SW", "T", "TH", "TP", "U", "VR",
    "X", "Y", "Z",
}  # fmt: skip


def annotate(symbols: list[Symbol], scene: Scene, profile: Profile, runs: Runs | None) -> None:
    texts = _Texts(scene.fields)
    _name_power_symbols(symbols, texts, scene, profile, runs)
    _assign_refs(symbols, texts, runs)
    _number_pins(symbols, scene.pin_numbers)
    _assign_values(symbols, texts, runs)


def is_common_ref(text: str) -> bool:
    match = REFDES.match(text)
    return bool(match) and match.group(1) in COMMON_PREFIXES


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
    for symbol in symbols:
        x0, y0, x1, y1 = symbol.bbox
        if len(symbol.pins) > 1 or not symbol.body or max(x1 - x0, y1 - y0) > POWER_MAX_SIZE:
            continue
        for _, i in texts.near(symbol.bbox, POWER_NAME_GAP):
            text = texts.texts[i]
            if not _is_net_name(text.text) or text.text in profile.not_power_nets:
                continue
            if is_common_ref(text.text):
                continue  # a one-pin part, such as a test point
            # The name is the first text drawn after the symbol, or else sits in line with it.
            if runs.first_text(symbol) == text.seq if runs else _in_line(symbol, text):
                symbol.power = text.text
                symbol.anchors = _anchors(symbol, scene)
                texts.used.add(i)
                break


def _anchors(symbol: Symbol, scene: Scene) -> list[Point]:
    """A power symbol connects at its pin, or else at a loose end of its drawing."""
    if symbol.pins:
        return [p.at for p in symbol.pins]
    shapes = (scene.shapes[i] for i in symbol.shapes)
    return [p for shape in shapes if not shape.closed for p in (shape.points[0], shape.points[-1])]


def _in_line(symbol: Symbol, text: Text) -> bool:
    """True if the text sits beyond the symbol along its pin axis, not beside it."""
    x0, y0, x1, y1 = symbol.bbox
    cx, cy = geometry.center(text.bbox)
    above_or_below = x0 - 0.5 <= cx <= x1 + 0.5 and not y0 < cy < y1
    left_or_right = y0 - 0.5 <= cy <= y1 + 0.5 and not x0 < cx < x1
    if not symbol.pins:
        return above_or_below or left_or_right
    return left_or_right if geometry.is_horizontal(symbol.pins[0].line) else above_or_below


def _assign_refs(symbols: list[Symbol], texts: _Texts, runs: Runs | None) -> None:
    parts = [s for s in symbols if s.pins and not s.power]
    candidates = []
    for si, symbol in enumerate(parts):
        for gap, ti in texts.near(symbol.body or symbol.bbox, REF_SEARCH):
            text = texts.texts[ti]
            match = REFDES.match(text.text)
            if not match or _is_pin_name(symbol, text):
                continue
            cost = gap
            if match.group(1) not in COMMON_PREFIXES:
                cost += UNKNOWN_PREFIX_COST
            if runs and not runs.owns(symbol, text.seq):
                cost += OTHER_SYMBOL_COST
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


def _number_pins(symbols: list[Symbol], numbers: list[Text]) -> None:
    pins = [p for s in symbols if s.ref for p in s.pins]
    index = GridIndex()
    for i, pin in enumerate(pins):
        index.add(i, geometry.bbox_of(pin.line))

    best: dict[int, tuple[float, str]] = {}
    for text in numbers:
        c = geometry.center(text.bbox)
        vertical_text = round(text.angle) % 180 == 90
        options = [
            (geometry.distance_to_segment(c, pins[i].line), i)
            for i in index.near(c, PIN_NUMBER_GAP)
            if geometry.is_horizontal(pins[i].line) != vertical_text
        ]
        if options:
            gap, i = min(options)
            if gap <= PIN_NUMBER_GAP and (i not in best or gap < best[i][0]):
                best[i] = (gap, text.text)
    for i, (_, number) in best.items():
        pins[i].number = number

    by_ref: dict[str, list[Pin]] = {}
    for s in symbols:
        if s.ref:
            by_ref.setdefault(s.ref, []).extend(s.pins)
    for part_pins in by_ref.values():
        if any(p.number for p in part_pins):
            continue
        # Small parts often hide pin numbers. Number them top-left first.
        if len(part_pins) <= 2:
            for number, pin in enumerate(sorted(part_pins, key=lambda p: (p.at[1], p.at[0])), 1):
                pin.number = str(number)


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


def _is_net_name(text: str) -> bool:
    return any(c.isalpha() for c in text)


def _is_pin_name(symbol: Symbol, text: Text) -> bool:
    """Pin names sit inside the body, next to the inner end of a pin."""
    if len(symbol.pins) <= 2 or not symbol.body:
        return False
    c = geometry.center(text.bbox)
    x0, y0, x1, y1 = symbol.body
    if not (x0 + 0.3 <= c[0] <= x1 - 0.3 and y0 + 0.3 <= c[1] <= y1 - 0.3):
        return False
    reach = PIN_NAME_GAP + max(text.bbox[2] - text.bbox[0], text.bbox[3] - text.bbox[1]) / 2
    return any(geometry.distance(c, pin.line[0]) <= reach for pin in symbol.pins)
