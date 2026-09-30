"""Stages 3-4: sort a page's primitives into wires, symbol graphics and texts."""

from dataclasses import dataclass, field
from typing import Literal

from schem2net import geometry
from schem2net.geometry import GridIndex, Segment
from schem2net.primitives import BBox, Page, Path, Point, Text
from schem2net.profile import Profile

LABEL_OUTLINE_MAX_HEIGHT = 4.0  # mm, across the text direction
SHEET_TEXT_GAP = 2.0  # mm between a sheet box and its name or file text


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
    kind: Literal["local", "global", "hier", "bus"]
    bbox: BBox
    angle: float
    outline: list[Point] = field(default_factory=list)


@dataclass(slots=True)
class SheetPin:
    name: str
    at: Point


@dataclass
class Sheet:
    """A box on a parent page standing for a child page."""

    name: str
    bbox: BBox
    pins: list[SheetPin] = field(default_factory=list)


@dataclass
class Scene:
    page: int
    path: str | None = None  # hierarchical path of this page, such as "/Power/"
    wires: list[Segment] = field(default_factory=list)
    buses: list[Segment] = field(default_factory=list)
    junctions: list[Point] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    fields: list[Text] = field(default_factory=list)
    pin_numbers: list[Text] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    sheets: list[Sheet] = field(default_factory=list)


def name_key(text: str) -> str:
    """A name as compared between labels.

    Whitespace is dropped because text extraction does not keep it reliably, and
    some fonts map the minus sign to a control character.
    """
    return "".join(text.replace("\x02", "-").split())


def build(page: Page, profile: Profile) -> Scene:
    scene = Scene(page=page.number)
    outlines: dict[str, list[list[Point]]] = {"global": [], "hier": []}
    pin_outlines: list[list[Point]] = []

    for path in _unique_paths(page.paths):
        if profile.is_("wire", path.stroke or path.fill):
            if path.fill and path.curved:
                scene.junctions.append(geometry.center(path.bbox))
            else:
                scene.wires.extend(
                    s for sub in path.subpaths for s in geometry.segments(sub) if s[0] != s[1]
                )
        elif profile.is_("bus", path.stroke):
            scene.buses.extend(
                s for sub in path.subpaths for s in geometry.segments(sub) if s[0] != s[1]
            )
        elif profile.is_("symbol", path.stroke or path.fill):
            for sub in path.subpaths:
                box = geometry.bbox_of(sub)
                if box[2] - box[0] > 1e-3 or box[3] - box[1] > 1e-3:  # skip zero-length dots
                    scene.shapes.append(Shape(len(scene.shapes), sub, path.width, box, path.seq))
        elif profile.is_("hier_label", path.stroke):
            outlines["hier"].extend(path.subpaths)
        elif profile.is_("sheet_pin", path.stroke):
            pin_outlines.extend(path.subpaths)

    label_texts = {"global": [], "hier": []}
    sheet_files, bus_texts = [], []
    for text in _join_runs(_unique_texts(page.texts)):
        if profile.sheet_path_prefix and text.text.startswith(profile.sheet_path_prefix):
            scene.path = name_key(text.text.removeprefix(profile.sheet_path_prefix))
        elif profile.sheet_file_prefix and text.text.startswith(profile.sheet_file_prefix):
            if profile.is_("hier_label", text.color):
                sheet_files.append(text)
        elif profile.is_("field", text.color):
            scene.fields.append(text)
        elif profile.is_("pin_number", text.color):
            scene.pin_numbers.append(text)
        elif profile.is_("local_label", text.color):
            scene.labels.append(Label(text.text, "local", text.bbox, text.angle))
        elif profile.is_("hier_label", text.color):
            label_texts["hier"].append(text)
        elif profile.is_("global_label", text.color):
            label_texts["global"].append(text)
        elif profile.is_("bus", text.color):
            bus_texts.append(text)

    # Global labels share the symbol colour, so their outlines are found among the shapes.
    outlines["global"] = [s.points for s in scene.shapes if s.closed]
    used = _find_sheets(scene, sheet_files, pin_outlines, bus_texts)
    for text, outline in _outlined(label_texts["global"], outlines["global"]):
        scene.labels.append(Label(text.text, "global", text.bbox, text.angle, outline))
        used.add(id(outline))
    # Bus names are drawn in the bus colour, whether they are labels or hierarchical labels.
    flagged = set()
    for text, anchor in _flagged(label_texts["hier"] + bus_texts, outlines["hier"]):
        scene.labels.append(Label(text.text, "hier", text.bbox, text.angle, [anchor]))
        flagged.add(id(text))
    for text in bus_texts:
        if id(text) not in flagged:
            scene.labels.append(Label(text.text, "bus", text.bbox, text.angle))
    scene.shapes = [s for s in scene.shapes if id(s.points) not in used]
    for i, shape in enumerate(scene.shapes):
        shape.id = i
    return scene


def _find_sheets(
    scene: Scene, files: list[Text], pin_outlines: list[list[Point]], bus_texts: list[Text]
) -> set[int]:
    """Find sheet boxes by their file text, and take their names and pins out of the texts.

    Returns the ids of the box outlines, which are not symbol graphics.
    """
    boxes = [s for s in scene.shapes if s.closed]
    used = set()
    for file in files:
        fx, fy = file.bbox[0], file.bbox[1]
        box = next(
            (s for s in boxes if abs(s.bbox[0] - fx) < 1 and 0 <= fy - s.bbox[3] < SHEET_TEXT_GAP),
            None,
        )
        if box is None:
            continue
        x0, y0, x1, y1 = box.bbox
        name = next(
            (
                t
                for t in scene.fields
                if abs(t.bbox[0] - x0) < 1 and 0 <= y0 - t.bbox[3] < SHEET_TEXT_GAP
            ),
            None,
        )
        if name is None:
            continue
        sheet = Sheet(name.text, box.bbox)
        taken = [name]
        for outline in pin_outlines:
            at = _on_edge(geometry.bbox_of(outline), box.bbox)
            if at is None:
                continue
            outline_box = geometry.bbox_of(outline)
            candidates = scene.fields + bus_texts
            text = min(candidates, key=lambda t: geometry.bbox_gap(t.bbox, outline_box))
            if geometry.bbox_gap(text.bbox, outline_box) < 1.5:
                sheet.pins.append(SheetPin(text.text, at))
                taken.append(text)
        scene.fields = [t for t in scene.fields if not any(t is u for u in taken)]
        bus_texts[:] = [t for t in bus_texts if not any(t is u for u in taken)]
        scene.sheets.append(sheet)
        used.add(id(box.points))
    return used


def _on_edge(pin: BBox, box: BBox, tol: float = 0.05) -> Point | None:
    """Where a sheet pin's outline meets the edge of its sheet box, if it does."""
    cx, cy = geometry.center(pin)
    if box[1] <= cy <= box[3]:
        for x in (box[0], box[2]):
            if abs(pin[0] - x) < tol or abs(pin[2] - x) < tol:
                return x, cy
    if box[0] <= cx <= box[2]:
        for y in (box[1], box[3]):
            if abs(pin[1] - y) < tol or abs(pin[3] - y) < tol:
                return cx, y
    return None


def _flagged(texts: list[Text], outlines: list[list[Point]]):
    """Pair each text with the small flag drawn beside it, and find where the flag connects.

    The flag connects on the text's centre line, at its side away from the text.
    """
    index = GridIndex()
    boxes = [geometry.bbox_of(o) for o in outlines]
    for i, box in enumerate(boxes):
        index.add(i, box)
    for text in texts:
        x0, y0, x1, y1 = text.bbox
        near = [
            (geometry.bbox_gap(text.bbox, boxes[i]), i)
            for i in index.within((x0 - 1, y0 - 1, x1 + 1, y1 + 1))
        ]
        near = [(gap, i) for gap, i in near if gap < 1.0]
        if not near:
            continue
        box = boxes[min(near)[1]]
        tx, ty = geometry.center(text.bbox)
        fx, fy = geometry.center(box)
        if round(text.angle) % 180 == 90:
            yield text, (fx, box[1] if fy < ty else box[3])
        else:
            yield text, (box[0] if fx < tx else box[2], ty)


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
