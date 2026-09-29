"""Stages 3-4: sort a page's primitives into wires, symbol graphics and texts."""

from dataclasses import dataclass, field
from typing import Literal

from schem2net import geometry
from schem2net.geometry import GridIndex, Segment
from schem2net.primitives import BBox, Page, Path, Point, Text
from schem2net.profile import Profile

LABEL_OUTLINE_MAX_HEIGHT = 4.0  # mm, across the text direction


@dataclass(slots=True)
class Shape:
    id: int
    points: list[Point]
    width: float
    bbox: BBox
    seq: int = 0

    @property
    def closed(self) -> bool:
        return len(self.points) > 2 and geometry.distance(self.points[0], self.points[-1]) < 1e-3


@dataclass(slots=True)
class Label:
    text: str
    kind: Literal["local", "global", "hier"]
    bbox: BBox
    angle: float
    outline: list[Point] = field(default_factory=list)


@dataclass
class Scene:
    page: int
    wires: list[Segment] = field(default_factory=list)
    junctions: list[Point] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    fields: list[Text] = field(default_factory=list)
    pin_numbers: list[Text] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)


def build(page: Page, profile: Profile) -> Scene:
    scene = Scene(page=page.number)
    outlines: dict[str, list[list[Point]]] = {"global": [], "hier": []}

    for path in _unique_paths(page.paths):
        if profile.is_("wire", path.stroke or path.fill):
            if path.fill and path.curved:
                scene.junctions.append(geometry.center(path.bbox))
            else:
                scene.wires.extend(
                    s for sub in path.subpaths for s in geometry.segments(sub) if s[0] != s[1]
                )
        elif profile.is_("symbol", path.stroke or path.fill):
            for sub in path.subpaths:
                box = geometry.bbox_of(sub)
                if box[2] - box[0] > 1e-3 or box[3] - box[1] > 1e-3:  # skip zero-length dots
                    scene.shapes.append(Shape(len(scene.shapes), sub, path.width, box, path.seq))
        elif profile.is_("hier_label", path.stroke):
            outlines["hier"].extend(path.subpaths)

    label_texts = {"global": [], "hier": []}
    for text in _join_runs(_unique_texts(page.texts)):
        if profile.is_("field", text.color):
            scene.fields.append(text)
        elif profile.is_("pin_number", text.color):
            scene.pin_numbers.append(text)
        elif profile.is_("local_label", text.color):
            scene.labels.append(Label(text.text, "local", text.bbox, text.angle))
        elif profile.is_("hier_label", text.color):
            label_texts["hier"].append(text)
        elif profile.is_("global_label", text.color):
            label_texts["global"].append(text)

    # Global labels share the symbol colour, so their outlines are found among the shapes.
    outlines["global"] = [s.points for s in scene.shapes if s.closed]
    used = set()
    for kind in ("global", "hier"):
        for text, outline in _outlined(label_texts[kind], outlines[kind]):
            scene.labels.append(Label(text.text, kind, text.bbox, text.angle, outline))
            used.add(id(outline))
    scene.shapes = [s for s in scene.shapes if id(s.points) not in used]
    for i, shape in enumerate(scene.shapes):
        shape.id = i
    return scene


def _outlined(texts: list[Text], outlines: list[list[Point]]):
    """Pair each text with the small closed outline drawn around it."""
    index = GridIndex()
    boxes = [geometry.bbox_of(o) for o in outlines]
    for i, box in enumerate(boxes):
        if min(box[2] - box[0], box[3] - box[1]) <= LABEL_OUTLINE_MAX_HEIGHT:
            index.add(i, box)
    for text in texts:
        cx, cy = geometry.center(text.bbox)
        for i in index.near((cx, cy), 0):
            x0, y0, x1, y1 = boxes[i]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                yield text, outlines[i]
                break


def _join_runs(texts: list[Text]) -> list[Text]:
    """Rejoin text that the PDF splits into pieces at spaces and at subscripts or overbars."""
    out: list[Text] = []
    for text in sorted(texts, key=lambda t: t.seq):
        prev = out[-1] if out else None
        if prev and _continues(prev, text):
            gap = _along(text.bbox, text.angle)[0] - _along(prev.bbox, prev.angle)[1]
            joiner = " " if gap > 0.25 * prev.size else ""
            out[-1] = Text(
                id=prev.id,
                text=prev.text + joiner + text.text,
                bbox=geometry.union_bbox(prev.bbox, text.bbox),
                size=max(prev.size, text.size),
                angle=prev.angle,
                color=prev.color,
                seq=text.seq,
            )
        else:
            out.append(text)
    return out


def _continues(prev: Text, text: Text) -> bool:
    """True if text is drawn right after prev and carries on along the same line."""
    if text.seq != prev.seq + 1 or text.color != prev.color or text.angle != prev.angle:
        return False
    start, _ = _along(text.bbox, text.angle)
    _, end = _along(prev.bbox, prev.angle)
    lo_a, hi_a = _across(prev.bbox, prev.angle)
    lo_b, hi_b = _across(text.bbox, text.angle)
    return -0.5 <= start - end <= 0.8 * prev.size and min(hi_a, hi_b) > max(lo_a, lo_b)


def _along(box: BBox, angle: float) -> tuple[float, float]:
    """Extent of a box in the reading direction of its text."""
    if round(angle) % 180 == 90:
        return -box[3], -box[1]  # text reading upwards
    return box[0], box[2]


def _across(box: BBox, angle: float) -> tuple[float, float]:
    if round(angle) % 180 == 90:
        return box[0], box[2]
    return box[1], box[3]


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen, out = set(), []
    for path in paths:
        key = (
            path.stroke,
            path.fill,
            tuple((round(x, 3), round(y, 3)) for sub in path.subpaths for x, y in sub),
        )
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _unique_texts(texts: list[Text]) -> list[Text]:
    seen, out = set(), []
    for text in texts:
        key = (text.text, text.color, tuple(round(v, 2) for v in text.bbox))
        if key not in seen:
            seen.add(key)
            out.append(text)
    return out
