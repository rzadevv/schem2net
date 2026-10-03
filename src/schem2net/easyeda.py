"""Read the netlist of an EasyEDA Std schematic (.json).

Used as ground truth for EasyEDA PDFs. The file stores drawing, not nets: each
sheet is a list of shapes in EasyEDA's "~"-separated records. Wires, part pins,
net flags and net labels that share a point are one net, as are wire corners and
points where a wire end meets another wire; flags and labels of one name join
their nets across sheets. Coordinates in the file are exact, so points are
matched as they are written.
"""

import json
from collections import defaultdict
from pathlib import Path

from schem2net.geometry import UnionFind
from schem2net.ir import Component, Design, Net, Pin, Source

Point = tuple[float, float]


def read(path: str | Path) -> Design:
    data = json.loads(Path(path).read_text())
    sheets = data.get("schematics") or [{"dataStr": data}]  # a project, or one sheet
    nets = UnionFind()
    names: dict[str, list] = defaultdict(list)  # net name -> nodes
    pins: list[tuple[str, str, str, object]] = []  # ref, pad, pin name, node
    parts: dict[str, Component] = {}
    for k, sheet in enumerate(sheets):
        body = sheet.get("dataStr") or {}
        if isinstance(body, str):  # older versions store each sheet as a JSON string
            body = json.loads(body)
        shapes = body.get("shape", [])
        _sheet(k, shapes, nets, names, pins, parts)
    for nodes in names.values():
        for node in nodes[1:]:
            nets.union(nodes[0], node)

    members: dict[object, set[tuple[str, str]]] = defaultdict(set)
    for ref, pad, _, node in pins:
        members[nets.find(node)].add((ref, pad))
    named = {nets.find(nodes[0]): name for name, nodes in sorted(names.items())}
    out = []
    for i, (root, members_) in enumerate(sorted(members.items(), key=lambda kv: min(kv[1])), 1):
        name = named.get(root)
        out.append(
            Net(id=f"n{i}", name=name, names_seen=[name] if name else [], pins=sorted(members_))
        )
    source = Source(file=Path(path).name, generator="easyeda", pages=len(sheets))
    return Design(source=source, components=sorted(parts.values(), key=lambda c: c.ref), nets=out)


def _sheet(k, shapes, nets, names, pins, parts) -> None:
    def node(p: Point):
        return ("p", k, round(p[0], 3), round(p[1], 3))

    segments: list[tuple[Point, Point]] = []
    ends: list[Point] = []
    for shape in shapes:
        kind, _, rest = shape.partition("~")
        if kind == "W":
            points = _points(rest.split("~")[0])
            for a, b in zip(points, points[1:], strict=False):
                nets.union(node(a), node(b))
                segments.append((a, b))
            ends += [points[0], points[-1]]
        elif kind == "F":  # net flag: power, ground or a named port
            head, anchor, label, *_ = shape.split("^^") + ["", ""]
            at = _point(anchor)
            name = label.split("~")[0].strip()
            if at and name:
                names[name].append(node(at))
                ends.append(at)
        elif kind == "N":  # net label
            fields = rest.split("~")
            at, name = (float(fields[0]), float(fields[1])), fields[4].strip()
            if name:
                names[name].append(node(at))
                ends.append(at)
        elif kind == "LIB":
            _part(shape, node, pins, parts, ends)
    # A wire end, flag or pin landing on the middle of a wire joins it, as EasyEDA does.
    for p in ends:
        for a, b in segments:
            if p not in (a, b) and _on_segment(p, a, b):
                nets.union(node(p), node(a))


def _part(shape, node, pins, parts, ends) -> None:
    head, *items = shape.split("#@$")
    attrs = _attributes(head.split("~")[3])
    ref = value = None
    for item in items:
        fields = item.split("~")
        if fields[0] != "T" or len(fields) < 13:
            continue
        if fields[1] == "P":  # the designator; "PK" is the package
            ref = fields[12].strip()
        elif fields[1] == "N":
            value = fields[12].strip()
    if not ref or ref.startswith("#") or attrs.get("package", "") in ("", "NONE"):
        return  # a frame, logo or symbol with no footprint: not a component
    ref = ref.split(".")[0]  # parts of one package are "U1.1", "U1.2"
    part = parts.setdefault(ref, Component(ref=ref, value=value, pins=[]))
    for item in items:
        if not item.startswith("P~"):
            continue
        segments = item.split("^^")
        at = _point(segments[1])
        name = segments[3].split("~")[4].strip() if len(segments) > 3 else ""
        number = segments[4].split("~")[4].strip() if len(segments) > 4 else ""
        number = number or segments[0].split("~")[3].strip()
        if at is None or not number:
            continue
        part.pins.append(Pin(num=number, name=name or None))
        pins.append((ref, number, name, node(at)))
        ends.append(at)


def _attributes(text: str) -> dict[str, str]:
    values = text.split("`")
    return dict(zip(values[0::2], values[1::2], strict=False))


def _points(text: str) -> list[Point]:
    values = [float(v) for v in text.split()]
    return list(zip(values[0::2], values[1::2], strict=False))


def _point(text: str) -> Point | None:
    fields = text.split("~")
    try:
        return float(fields[0]), float(fields[1])
    except (ValueError, IndexError):
        return None


def _on_segment(p: Point, a: Point, b: Point) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > 1e-6:
        return False
    return (
        min(ax, bx) - 1e-6 <= px <= max(ax, bx) + 1e-6
        and min(ay, by) - 1e-6 <= py <= max(ay, by) + 1e-6
    )
