"""How likely each text of a page is to be a part's designator.

Rules tell most designators by their form, R12 or U5A, but designers name parts as
they please (LCD_CON, GPIO1-1, USB-Serial/JTAG1) and values look like designators
too (Z80, A20). Gradient-boosted trees, learned from the dev designs of each corpus
(see `bench/designators.py`), weigh what a text says, where it sits against the
nearest part and the wires, and what the generator drew just before and after it.
They are stored as node arrays in `profiles/designators.npz` and read with numpy.
"""

from __future__ import annotations

import statistics
from functools import cache
from typing import TYPE_CHECKING

import numpy as np

from schem2net import geometry
from schem2net.geometry import GridIndex
from schem2net.primitives import Text
from schem2net.profile import Profile, learned_arrays, learned_file
from schem2net.refdes import COMMON_PREFIXES, PART_VALUE, REFDES, is_common_ref, split_ref
from schem2net.roles import Forest
from schem2net.scene import Scene, values_run

if TYPE_CHECKING:
    from schem2net.symbols import Runs, Symbol

NEAR = 15.0  # mm around a text searched for parts
ORDER = 6  # texts drawn either side of a text that give its context
MODEL_FILE = "designators.npz"

FEATURES = (
    "length",
    "digits",
    "letters",
    "capitals",
    "number",
    "separators",
    "designator form",
    "usual prefix",
    "value form",
    "leading digit",
    "space",
    "trailing digit",
    "gap to part",
    "inside part",
    "pin tip",
    "pin start",
    "part pins",
    "part size",
    "across part",
    "along part",
    "wire gap",
    "along wire",
    "in outline",
    "relative size",
    "upright",
    "among values",
    "designators around",
    "values around",
    "numbers around",
    "first after part",
    "drawn with part",
    "designator colour",
    "pin number colour",
    "field colour",
)


def features(
    scene: Scene, symbols: list[Symbol], runs: Runs | None, profile: Profile
) -> np.ndarray:
    """One row of FEATURES for each text of scene.fields, in its order."""
    texts = scene.fields
    parts = [s for s in symbols if s.pins and not s.power]
    part_index = GridIndex(cell=5.0)
    for k, part in enumerate(parts):
        part_index.add(k, part.bbox)
    tips = [(p.at, p.line[0]) for s in parts for p in s.pins]
    tip_index = GridIndex()
    for k, (at, start) in enumerate(tips):
        tip_index.add(k, geometry.bbox_of((at, start)))
    wire_index = GridIndex(cell=5.0)
    for k, wire in enumerate(scene.wires):
        wire_index.add(k, geometry.bbox_of(wire))
    outlines = [s for s in scene.shapes if s.closed]
    outline_index = GridIndex(cell=5.0)
    for k, shape in enumerate(outlines):
        outline_index.add(k, shape.bbox)

    sizes = [t.size for t in texts if t.size > 0]
    median = statistics.median(sizes) if sizes else 1.0
    run = values_run(texts, ORDER)
    order = sorted(texts, key=lambda t: t.seq)
    at = {id(t): k for k, t in enumerate(order)}
    refs = [is_common_ref(t.text) for t in order]
    values = [t.text[:1].isdigit() and not t.text.isdigit() for t in order]
    numbers = [t.text.isdigit() for t in order]
    firsts = {runs.first_text(s) for s in parts} if runs else set()

    rows = []
    for text in texts:
        word = text.text.strip()
        letters = sum(c.isalpha() for c in word)
        match = REFDES.match(word)
        centre = geometry.center(text.bbox)

        nearby = [parts[k] for k in part_index.within(geometry.grown(text.bbox, NEAR))]
        part = min(
            nearby, key=lambda s: geometry.bbox_gap(s.body or s.bbox, text.bbox), default=None
        )
        if part:
            body = part.body or part.bbox
            gap = geometry.bbox_gap(body, text.bbox)
            inside = body[0] < centre[0] < body[2] and body[1] < centre[1] < body[3]
            width, height = max(body[2] - body[0], 1.0), max(body[3] - body[1], 1.0)
            across = (centre[0] - (body[0] + body[2]) / 2) / width
            along = (centre[1] - (body[1] + body[3]) / 2) / height
            pins, size = len(part.pins), max(width, height)
        else:
            gap, inside, across, along, pins, size = NEAR, False, 0.0, 0.0, 0, 0.0

        near_tips = tip_index.near(centre, 4.0)
        tip_gap = min((geometry.distance(centre, tips[k][0]) for k in near_tips), default=4.0)
        start_gap = min((geometry.distance(centre, tips[k][1]) for k in near_tips), default=4.0)
        wires = [scene.wires[k] for k in wire_index.near(centre, 5.0)]
        wire_gap = min((geometry.distance_to_segment(centre, w) for w in wires), default=5.0)
        bottom = ((text.bbox[0] + text.bbox[2]) / 2, text.bbox[3])
        under = min((geometry.distance_to_segment(bottom, w) for w in wires), default=5.0)
        held = any(
            outlines[k].bbox[0] <= centre[0] <= outlines[k].bbox[2]
            and outlines[k].bbox[1] <= centre[1] <= outlines[k].bbox[3]
            and geometry.in_polygon(centre, outlines[k].points)
            for k in outline_index.near(centre, 0.0)
        )

        k = at[id(text)]
        around = slice(max(0, k - ORDER), k + ORDER + 1)
        owned = -1.0
        if runs and part:
            owned = float(runs.owns(part, text.seq))

        rows.append(
            [
                len(word),
                sum(c.isdigit() for c in word) / max(len(word), 1),
                letters / max(len(word), 1),
                sum(c.isupper() for c in word) / max(letters, 1),
                word.isdigit(),
                any(c in word for c in "/_+-.$"),
                bool(match),
                bool(match) and match.group(1).rstrip("$") in COMMON_PREFIXES,
                bool(PART_VALUE.match(word)),
                word[:1].isdigit(),
                any(c.isspace() for c in word),
                word[-1:].isdigit(),
                gap,
                inside,
                tip_gap,
                start_gap,
                pins,
                size,
                across,
                along,
                wire_gap,
                under,
                held,
                text.size / median if median else 1.0,
                round(text.angle) % 180 == 90,
                id(text) in run,
                sum(refs[around]) - refs[k],
                sum(values[around]) - values[k],
                sum(numbers[around]) - numbers[k],
                text.seq in firsts,
                owned,
                profile.is_("designator", text.color),
                profile.is_("pin_number", text.color),
                profile.is_("field", text.color),
            ]
        )
    return np.array(rows, dtype=float).reshape(len(rows), len(FEATURES))


def likelihood(
    scene: Scene, symbols: list[Symbol], runs: Runs | None, profile: Profile
) -> dict[int, float] | None:
    """For each text of scene.fields, by id, how likely it is a designator; None where no
    model was learned for the generator."""
    model = _model(profile.name)
    if model is None or not scene.fields:
        return None
    rows = features(scene, symbols, runs, profile)
    return dict(zip((id(t) for t in scene.fields), probability(model, rows), strict=True))


def probability(model: Forest, rows: np.ndarray) -> np.ndarray:
    """The second class's probability, from a two-class forest."""
    if len(model.classes) == 1:
        return np.full(len(rows), float(model.classes[0]))
    raw = model._raw(rows)
    return 1.0 / (1.0 + np.exp(raw[:, 0] - raw[:, 1]))


def _model(generator: str) -> Forest | None:
    return _forest(learned_file(MODEL_FILE), generator)


@cache
def _forest(path, generator: str) -> Forest | None:
    arrays = learned_arrays(path)
    return Forest(arrays, generator) if f"{generator}.classes" in arrays else None


def label(text: Text, refs: set[str]) -> bool:
    """Whether the text is a designator of the truth: a reference, or one with a unit."""
    word = text.text.strip()
    if word in refs:
        return True
    match = split_ref(word)
    return bool(match) and match.group(3) is not None and match.group(1) + match.group(2) in refs
