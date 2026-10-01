"""Stages 3-4: sort a page's primitives into wires, symbol graphics and texts."""

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Literal

from schem2net import geometry
from schem2net.geometry import GridIndex, Segment
from schem2net.primitives import BBox, Color, Page, Path, Point, Text
from schem2net.profile import Profile
from schem2net.refdes import is_common_ref

LABEL_OUTLINE_MAX_HEIGHT = 4.0  # mm, across the text direction
MIN_COLOUR_HITS = 5  # pin ends a colour must reach to be taken as a wire or body colour
BUS_WIDTH_RATIO = 1.8  # a wire-coloured line this much thicker than usual is a bus
SHEET_TEXT_GAP = 2.0  # mm between a sheet box and its name or file text


@dataclass(slots=True)
class Shape:
    id: int
    points: list[Point]
    width: float
    bbox: BBox
    seq: int = 0
    color: Color | None = None

    @property
    def closed(self) -> bool:
        return _closed(self.points)


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

    paths = _unique_paths(page.paths)
    if profile.infer_wire_colour:
        profile = _with_wire_colour(paths, profile)
        profile = _with_body_colours(paths, profile)
    thick = _thick_lines(paths, profile) if profile.thick_wires_are_buses else set()
    wire_like, dot_like = set(), set()
    if profile.wires_drawn_together:
        wire_like = _drawn_with_wires(paths, page.texts, profile, _is_line)
        dot_like = _drawn_with_wires(paths, page.texts, profile, _is_dot)

    for path in paths:
        color = path.stroke or path.fill
        if path.seq in dot_like or (profile.is_("wire", color) and _is_dot_or_ring(path)):
            scene.junctions.append(geometry.center(path.bbox))
        elif path.seq in thick or profile.is_("bus", path.stroke):
            scene.buses.extend(_segments(path))
        elif _is_wire(path, wire_like, profile):
            scene.wires.extend(_chords(path) if _is_hop(path) else _segments(path))
        elif profile.is_("symbol", color) or profile.is_("pin", color):
            for sub in path.subpaths:
                box = geometry.bbox_of(sub)
                if box[2] - box[0] > 1e-3 or box[3] - box[1] > 1e-3:  # skip zero-length dots
                    shape = Shape(len(scene.shapes), sub, path.width, box, path.seq, color)
                    scene.shapes.append(shape)
        elif profile.is_("hier_label", path.stroke):
            outlines["hier"].extend(path.subpaths)
        elif profile.is_("sheet_pin", path.stroke):
            pin_outlines.extend(path.subpaths)

    label_texts = {"local": [], "global": [], "hier": []}
    recoloured = []  # texts in a colour no role has, such as labels given their own
    sheet_files, bus_texts = [], []
    visible = [t for t in page.texts if t.visible]
    known = set().union(*profile.colors.values())
    for text in _join_runs(_unique_texts(visible)):
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
            label_texts["local"].append(text)
        elif profile.is_("hier_label", text.color):
            label_texts["hier"].append(text)
        elif profile.is_("global_label", text.color):
            label_texts["global"].append(text)
        elif profile.is_("bus", text.color):
            bus_texts.append(text)
        elif (
            profile.designators_in_any_colour
            and text.color not in known
            and is_common_ref(text.text)
        ):
            scene.fields.append(text)  # a designator given a colour of its own
        elif text.color not in known:
            recoloured.append(text)

    # Global labels share the symbol colour, so their outlines are found among the shapes.
    outlines["global"] = [s.points for s in scene.shapes if s.closed]
    # Sheet borders can have any colour, so every closed outline is a candidate.
    outlines_any = [
        sub for p in paths if p.stroke and not p.fill for sub in p.subpaths if _closed(sub)
    ]
    used = _find_sheets(scene, sheet_files, pin_outlines, bus_texts, outlines_any)
    for text, outline in _outlined(label_texts["global"], outlines["global"]):
        scene.labels.append(Label(text.text, "global", text.bbox, text.angle, outline))
        used.add(id(outline))
    # A net label text inside an outline is a port, which reaches other sheets. So is
    # text given a colour of its own, when its outline meets a wire.
    wire_index = GridIndex()
    for k, wire in enumerate(scene.wires):
        wire_index.add(k, geometry.bbox_of(wire))
    wired = [o for o in outlines["global"] if _meets_wire(o, scene.wires, wire_index)]
    ported = set()
    pairs = [*_outlined(label_texts["local"], outlines["global"]), *_outlined(recoloured, wired)]
    for text, outline in pairs:
        scene.labels.append(Label(text.text, "global", text.bbox, text.angle, outline))
        used.add(id(outline))
        ported.add(id(text))
    for text in label_texts["local"]:
        if id(text) not in ported:
            scene.labels.append(Label(text.text, "local", text.bbox, text.angle))
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


def _with_wire_colour(paths: list[Path], profile: Profile) -> Profile:
    """Add the page's own wire colour: the colour of the lines that end on pin ends.

    Some designers change the wire colour, so the default one finds nothing.
    """
    pin_ends = GridIndex(cell=1.0)
    ends = []
    for p in paths:
        if profile.is_("pin", p.stroke) and len(p.subpaths[0]) == 2:
            for end in p.subpaths[0]:
                pin_ends.add(len(ends), (*end, *end))
                ends.append(end)
    known = set().union(*profile.colors.values())
    hits = Counter()
    for p in paths:
        if p.fill or not p.stroke or p.stroke in known:
            continue
        for sub in p.subpaths:
            for end in (sub[0], sub[-1]):
                if any(geometry.distance(end, ends[k]) < 0.05 for k in pin_ends.near(end, 0.05)):
                    hits[p.stroke] += 1
    if not hits or hits.most_common(1)[0][1] < MIN_COLOUR_HITS:
        return profile
    colour = hits.most_common(1)[0][0]
    return replace(profile, colors={**profile.colors, "wire": profile.colors["wire"] | {colour}})


def _with_body_colours(paths: list[Path], profile: Profile) -> Profile:
    """Add body colours of the page: colours of outlines that pins start from.

    Pins meet a body square on, partway along its edge, which a wire never does,
    nor the diagonal cross of a no-connect mark.
    """
    known = set().union(*profile.colors.values())
    outlines = GridIndex()
    candidates = [p for p in paths if p.stroke and p.stroke not in known]
    for k, p in enumerate(candidates):
        outlines.add(k, p.bbox)
    hits = Counter()
    for p in paths:
        if not profile.is_("pin", p.stroke) or len(p.subpaths[0]) != 2:
            continue
        along = geometry.unit(*p.subpaths[0])
        for end in p.subpaths[0]:
            for k in outlines.near(end, 0.05):
                other = candidates[k]
                if any(
                    geometry.is_interior(end, seg, 0.05) and _square(along, geometry.unit(*seg))
                    for sub in other.subpaths
                    for seg in geometry.segments(sub)
                ):
                    hits[other.stroke] += 1
    found = {c for c, n in hits.items() if n >= MIN_COLOUR_HITS}
    if not found:
        return profile
    return replace(profile, colors={**profile.colors, "symbol": profile.colors["symbol"] | found})


def _square(a: Point, b: Point) -> bool:
    return abs(a[0] * b[0] + a[1] * b[1]) < 0.1


def _is_wire(path: Path, drawn_with_wires: set[int], profile: Profile) -> bool:
    if profile.is_("wire", path.stroke):
        return True
    return path.seq in drawn_with_wires and not profile.is_("note", path.stroke)


def _segments(path: Path) -> list[Segment]:
    return [s for sub in path.subpaths for s in geometry.segments(sub) if s[0] != s[1]]


def _is_hop(path: Path) -> bool:
    """A small arc drawn where a wire crosses another without joining it."""
    x0, y0, x1, y1 = path.bbox
    return path.curved and max(x1 - x0, y1 - y0) < 2.0 and not _closed(path.subpaths[0])


def _chords(path: Path) -> list[Segment]:
    return [(sub[0], sub[-1]) for sub in path.subpaths if sub[0] != sub[-1]]


def _thick_lines(paths: list[Path], profile: Profile) -> set[int]:
    """Wire-coloured lines much thicker than the usual wire on the page: buses.

    Pages are often scaled to fit the paper, so only relative thickness means anything.
    """
    wires = [p for p in paths if profile.is_("wire", p.stroke) and not p.fill and not p.curved]
    if not wires:
        return set()
    usual = Counter(round(p.width, 3) for p in wires).most_common(1)[0][0]
    return {p.seq for p in wires if p.width > BUS_WIDTH_RATIO * usual}


def _drawn_with_wires(paths: list[Path], texts: list[Text], profile: Profile, kind) -> set[int]:
    """Paths of one kind drawn in an unbroken run with wire-coloured ones.

    Wires take the colour of their net class, so colour alone misses some. A
    generator that draws all wires in one run lets drawing order find them.
    """
    items = sorted([(p.seq, p) for p in paths] + [(t.seq, None) for t in texts], key=lambda i: i[0])
    found, run = set(), []
    for _, path in [*items, (None, None)]:
        if path is not None and kind(path):
            run.append(path)
            continue
        if any(profile.is_("wire", p.stroke or p.fill) for p in run):
            found |= {p.seq for p in run}
        run = []
    return found


def _is_line(path: Path) -> bool:
    return (
        path.stroke is not None
        and path.fill is None
        and len(path.subpaths) == 1
        and len(path.subpaths[0]) == 2
        and path.subpaths[0][0] != path.subpaths[0][1]
    )


def _is_dot_or_ring(path: Path) -> bool:
    """A junction dot, or the outline some generators draw around it."""
    x0, y0, x1, y1 = path.bbox
    return path.curved and max(x1 - x0, y1 - y0) < 2.0 and (path.fill or _closed(path.subpaths[0]))


def _is_dot(path: Path) -> bool:
    x0, y0, x1, y1 = path.bbox
    return path.fill is not None and path.curved and max(x1 - x0, y1 - y0) < 2.0


def _find_sheets(
    scene: Scene,
    files: list[Text],
    pin_outlines: list[list[Point]],
    bus_texts: list[Text],
    outlines: list[list[Point]],
) -> set[int]:
    """Find sheet boxes by their file text, and take their names and pins out of the texts.

    Returns the ids of the box outlines, which are not symbol graphics.
    """
    boxes = [(geometry.bbox_of(o), o) for o in outlines]
    used = set()
    for file in files:
        fx0, fy0, _, fy1 = file.bbox
        # The file name sits below the box's left corner, or above it for short sheets.
        found = [
            (b, o)
            for b, o in boxes
            if abs(b[0] - fx0) < 1
            and (0 <= fy0 - b[3] < SHEET_TEXT_GAP or -0.5 <= b[1] - fy1 < SHEET_TEXT_GAP)
        ]
        if not found:
            continue
        box, outline = found[0]
        x0, y0, x1, y1 = box
        top = min(y0, fy0)
        # Large names leave a wider gap when no letter reaches below the line.
        names = [
            t
            for t in scene.fields
            if abs(t.bbox[0] - x0) < 1 and 0 <= top - t.bbox[3] < max(SHEET_TEXT_GAP, 0.75 * t.size)
        ]
        if not names:
            continue
        sheet = Sheet(names[0].text, box)
        taken = [names[0]]
        for pin_outline in pin_outlines:
            pin_box = geometry.bbox_of(pin_outline)
            at = _on_edge(pin_box, box)
            if at is None:
                continue
            text = min(scene.fields + bus_texts, key=lambda t: geometry.bbox_gap(t.bbox, pin_box))
            if geometry.bbox_gap(text.bbox, pin_box) < 1.5:
                sheet.pins.append(SheetPin(text.text, at))
                taken.append(text)
        scene.fields = [t for t in scene.fields if not any(t is u for u in taken)]
        bus_texts[:] = [t for t in bus_texts if not any(t is u for u in taken)]
        scene.sheets.append(sheet)
        used.add(id(outline))
    return used


def _closed(points: list[Point]) -> bool:
    return len(points) > 2 and geometry.distance(points[0], points[-1]) < 1e-3


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


def _meets_wire(outline: list[Point], wires: list[Segment], index: GridIndex) -> bool:
    """True if a wire touches the outline, at a corner or partway along an edge."""
    box = geometry.bbox_of(outline)
    if min(box[2] - box[0], box[3] - box[1]) > LABEL_OUTLINE_MAX_HEIGHT:
        return False
    edges = list(geometry.segments(outline))
    for k in index.within((box[0] - 0.05, box[1] - 0.05, box[2] + 0.05, box[3] + 0.05)):
        wire = wires[k]
        if any(geometry.distance_to_segment(v, wire) <= 0.05 for v in outline) or any(
            geometry.distance_to_segment(end, e) <= 0.05 for end in wire for e in edges
        ):
            return True
    return False


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
    # A designator is a field of its own, even when the value is drawn next to it.
    # Text written a letter or two at a time still joins up.
    if is_common_ref(prev.text) and prev.text[-1].isdigit():
        spaced = start - end > 0.25 * prev.size
        glued = (
            len(text.text) >= 3
            and any(c.isalpha() for c in text.text)
            and not is_common_ref(prev.text + text.text)
        )
        if spaced or glued:
            return False
    lo_a, hi_a = _across(prev.bbox, prev.angle)
    lo_b, hi_b = _across(text.bbox, text.angle)
    # An underscore sits below the other letters, so allow a small vertical gap.
    beside = min(hi_a, hi_b) > max(lo_a, lo_b) - 0.3 * prev.size
    return -0.5 <= start - end <= 0.8 * prev.size and beside


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
