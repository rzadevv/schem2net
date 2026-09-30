"""Stages 5, 7 and 8: join wires, pins and labels into nets.

Every join is recorded with its kind. A net's confidence is the weight of its
weakest join, so a net held together by one guess is marked as such.
"""

from collections import Counter, defaultdict

from schem2net import buses as busnames
from schem2net import geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.ir import Component, Evidence, Issue, Net
from schem2net.ir import Pin as PinOut
from schem2net.primitives import Point
from schem2net.scene import Label, Scene, name_key
from schem2net.symbols import Pin, Symbol

TOL = 0.05  # mm; KiCad places connections exactly
LABEL_GAP = 1.5  # mm between a local label's baseline and its wire

WEIGHTS = {
    "exact": 1.0,
    "junction": 1.0,
    "direct": 0.95,
    "global_name": 0.95,
    "local_name": 0.95,
    "hier_name": 0.95,
    "label": 0.9,
    "bus": 0.9,
    "t_contact": 0.85,
}
LONE_PIN_CONFIDENCE = 0.5


class Netlister:
    def __init__(self):
        self.uf = UnionFind()
        self.edges: list[tuple[tuple, tuple, str]] = []
        self.names: dict[tuple, str] = {}
        self.pins: list[tuple[tuple, int, Symbol, Pin]] = []
        self.local_names: dict[int, set[str]] = defaultdict(set)
        # Buses crossing into child sheets: (page, child path, name) -> bus on this page
        self.sheet_buses: list[tuple[int, str, str, busnames.Bus]] = []
        # Bus labels on child pages: (path, name) -> (page, bus)
        self.label_buses: dict[tuple[str, str], list[tuple[int, busnames.Bus]]] = defaultdict(list)

    def join(self, a: tuple, b: tuple, kind: str) -> None:
        self.uf.union(a, b)
        self.edges.append((a, b, kind))

    def add_page(self, scene: Scene, symbols: list[Symbol]) -> None:
        page = scene.page
        wires = scene.wires
        wire_index = GridIndex()
        for i, seg in enumerate(wires):
            wire_index.add(i, geometry.bbox_of(seg))
            self.uf.find(("w", page, i))

        dots = GridIndex()
        for k, (x, y) in enumerate(scene.junctions):
            dots.add(k, (x, y, x, y))

        def dotted(p: Point) -> bool:
            return any(geometry.distance(p, scene.junctions[k]) <= TOL for k in dots.near(p, TOL))

        for i, seg in enumerate(wires):
            for end in seg:
                for j in wire_index.near(end, TOL):
                    if j != i:
                        self._touch(("w", page, i), end, ("w", page, j), wires[j], dotted)

        for c in scene.junctions:
            through = [
                j
                for j in wire_index.near(c, TOL)
                if geometry.distance_to_segment(c, wires[j]) <= TOL
            ]
            for j in through[1:]:
                self.join(("w", page, through[0]), ("w", page, j), "junction")

        buses = scene.buses
        bus_index = GridIndex()
        vector_labels: list[tuple[tuple, Label, busnames.Bus]] = []
        # Buses crossing sheets, named once this page's buses are joined: (node, at, key, bus)
        crossings: list[tuple[tuple, Point, tuple, busnames.Bus]] = []
        for i, seg in enumerate(buses):
            bus_index.add(i, geometry.bbox_of(seg))
            self.uf.find(("b", page, i))
        for i, seg in enumerate(buses):
            for end in seg:
                for j in bus_index.near(end, TOL):
                    if j != i and geometry.distance_to_segment(end, buses[j]) <= TOL:
                        self.join(("b", page, i), ("b", page, j), "bus")

        points: list[tuple[Point, tuple]] = []
        bus_points: list[tuple[Point, tuple]] = []
        pin_lines: list[tuple[Segment, tuple]] = []
        for si, symbol in enumerate(symbols):
            if symbol.power:
                node = ("s", page, si)
                self.names[node] = symbol.power
                self.join(node, ("global", name_key(symbol.power)), "global_name")
                points += [(p, node) for p in symbol.anchors]
                continue
            for pin in symbol.pins:
                node = ("p", page, pin.shape)
                self.uf.find(node)
                self.pins.append((node, page, symbol, pin))
                points.append((pin.at, node))
                pin_lines.append((pin.line, node))

        for li, label in enumerate(scene.labels):
            node = ("l", page, li)
            key = name_key(label.text)
            self.names[node] = label.text
            if label.kind == "global":
                self.join(node, ("global", key), "global_name")
            else:
                self.join(node, ("local", page, key), "local_name")
                self.local_names[page].add(key)
            bus = busnames.parse(label.text)
            if label.kind == "hier" and scene.path:
                self.join(node, ("hier", scene.path, key), "hier_name")
                if bus and label.outline:
                    crossings.append((node, label.outline[0], ("label", scene.path, key), bus))
            if label.kind == "bus":
                target = _under_label(label, buses, bus_index, [], ("b", page))
                if target:
                    self.join(node, target, "label")
                    if bus and bus.vector:
                        vector_labels.append((target, label, bus))
            elif label.outline:
                tips = [(v, node) for v in _label_tips(label)]
                (bus_points if bus else points).extend(tips)
            else:
                target = _under_label(label, wires, wire_index, pin_lines, ("w", page))
                if target:
                    self.join(node, target, "label")

        # A sheet pin on this page is the same net as the matching label on the child page.
        for si, sheet in enumerate(scene.sheets if scene.path else []):
            child = scene.path + name_key(sheet.name) + "/"
            for k, pin in enumerate(sheet.pins):
                node = ("sp", page, si, k)
                key = name_key(pin.name)
                self.names[node] = pin.name
                self.join(node, ("hier", child, key), "hier_name")
                bus = busnames.parse(pin.name)
                if not bus:
                    points.append((pin.at, node))
                    continue
                bus_points.append((pin.at, node))
                crossings.append((node, pin.at, ("sheet", child, key), bus))

        for p, node in bus_points:
            self._join_near(p, node, buses, bus_index, page)
        for node, at, (side, path, key), bus in crossings:
            if bus.vector:
                bus = self._named_on_page(at, node, bus, vector_labels)
            if side == "sheet":
                self.sheet_buses.append((page, path, key, bus))
            else:
                self.label_buses[path, key].append((page, bus))

        point_index = GridIndex()
        for k, (p, _) in enumerate(points):
            point_index.add(k, (p[0], p[1], p[0], p[1]))
        for p, node in points:
            for j in wire_index.near(p, TOL):
                self._touch(node, p, ("w", page, j), wires[j], dotted)
            for m in point_index.near(p, TOL):
                q, other = points[m]
                if other != node and geometry.distance(p, q) <= TOL:
                    self.join(node, other, "direct")

    def _touch(self, node: tuple, p: Point, wire: tuple, seg: Segment, dotted) -> None:
        """Join a point to a wire it touches: at an end, or partway along it."""
        if min(geometry.distance(p, seg[0]), geometry.distance(p, seg[1])) <= TOL:
            self.join(node, wire, "exact")
        elif geometry.distance_to_segment(p, seg) <= TOL:
            self.join(node, wire, "junction" if dotted(p) else "t_contact")

    def _join_near(self, p: Point, node: tuple, buses: list[Segment], index: GridIndex, page: int):
        for j in index.near(p, TOL):
            if geometry.distance_to_segment(p, buses[j]) <= TOL:
                self.join(node, ("b", page, j), "bus")

    def _named_on_page(self, at: Point, node: tuple, bus: busnames.Bus, labels) -> busnames.Bus:
        """The names a vector bus's members have on this page.

        They come from the nearest bus label of the same width on the same bus,
        such as D[8..15] on the branch leading to a sheet pin named D[0..7].
        """
        own = self.uf.find(node)
        same = [
            (geometry.bbox_gap(label.bbox, (*at, *at)), other)
            for segment, label, other in labels
            if self.uf.find(segment) == own and len(other.members) == len(bus.members)
        ]
        return min(same, key=lambda s: s[0])[1] if same else bus

    def _join_bus_members(self) -> None:
        """Join the member nets of each bus crossing into a child sheet."""
        for page, child, key, bus in self.sheet_buses:
            for child_page, child_bus in self.label_buses.get((child, key), []):
                if child_bus.vector != bus.vector:
                    continue
                up = busnames.member_nets(bus, self.local_names[page])
                down = busnames.member_nets(child_bus, self.local_names[child_page])
                for member in up.keys() & down.keys() if bus.vector else up.keys() | down.keys():
                    above = up.get(member, bus.prefix + bus.separator + member)
                    below = down.get(member, child_bus.prefix + child_bus.separator + member)
                    self.join(("local", page, above), ("local", child_page, below), "bus")

    def result(self) -> tuple[list[Component], list[Net], list[Issue]]:
        self._join_bus_members()
        find = self.uf.find
        kinds: dict[tuple, Counter] = defaultdict(Counter)
        for a, _, kind in self.edges:
            kinds[find(a)][kind] += 1
        names: dict[tuple, Counter] = defaultdict(Counter)
        for node, name in self.names.items():
            names[find(node)][name] += 1

        components: dict[str, Component] = {}
        members: dict[tuple, set[tuple[str, str]]] = defaultdict(set)
        pages: dict[tuple, set[int]] = defaultdict(set)
        issues = []
        for node, page, symbol, pin in self.pins:
            comp = components.setdefault(
                symbol.ref,
                Component(ref=symbol.ref, value=symbol.value, page=page, bbox=symbol.bbox),
            )
            if symbol.unit and symbol.unit not in comp.units:
                comp.units.append(symbol.unit)
            if pin.number is None:
                issues.append(Issue(kind="unnumbered_pin", page=page, at=pin.at))
                continue
            comp.pins.append(PinOut(num=pin.number, at=pin.at))
            root = find(node)
            members[root].add((symbol.ref, pin.number))
            pages[root].add(page)

        nets = []
        for root, pins in members.items():
            if len(pins) < 2 and not kinds[root]:
                continue  # an unconnected pin
            confidence = min((WEIGHTS[k] for k in kinds[root]), default=1.0)
            if len(pins) < 2:
                confidence = min(confidence, LONE_PIN_CONFIDENCE)
            seen = [name for name, _ in names[root].most_common()]
            nets.append(
                Net(
                    id="",
                    name=seen[0] if seen else None,
                    names_seen=seen,
                    pins=sorted(pins),
                    confidence=confidence,
                    evidence=[Evidence(type=k, count=n) for k, n in sorted(kinds[root].items())],
                    pages=sorted(pages[root]),
                )
            )
        nets.sort(key=lambda n: (n.name is None, n.name or "", n.pins))
        for i, net in enumerate(nets, 1):
            net.id = f"n{i}"
        return sorted(components.values(), key=lambda c: c.ref), nets, issues


def _label_tips(label: Label) -> list[Point]:
    """Outline corners on the text's centre line: the connecting tip and the far end."""
    cx, cy = geometry.center(label.bbox)
    vertical = round(label.angle) % 180 == 90
    return [v for v in label.outline if abs((v[0] - cx) if vertical else (v[1] - cy)) < 0.3]


def _under_label(
    label: Label,
    wires: list[Segment],
    wire_index: GridIndex,
    pin_lines: list[tuple[Segment, tuple]],
    node_of: tuple,
) -> tuple | None:
    """The wire or pin a label without an outline sits on: parallel, just below its baseline."""
    x0, y0, x1, y1 = label.bbox
    vertical = round(label.angle) % 180 == 90
    region = (x0 - LABEL_GAP, y0 - LABEL_GAP, x1 + LABEL_GAP, y1 + LABEL_GAP)
    candidates = [(wires[j], (*node_of, j)) for j in wire_index.within(region)]
    candidates += [
        (line, node)
        for line, node in pin_lines
        if geometry.bbox_gap(region, geometry.bbox_of(line)) == 0
    ]

    best = None
    for seg, node in candidates:
        if geometry.is_horizontal(seg) == vertical:
            continue
        if vertical:
            gap = seg[0][0] - x1
            lo, hi, a, b = y0, y1, seg[0][1], seg[1][1]
        else:
            gap = seg[0][1] - y1
            lo, hi, a, b = x0, x1, seg[0][0], seg[1][0]
        overlaps = min(a, b) <= hi + 0.5 and max(a, b) >= lo - 0.5
        if -0.2 <= gap <= LABEL_GAP and overlaps and (best is None or gap < best[0]):
            best = (gap, node)
    return best[1] if best else None
