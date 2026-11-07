"""Stages 5, 7 and 8: join wires, pins and labels into nets.

Every join is recorded with its kind. A net's confidence is the weight of its
weakest join, so a net held together by one guess is marked as such.
"""

import re
from collections import Counter, defaultdict
from typing import NamedTuple

from schem2net import buses as busnames
from schem2net import geometry
from schem2net.geometry import GridIndex, Segment, UnionFind
from schem2net.ir import UNNUMBERED, Component, Evidence, Issue, Net
from schem2net.ir import Pin as PinOut
from schem2net.primitives import Point
from schem2net.refdes import REFDES, TWO_TERMINAL_PREFIXES, is_common_ref, split_ref
from schem2net.scene import Label, Scene, name_key
from schem2net.symbols import Pin, Symbol

TOL = 0.05  # mm; KiCad places connections exactly
NO_CONNECT_REACH = 0.3  # mm from a pin's tip to the middle of its no-connect cross, as printed
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
    "shared_pin": 0.95,  # one pin drawn in several units
    "dangling": 0.6,  # a wire end touching nothing: often a connection that was missed
    # A page known by a power name only where it is hidden, such as a ground sign's,
    # joined to the pages of that name: the name is the generator's usual one, and
    # modules of one design may each name their ground apart.
    "hidden_name": 0.7,
}
LONE_PIN_CONFIDENCE = 0.5
# Consistency checks: a net that fails one is capped at this confidence.
MERGED_POWER_CONFIDENCE = 0.4  # two power names on one net: a short somewhere
DUPLICATE_PIN_CONFIDENCE = 0.6  # a pin number used twice in one part
DUPLICATE_REF_CONFIDENCE = 0.6  # one designator on two parts: a copy, or a misread
PIECE_GAP = 0.5  # mm; parts of one designator this close are pieces of one drawing
UNANNOTATED = re.compile(r"^[A-Za-z]{1,4}\?+[A-Z]?$")  # R?, U?A: a part not yet numbered
# Check textual supply conflicts for distinct voltages, or voltage and
# ground. Names such as VCC and VDD may intentionally alias the same rail.
VOLTAGE_NAME = re.compile(r"[+-]?(?:\d+(?:\.\d+)?V|\d+V\d+)", re.I)


class Result(NamedTuple):
    components: list[Component]
    nets: list[Net]
    issues: list[Issue]
    wire_nets: dict[tuple[int, int], str]  # (page, wire index) -> net id, for drawing


class Netlister:
    def __init__(
        self,
        labels_span_pages: bool = False,
        designators: frozenset = frozenset(),
        case_blind: bool = False,
        not_nets: frozenset = frozenset(),
    ):
        # Net labels with one name are one net on every page, unless sheets are nested.
        self.labels_span_pages = labels_span_pages
        self.case_blind = case_blind
        self.designators = designators  # the designators' own colours, where they have one
        # Names of symbols drawn like power symbols that join nothing by name, as PWR_FLAG:
        # a wire ending on one ends on something, but no net takes its name.
        self.not_nets = not_nets
        self.nested = False
        self.no_connect: set[tuple] = set()  # pins flagged as left unconnected on purpose
        self.uf = UnionFind()
        self.edges: list[tuple[tuple, tuple, str]] = []
        self.names: dict[tuple, str] = {}
        self.pins: list[tuple[tuple, int, Symbol, Pin]] = []
        self.local_names: dict[int, set[str]] = defaultdict(set)
        # Pages of each global name: where it is printed, and where it is hidden.
        self.printed_pages: dict[str, set[int]] = defaultdict(set)
        self.hidden_pages: dict[str, set[int]] = defaultdict(set)
        self.issues: list[Issue] = []
        # Buses crossing into child sheets: (page, child path, name) -> bus on this page
        self.sheet_buses: list[tuple[int, str, str, busnames.Bus]] = []
        # Bus labels on child pages: (path, name) -> (page, bus)
        self.label_buses: dict[tuple[str, str], list[tuple[int, busnames.Bus]]] = defaultdict(list)
        # Nodes that name a group bus, with the bus they name: (page, node, bus)
        self.group_names: list[tuple[int, tuple, busnames.Bus]] = []
        self.renamed: set[tuple] = set()  # sheet pins whose bus a label names

    def _key(self, name: str) -> str:
        """A net name as names are matched: in capitals too where case tells nothing."""
        key = name_key(name)
        return key.upper() if self.case_blind else key

    def join(self, a: tuple, b: tuple, kind: str) -> None:
        self.uf.union(a, b)
        self.edges.append((a, b, kind))

    def add_page(self, scene: Scene, symbols: list[Symbol]) -> None:
        page = scene.page
        # A designator no part claimed usually means a part was missed.
        named = {s.ref for s in symbols if s.ref}
        bodies = [s.body for s in symbols if s.body]
        for text in scene.fields:
            if UNANNOTATED.match(text.text.strip()):
                c = geometry.center(text.bbox)
                self.issues.append(
                    Issue(kind="unannotated_part", page=page, at=c, detail=text.text.strip())
                )
                continue
            match = split_ref(text.text)
            if not is_common_ref(text.text) or match.group(1) + match.group(2) in named:
                continue
            if self.designators and text.color not in self.designators:
                continue  # a pin number such as A6
            c = geometry.center(text.bbox)
            if not any(b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3] for b in bodies):
                self.issues.append(
                    Issue(kind="designator_without_part", page=page, at=c, detail=text.text)
                )
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

        buses = scene.buses
        bus_index = GridIndex()
        for i, seg in enumerate(buses):
            bus_index.add(i, geometry.bbox_of(seg))
            self.uf.find(("b", page, i))

        def on_bus(p: Point) -> bool:
            return any(_on(p, buses[j]) for j in bus_index.near(p, TOL))

        plain_crossings: dict[Point, bool] = {}
        for i, seg in enumerate(wires):
            for end in seg:
                near = wire_index.near(end, TOL)
                if end not in plain_crossings:
                    plain_crossings[end] = not dotted(end) and _crosses(
                        end, [wires[j] for j in near]
                    )
                on = on_bus(end)
                for j in near:
                    if j != i:
                        # A slanted bus entry joins the bus where it meets other wires on
                        # it, not them: a bus carries its members by name.
                        if on and (_slanted(seg) or _slanted(wires[j])):
                            continue
                        # A PDF can split a continuous wire at a plain crossing.
                        # Its artificial end is not a T-contact with the other axis.
                        if (
                            plain_crossings[end]
                            and geometry.is_axis_aligned(seg)
                            and geometry.is_axis_aligned(wires[j])
                            and geometry.is_horizontal(seg) != geometry.is_horizontal(wires[j])
                            and geometry.is_interior(end, wires[j], TOL)
                        ):
                            continue
                        self._touch(("w", page, i), end, ("w", page, j), wires[j], dotted)

        for c in scene.junctions:
            through = [
                j
                for j in wire_index.near(c, TOL)
                if geometry.distance_to_segment(c, wires[j]) <= TOL
            ]
            for j in through[1:]:
                self.join(("w", page, through[0]), ("w", page, j), "junction")

        labelled: set[int] = set()
        vector_labels: list[tuple[tuple, Label, busnames.Bus]] = []
        # Buses crossing sheets, named once this page's buses are joined: (node, at, key, bus)
        crossings: list[tuple[tuple, Point, tuple, busnames.Bus]] = []
        for i, seg in enumerate(buses):
            for end in seg:
                for j in bus_index.near(end, TOL):
                    if j != i and geometry.distance_to_segment(end, buses[j]) <= TOL:
                        self.join(("b", page, i), ("b", page, j), "bus")

        points: list[tuple[Point, tuple]] = []
        bus_points: list[tuple[Point, tuple]] = []
        pin_lines: list[tuple[Segment, tuple]] = []
        ports: set[tuple] = set()
        for si, symbol in enumerate(symbols):
            if symbol.power in self.not_nets:
                points += [(p, ("s", page, si)) for p in symbol.anchors]
                continue
            if symbol.power:
                node = ("s", page, si)
                self.names[node] = symbol.power
                key = self._key(symbol.power)
                if symbol.power_hidden:
                    self.hidden_pages[key].add(page)
                    self.join(node, ("hidden", page, key), "global_name")
                else:
                    self.printed_pages[key].add(page)
                    self.join(node, ("global", key), "global_name")
                points += [(p, node) for p in symbol.anchors]
                ports.add(node)
                continue
            for pin in symbol.pins:
                node = ("p", page, pin.shape)
                self.uf.find(node)
                self.pins.append((node, page, symbol, pin))
                if any(geometry.distance(pin.at, c) <= NO_CONNECT_REACH for c in scene.no_connects):
                    self.no_connect.add(node)
                points.append((pin.at, node))
                pin_lines.append((pin.line, node))

        pin_index = GridIndex()
        for k, (line, _) in enumerate(pin_lines):
            pin_index.add(k, geometry.bbox_of(line))
        for li, label in enumerate(scene.labels):
            node = ("l", page, li)
            key = self._key(label.text)
            self.names[node] = label.text
            if label.kind == "global":
                self.printed_pages[key].add(page)
                self.join(node, ("global", key), "global_name")
            else:
                self.join(node, ("local", page, key), "local_name")
                self.local_names[page].add(key)
            bus = busnames.parse(label.text)
            if bus and not bus.vector:
                self.group_names.append((page, node, bus))
            if label.kind == "hier" and scene.path:
                self.join(node, ("hier", scene.path, key), "hier_name")
                if bus and label.outline:
                    crossings.append((node, label.outline[0], ("label", scene.path, key), bus))
            if label.kind == "bus" or (bus and not label.outline):
                target = _under_label(label, buses, bus_index, [], None, ("b", page))
                if target:
                    self.join(node, target, "label")
                    if bus and bus.vector:
                        vector_labels.append((target, label, bus))
            elif label.outline:
                tips = [(v, node) for v in _label_tips(label)]
                (bus_points if bus else points).extend(tips)
            else:
                target = _under_label(label, wires, wire_index, pin_lines, pin_index, ("w", page))
                if target:
                    self.join(node, target, "label")
                    if target[0] == "w":
                        labelled.add(target[2])
                else:
                    at = geometry.center(label.bbox)
                    self.issues.append(
                        Issue(kind="unattached_label", page=page, at=at, detail=label.text)
                    )

        # A sheet pin on this page is the same net as the matching label on the child page.
        self.nested |= bool(scene.sheets)
        for si, sheet in enumerate(scene.sheets if scene.path else []):
            child = scene.path + name_key(sheet.name) + "/"
            for k, pin in enumerate(sheet.pins):
                node = ("sp", page, si, k)
                key = self._key(pin.name)
                self.names[node] = pin.name
                self.join(node, ("hier", child, key), "hier_name")
                bus = busnames.parse(pin.name)
                if not bus:
                    points.append((pin.at, node))
                    continue
                if not bus.vector:
                    self.group_names.append((page, node, bus))
                bus_points.append((pin.at, node))
                crossings.append((node, pin.at, ("sheet", child, key), bus))

        for p, node in bus_points:
            self._join_near(p, node, buses, bus_index, page)
        for node, at, (side, path, key), bus in crossings:
            if bus.vector:
                bus = self._named_on_page(at, node, bus, vector_labels)
            elif side == "sheet":
                bus = self._labelled_on_page(page, node, bus)
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

        # A power port placed over the end of a pin, rather than at its tip.
        for p, node in points:
            if node in ports:
                for k in pin_index.near(p, TOL):
                    line, pin = pin_lines[k]
                    if geometry.distance_to_segment(p, line) <= TOL:
                        self.join(node, pin, "t_contact")

        # A wire end that touches nothing usually means a connection was missed.
        for i, seg in enumerate(wires):
            if i in labelled:
                continue
            for end in seg:
                touches = (
                    any(j != i and _on(end, wires[j]) for j in wire_index.near(end, TOL))
                    or any(
                        geometry.distance(end, points[m][0]) <= TOL
                        for m in point_index.near(end, TOL)
                    )
                    or any(_on(end, buses[j]) for j in bus_index.near(end, TOL))
                    or any(geometry.distance(end, c) <= NO_CONNECT_REACH for c in scene.no_connects)
                    # On a pin drawn with no line, laid out along its wire.
                    or any(
                        pin_lines[k][1][2] < 0 and _on(end, pin_lines[k][0])
                        for k in pin_index.near(end, TOL)
                    )
                )
                if not touches:
                    self.join(("w", page, i), ("dangling", page, i, end), "dangling")
                    self.issues.append(Issue(kind="dangling_wire", page=page, at=end))

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

    def _labelled_on_page(self, page: int, node: tuple, bus: busnames.Bus) -> busnames.Bus:
        """The names a group bus's members have where it meets a sheet pin: a label on
        the bus names them, as SFP0{SFP} on the bus to a sheet pin SFP{SFP}; the sheet
        pin's own name is what the sheet calls them."""
        own, members = self.uf.find(node), self.names[node].partition("{")[2]
        named = {
            other
            for at, label, other in self.group_names
            if at == page
            and label[0] == "l"
            and self.uf.find(label) == own
            and self.names[label].partition("{")[2] == members
        }
        if len(named) != 1:
            return bus
        self.renamed.add(node)
        return named.pop()

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
        """Join the member nets of each bus crossing into a child sheet. An alias names
        the same members on every sheet, so they are taken from the labels of all of
        them: a sheet that only passes the bus on has none of its own."""
        every = set().union(*self.local_names.values())

        def names(page: int, bus: busnames.Bus) -> set[str]:
            return self.local_names[page] | every if bus.members is None else self.local_names[page]

        for page, child, key, bus in self.sheet_buses:
            for child_page, child_bus in self.label_buses.get((child, key), []):
                if child_bus.vector != bus.vector:
                    continue
                up = busnames.member_nets(bus, names(page, bus))
                down = busnames.member_nets(child_bus, names(child_page, child_bus))
                for member in up.keys() & down.keys() if bus.vector else up.keys() | down.keys():
                    above = up.get(member, bus.prefix + bus.separator + member)
                    below = down.get(member, child_bus.prefix + child_bus.separator + member)
                    self.join(("local", page, above), ("local", child_page, below), "bus")

        # One bus named twice, as DPHY0_C{DPHY} and DPHY0_P{DPHY} where it runs between
        # two sheets that call it each its own way: members of one name are one net.
        on_bus: dict[tuple, list[tuple[int, tuple, busnames.Bus]]] = defaultdict(list)
        for page, node, bus in self.group_names:
            on_bus[self.uf.find(node)].append((page, node, bus))
        for named in on_bus.values():
            # A sheet pin whose bus a label names names only its sheet's side.
            named = [n for n in named if n[1] not in self.renamed]
            buses = {(page, bus.prefix): (page, bus) for page, _, bus in named}
            if len({prefix for _, prefix in buses}) < 2:
                continue
            members = [
                (page, busnames.member_nets(bus, names(page, bus))) for page, bus in buses.values()
            ]
            (first_page, first), *rest = members
            for page, nets in rest:
                for member in first.keys() & nets.keys():
                    self.join(
                        ("local", first_page, first[member]), ("local", page, nets[member]), "bus"
                    )

    def result(self) -> Result:
        self._join_bus_members()
        # A pin drawn in several units of one part is one pad.
        shared: dict[tuple[str, str], dict[str, tuple]] = defaultdict(dict)
        for node, _, symbol, pin in self.pins:
            if pin.number is not None and symbol.unit:
                shared[symbol.ref, pin.number].setdefault(symbol.unit, node)
        for by_unit in shared.values():
            nodes = list(by_unit.values())
            for node in nodes[1:]:
                self.join(nodes[0], node, "shared_pin")
        if self.labels_span_pages and not self.nested:
            for page, keys in self.local_names.items():
                for key in keys:
                    self.join(("local", page, key), ("label", key), "local_name")
        # A net label names the same net as a power symbol or global label of its name on
        # its page.
        for page, keys in self.local_names.items():
            for key in keys:
                if page in self.printed_pages.get(key, ()):
                    self.join(("local", page, key), ("global", key), "local_name")
                elif page in self.hidden_pages.get(key, ()):
                    self.join(("local", page, key), ("hidden", page, key), "local_name")
        for key, hidden in self.hidden_pages.items():
            printed = self.printed_pages[key]
            for page in hidden:
                weak = page not in printed and len(hidden | printed) > 1
                kind = "hidden_name" if weak else "global_name"
                self.join(("hidden", page, key), ("global", key), kind)
        find = self.uf.find
        kinds: dict[tuple, Counter] = defaultdict(Counter)
        for a, _, kind in self.edges:
            kinds[find(a)][kind] += 1
        names: dict[tuple, Counter] = defaultdict(Counter)
        for node, name in self.names.items():
            names[find(node)][name] += 1

        components: dict[str, Component] = {}
        self._pin_numbers: dict[str, dict[str, list[tuple]]] = defaultdict(
            lambda: defaultdict(list)
        )
        members: dict[tuple, set[tuple[str, str]]] = defaultdict(set)
        pages: dict[tuple, set[int]] = defaultdict(set)
        issues = list(self.issues)
        guessed: dict[tuple[str, int], list[tuple]] = defaultdict(list)
        marks: Counter = Counter()  # pins kept unnumbered so far, by part
        for node, page, symbol, pin in self.pins:
            if _doubtful(pin, symbol):
                guessed[symbol.ref, page].append((symbol, pin))
            comp = components.setdefault(
                symbol.ref,
                Component(ref=symbol.ref, value=symbol.value, page=page, bbox=symbol.bbox),
            )
            if symbol.unit and symbol.unit not in comp.units:
                comp.units.append(symbol.unit)
            if pin.number is None:
                # The pin and what it connects to are drawn, its number is not: it stays
                # on its net under a mark, so the connection is not lost with the number.
                marks[symbol.ref] += 1
                number = f"{UNNUMBERED}{marks[symbol.ref]}"
                issues.append(
                    Issue(
                        kind="unnumbered_pin",
                        page=page,
                        at=pin.at,
                        detail=symbol.ref,
                        pins=[(symbol.ref, number)],
                    )
                )
                comp.pins.append(PinOut(num=number, name=pin.name, at=pin.at, how="unnumbered"))
            else:
                number = pin.number
                self._pin_numbers[symbol.ref][number].append((node, (page, symbol.unit)))
                comp.pins.append(PinOut(num=number, at=pin.at, how=pin.how))
            root = find(node)
            members[root].add((symbol.ref, number))
            pages[root].add(page)

        # Numbers the drawing does not show, guessed where libraries disagree.
        for (ref, page), drawn in guessed.items():
            symbol = drawn[0][0]
            issues.append(
                Issue(
                    kind="pin_number_guessed",
                    page=page,
                    detail=ref,
                    at=geometry.center(symbol.bbox),
                    pins=[(ref, pin.number) for _, pin in drawn],
                )
            )

        # Consistency checks. Each failure is reported and caps the confidence of its nets.
        caps: dict[tuple, float] = defaultdict(lambda: 1.0)
        power: dict[tuple, set[str]] = defaultdict(set)
        for node, name in self.names.items():
            if node[0] == "s":
                power[find(node)].add(self._key(name))
        power_issues = {}
        for root, named in names.items():
            keys = {self._key(name) for name in named}
            voltages = {
                key: float(key.upper().rstrip("V").replace("V", "."))
                for key in keys
                if VOLTAGE_NAME.fullmatch(key)
            }
            grounds = {key for key in keys if "GND" in key.upper()}
            found = power[root]
            if (
                len(found) > 1
                or len(set(voltages.values())) > 1
                or (any(voltages.values()) and grounds)
            ):
                found = found | voltages.keys() | grounds
                caps[root] = min(caps[root], MERGED_POWER_CONFIDENCE)
                detail = " and ".join(sorted(found))
                issue = Issue(
                    kind="power_nets_merged",
                    severity="error",
                    detail=detail,
                    pins=sorted(members[root]),
                )
                issues.append(issue)
                power_issues[root] = issue
        # Pins on no net should carry a no-connect flag, and flagged pins should be on none.
        for node, page, symbol, pin in self.pins:
            if pin.number is None:
                continue
            alone = len(members[find(node)]) < 2 and not kinds[find(node)]
            where = {"page": page, "at": pin.at, "detail": f"{symbol.ref}.{pin.number}"}
            if alone and node not in self.no_connect:
                issues.append(Issue(kind="unconnected_pin", severity="info", **where))
            elif not alone and node in self.no_connect:
                issues.append(Issue(kind="connected_no_connect", **where))
        # One designator, and unit, on two parts drawn apart with pin numbers in common:
        # each such pin of one is read as joined to the nets of both. Pieces that touch,
        # as a jumper read in parts, are one drawing; drawings without a number in
        # common are units of one part whose letters are not shown.
        drawn_as: dict[tuple, dict[int, list]] = defaultdict(dict)
        for node, page, symbol, pin in self.pins:
            drawn_as[symbol.ref, symbol.unit].setdefault(id(symbol), []).append(
                (node, page, pin, symbol)
            )
        doubled = set()
        for (ref, unit), parts in drawn_as.items():
            found = list(parts.values())
            numbers = [
                {p.number for k in group for _, _, p, _ in found[k] if p.number}
                for group in _apart([f[0] for f in found])
            ]
            if not any(a & b for i, a in enumerate(numbers) for b in numbers[:i]):
                continue
            doubled.add(ref)
            drawn = [d for found in parts.values() for d in found]
            issues.append(
                Issue(
                    kind="duplicate_designator",
                    severity="error",
                    page=drawn[0][1],
                    detail=ref + (unit or ""),
                    pins=sorted({(ref, p.number) for _, _, p, _ in drawn if p.number}),
                )
            )
            for node, _, _, _ in drawn:
                caps[find(node)] = min(caps[find(node)], DUPLICATE_REF_CONFIDENCE)
        for ref, numbers in self._pin_numbers.items():
            if ref in doubled:
                continue
            for number, drawn in numbers.items():
                units = Counter(unit for _, unit in drawn)
                if any(n > 1 for n in units.values()):
                    page = drawn[0][0][1]
                    issues.append(Issue(kind="duplicate_pin", page=page, detail=f"{ref}.{number}"))
                    for node, _ in drawn:
                        caps[find(node)] = min(caps[find(node)], DUPLICATE_PIN_CONFIDENCE)

        nets, roots = [], {}
        for root, pins in members.items():
            if len(pins) < 2 and not kinds[root]:
                continue  # an unconnected pin, reported below
            confidence = min((WEIGHTS[k] for k in kinds[root]), default=1.0)
            confidence = min(confidence, caps[root])
            # One pin known by its number, whatever unnumbered ones share its net, is as
            # doubtful as a pin alone: what it joins has no pad to check it against.
            if sum(not n.startswith(UNNUMBERED) for _, n in pins) < 2:
                confidence = min(confidence, LONE_PIN_CONFIDENCE)
            seen = [name for name, _ in names[root].most_common()]
            net = Net(
                id="",
                name=seen[0] if seen else None,
                names_seen=seen,
                pins=sorted(pins),
                confidence=confidence,
                evidence=[Evidence(type=k, count=n) for k, n in sorted(kinds[root].items())],
                pages=sorted(pages[root]),
            )
            nets.append(net)
            roots[id(net)] = root
        nets.sort(key=lambda n: (n.name is None, n.name or "", n.pins))
        net_of_root = {}
        for i, net in enumerate(nets, 1):
            net.id = f"n{i}"
            root = roots[id(net)]
            net_of_root[root] = net.id
            if root in power_issues:
                power_issues[root].net = net.id

        wire_nets = {
            (node[1], node[2]): net_of_root[root]
            for root, group in self.uf.groups().items()
            if root in net_of_root
            for node in group
            if node[0] == "w"
        }
        return Result(sorted(components.values(), key=lambda c: c.ref), nets, issues, wire_nets)


def _crosses(p: Point, segments: list[Segment]) -> bool:
    """Four wire arms at a point, whether drawn whole or split into pieces."""
    arms = set()
    for seg in segments:
        if not geometry.is_axis_aligned(seg) or not _on(p, seg):
            continue
        axis = 0 if geometry.is_horizontal(seg) else 1
        for end in seg:
            offset = end[axis] - p[axis]
            if abs(offset) > TOL:
                arms.add((axis, 1 if offset > 0 else -1))
    return len(arms) == 4


def _slanted(seg: Segment) -> bool:
    """Neither level nor upright, as a bus entry is."""
    (ax, ay), (bx, by) = seg
    return min(abs(ax - bx), abs(ay - by)) > TOL


def _on(p: Point, seg: Segment) -> bool:
    return geometry.distance_to_segment(p, seg) <= TOL


def _label_tips(label: Label) -> list[Point]:
    """Outline corners on the text's centre line: the connecting tip and the far end.

    A plain rectangle has no such corners; it connects at the middle of either end.
    """
    cx, cy = geometry.center(label.bbox)
    vertical = round(label.angle) % 180 == 90
    tips = [v for v in label.outline if abs((v[0] - cx) if vertical else (v[1] - cy)) < 0.3]
    if tips:
        return tips
    box = geometry.bbox_of(label.outline)
    mx, my = geometry.center(box)
    return [(mx, box[1]), (mx, box[3])] if vertical else [(box[0], my), (box[2], my)]


def _under_label(
    label: Label,
    wires: list[Segment],
    wire_index: GridIndex,
    pin_lines: list[tuple[Segment, tuple]],
    pin_index: GridIndex | None,
    node_of: tuple,
) -> tuple | None:
    """The wire or pin a label without an outline sits on: parallel, just below its baseline."""
    x0, y0, x1, y1 = label.bbox
    vertical = round(label.angle) % 180 == 90
    along, across = geometry.reading_frame(label.angle)
    lo, hi = geometry.extent(label.bbox, along)
    base = geometry.extent(label.bbox, across)[1]  # its baseline, on the far side across
    region = (x0 - LABEL_GAP, y0 - LABEL_GAP, x1 + LABEL_GAP, y1 + LABEL_GAP)
    candidates = [(wires[j], (*node_of, j)) for j in wire_index.within(region)]
    near = sorted(pin_index.within(region)) if pin_index else []
    candidates += [
        pin_lines[k]
        for k in near
        if geometry.bbox_gap(region, geometry.bbox_of(pin_lines[k][0])) == 0
    ]

    best = None
    for seg, node in candidates:
        if geometry.is_horizontal(seg) == vertical or _slanted(seg):
            continue
        gap = geometry.dot(seg[0], across) - base
        a, b = geometry.dot(seg[0], along), geometry.dot(seg[1], along)
        overlaps = min(a, b) <= hi + 0.5 and max(a, b) >= lo - 0.5
        if -0.2 <= gap <= LABEL_GAP and overlaps and (best is None or gap < best[0]):
            best = (gap, node)
    return best[1] if best else None


def _apart(parts: list[tuple]) -> list[set[int]]:
    """Parts, each (node, page, pin, symbol), grouped into drawings: those on one page
    whose boxes touch are one."""
    groups = UnionFind()
    index: dict[int, GridIndex] = defaultdict(GridIndex)  # by page
    for i, (_, page, _, symbol) in enumerate(parts):
        groups.find(i)
        for j in index[page].within(geometry.grown(symbol.bbox, PIECE_GAP)):
            if geometry.bbox_gap(symbol.bbox, parts[j][3].bbox) <= PIECE_GAP:
                groups.union(i, j)
        index[page].add(i, symbol.bbox)
    found: dict = defaultdict(set)
    for i in range(len(parts)):
        found[groups.find(i)].add(i)
    return list(found.values())


def _doubtful(pin, symbol) -> bool:
    """A number guessed where libraries number alike-looking parts either way: a diode's
    end where the generator has no rule for which is 1, a three-pin part's ends, or the
    ends of a two-pin part other than a resistor, capacitor, inductor, fuse or ferrite,
    such as a connector, whose order matters."""
    if pin.number is None:
        return False
    if pin.how == "polarity":
        return True
    if pin.how != "position":
        return False
    if len(symbol.pins) > 2:
        return True
    match = REFDES.match(symbol.ref or "")
    return not match or match.group(1).rstrip("$") not in TWO_TERMINAL_PREFIXES
