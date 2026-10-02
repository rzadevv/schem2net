"""Stages 5-8 on small hand-built scenes that follow KiCad's drawing conventions."""

import math

from schem2net import buses, fields, geometry, profile, symbols
from schem2net.nets import Netlister
from schem2net.primitives import Page, Path, Text
from schem2net.scene import Label, Scene, Shape, Sheet, SheetPin, _join_runs
from schem2net.scene import build as build_scene

KICAD = profile.load("kicad")
ALTIUM = profile.load("altium")


class SceneBuilder:
    """Adds primitives in drawing order, the way a KiCad PDF lists them."""

    def __init__(self):
        self.scene = Scene(page=1)
        self.seq = 0

    def shape(self, *points, width=0.152, color=None):
        self.seq += 1
        box = geometry.bbox_of(points)
        self.scene.shapes.append(
            Shape(len(self.scene.shapes), list(points), width, box, self.seq, color)
        )

    def field(self, text, x, y):
        self.seq += 1
        box = (x, y, x + 0.8 * len(text), y + 1.27)
        self.scene.fields.append(Text(self.seq, text, box, 1.27, 0.0, (0, 100, 100), self.seq))

    def resistor(self, x, y, ref, value):
        """Vertical resistor with its body at (x, y) and hidden pin numbers."""
        self.shape((x - 1, y), (x + 1, y), (x + 1, y + 5), (x - 1, y + 5), (x - 1, y))
        self.shape((x, y), (x, y - 2.54))
        self.shape((x, y + 5), (x, y + 7.54))
        self.field(ref, x + 2, y + 1)
        self.field(value, x + 2, y + 3)

    def ground(self, x, y):
        """Ground symbol connecting at (x, y)."""
        self.shape((x, y), (x, y + 1.27), (x + 1.27, y + 1.27), (x, y + 2.54), (x - 1.27, y + 1.27))
        self.field("GND", x - 1.5, y + 3)

    def capacitor(self, x, y, ref, value):
        """Vertical capacitor: two plates that do not touch, one pin on each."""
        self.shape((x - 2, y), (x + 2, y), width=0.508)
        self.shape((x - 2, y + 1.5), (x + 2, y + 1.5), width=0.508)
        self.shape((x, y - 0.25), (x, y - 2.8))
        self.shape((x, y + 1.75), (x, y + 4.3))
        self.field(ref, x + 3, y - 1)
        self.field(value, x + 3, y + 1)


def netlist(*scenes: Scene, rules=KICAD):
    netlister = Netlister(labels_span_pages=rules.labels_span_pages)
    for scene in scenes:
        netlister.add_page(scene, symbols.find(scene, rules))
    components, nets, *_ = netlister.result()
    return {c.ref: c for c in components}, {n.name: n for n in nets}


def test_two_resistors_on_a_labelled_wire_and_ground():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "10k")
    b.ground(10, 17.54)  # directly on R1 pin 2, no wire
    b.resistor(20, 10, "R2", "1k")
    b.scene.wires.append(((10, 7.46), (20, 7.46)))
    b.scene.labels.append(Label("SDA", "local", (13, 6.0, 16, 7.2), 0.0))

    components, nets = netlist(b.scene)

    assert {ref: c.value for ref, c in components.items()} == {"R1": "10k", "R2": "1k"}
    assert nets["SDA"].pins == [("R1", "1"), ("R2", "1")]
    assert nets["GND"].pins == [("R1", "2")]
    assert ("R2", "2") not in {p for n in nets.values() for p in n.pins}


def test_capacitor_plates_form_one_part():
    b = SceneBuilder()
    b.capacitor(10, 10, "C1", "100n")
    b.ground(10, 14.3)
    b.scene.wires.append(((10, 7.2), (20, 7.2)))
    b.scene.labels.append(Label("VIN", "local", (13, 5.7, 16, 6.9), 0.0))

    components, nets = netlist(b.scene)

    assert [p.num for p in components["C1"].pins] == ["1", "2"]
    assert nets["VIN"].pins == [("C1", "1")]
    assert nets["GND"].pins == [("C1", "2")]


def test_wires_join_at_junctions_but_not_plain_crossings():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    b.resistor(30, 10, "R2", "1k")
    b.resistor(50, 10, "R3", "1k")
    b.resistor(20, -10, "R4", "1k")  # pin 2 ends at (20, -2.46)
    b.scene.wires += [
        ((10, 7.46), (30, 7.46)),  # R1 to R2
        ((20, -2.46), (20, 7.46)),  # T from R4 into the first wire, with a dot
        ((40, 3), (40, 12)),  # crosses the R2-R3 wire without a dot
        ((30, 7.46), (50, 7.46)),
    ]
    b.scene.junctions.append((20, 7.46))

    _, nets = netlist(b.scene)
    (net,) = [n for n in nets.values() if ("R1", "1") in n.pins]
    assert net.pins == [("R1", "1"), ("R2", "1"), ("R3", "1"), ("R4", "2")]
    assert net.confidence == 1.0


def test_dangling_wire_lowers_confidence():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    b.resistor(20, 10, "R2", "1k")
    b.scene.wires += [
        ((10, 7.46), (20, 7.46)),
        ((20, 7.46), (30, 7.46)),
    ]  # second one leads nowhere

    _, nets = netlist(b.scene)
    (net,) = nets.values()
    assert net.pins == [("R1", "1"), ("R2", "1")]
    assert net.confidence < 0.8


def test_split_label_text_is_rejoined():
    pieces = [
        Text(1, "PCIe", (0, 0, 4.4, 1.4), 1.27, 0.0, (15, 15, 15), 1),
        Text(2, "C5x4", (4.3, 0.6, 6.8, 1.6), 0.76, 0.0, (15, 15, 15), 2),
        Text(3, ".RST", (6.7, 0, 10.3, 1.4), 1.27, 0.0, (15, 15, 15), 3),
        Text(4, "NEXT", (0, 5, 4, 6.4), 1.27, 0.0, (15, 15, 15), 4),
    ]
    assert [t.text for t in _join_runs(pieces)] == ["PCIeC5x4.RST", "NEXT"]


def test_designator_is_not_joined_to_a_value_drawn_against_it():
    teal = (0, 100, 100)
    touching = [
        Text(1, "J802", (0, 0, 4.7, 1.4), 1.27, 0.0, teal, 1),
        Text(2, "Conn_01x22_Female", (4.4, 0, 23.9, 1.5), 1.27, 0.0, teal, 2),
    ]
    assert [t.text for t in _join_runs(touching)] == ["J802", "Conn_01x22_Female"]
    spaced = [
        Text(1, "R10", (0, 0, 3.1, 1.2), 1.27, 0.0, teal, 1),
        Text(2, "470", (4.0, 0, 7.1, 1.2), 1.27, 0.0, teal, 2),
    ]
    assert [t.text for t in _join_runs(spaced)] == ["R10", "470"]
    # Text written a character at a time still joins up.
    one_by_one = [
        Text(1, "C1", (0, 0, 1.8, 1.2), 1.78, 0.0, teal, 1),
        Text(2, "0", (2.0, 0, 2.8, 1.2), 1.78, 0.0, teal, 2),
    ]
    assert [t.text for t in _join_runs(one_by_one)] == ["C10"]


def test_bus_names():
    vector = buses.parse("D[0..3]")
    assert vector.vector and vector.members == ("0", "1", "2", "3")
    assert buses.member_nets(vector, set()) == {"0": "D0", "1": "D1", "2": "D2", "3": "D3"}

    group = buses.parse("I2C{SCL SDA}")
    assert buses.member_nets(group, set()) == {"SCL": "I2C.SCL", "SDA": "I2C.SDA"}

    alias = buses.parse("I2C_SYS{I2C}")
    assert alias.members is None
    names = {"I2C_SYS.SCL", "I2C_SYS.SDA", "OTHER"}
    assert buses.member_nets(alias, names) == {"SCL": "I2C_SYS.SCL", "SDA": "I2C_SYS.SDA"}

    bare = buses.parse("{VME}")
    assert buses.member_nets(bare, {"VME.IRQ", "VME.ACK"}) == {"IRQ": "VME.IRQ", "ACK": "VME.ACK"}

    assert buses.parse("SCL") is None


def test_sheet_pin_joins_child_label():
    parent = SceneBuilder()
    parent.scene.path = "/"
    parent.resistor(10, 10, "R1", "1k")
    parent.scene.wires.append(((10, 7.46), (30, 7.46)))
    parent.scene.sheets.append(Sheet("Sub", (30, 0, 50, 20), [SheetPin("SIG", (30, 7.46))]))

    child = SceneBuilder()
    child.scene.page, child.scene.path = 2, "/Sub/"
    child.resistor(10, 10, "R2", "1k")
    child.scene.wires.append(((10, 7.46), (20, 7.46)))
    child.scene.labels.append(Label("SIG", "hier", (21, 6.8, 24, 8.1), 0.0, [(20, 7.46)]))

    _, nets = netlist(parent.scene, child.scene)
    assert nets["SIG"].pins == [("R1", "1"), ("R2", "1")]


def test_vector_bus_members_match_by_position():
    parent = SceneBuilder()
    parent.scene.path = "/"
    parent.resistor(10, 10, "R1", "1k")
    parent.resistor(20, 10, "R2", "1k")
    parent.scene.wires += [((10, 7.46), (10, 3)), ((20, 7.46), (20, 3))]
    parent.scene.labels += [
        Label("D4", "local", (10.5, 1.7, 12.5, 2.9), 0.0),
        Label("D5", "local", (20.5, 1.7, 22.5, 2.9), 0.0),
        Label("D[4..5]", "bus", (32, 8.5, 38, 9.8), 0.0),
    ]
    parent.scene.wires += [((10, 3), (15, 3)), ((20, 3), (25, 3))]
    parent.scene.buses.append(((30, 10), (40, 10)))
    parent.scene.sheets.append(Sheet("Sub", (40, 0, 60, 20), [SheetPin("D[0..1]", (40, 10))]))

    child = SceneBuilder()
    child.scene.page, child.scene.path = 2, "/Sub/"
    child.resistor(10, 10, "R3", "1k")
    child.resistor(20, 10, "R4", "1k")
    child.scene.wires += [((10, 7.46), (10, 3)), ((20, 7.46), (20, 3))]
    child.scene.labels += [
        Label("X0", "local", (10.5, 1.7, 12.5, 2.9), 0.0),
        Label("X1", "local", (20.5, 1.7, 22.5, 2.9), 0.0),
        Label("D[0..1]", "hier", (31, 9.3, 37, 10.6), 0.0, [(30, 10)]),
        Label("X[0..1]", "bus", (32, 12.5, 38, 13.8), 0.0),
    ]
    child.scene.wires += [((10, 3), (15, 3)), ((20, 3), (25, 3))]
    child.scene.buses += [((30, 10), (30, 14)), ((30, 14), (40, 14))]

    _, nets = netlist(parent.scene, child.scene)
    assert nets["D4"].pins == [("R1", "1"), ("R3", "1")]
    assert nets["D5"].pins == [("R2", "1"), ("R4", "1")]


def test_altium_conventions():
    """Black pins, a blue body touching them tip to tip, an unnamed ground, a net label."""
    black, blue, dark_red = (0, 0, 0), (0, 0, 255), (128, 0, 0)
    b = SceneBuilder()
    # R1: black pins at both ends of a blue zigzag.
    b.shape((10, 5), (10, 8), color=black)
    b.shape((10, 8), (11, 9), (9, 10), (11, 11), (10, 12), color=blue)
    b.shape((10, 12), (10, 15), color=black)
    b.field("R1", 12, 9)
    # Ground port: a stem and three shrinking bars, no name.
    b.shape((10, 17), (10, 18), color=dark_red)
    for i, half in enumerate((1.5, 1.0, 0.5)):
        b.shape((10 - half, 18 + 0.5 * i), (10 + half, 18 + 0.5 * i), color=dark_red)
    b.scene.wires += [((10, 15), (10, 17)), ((10, 5), (20, 5))]
    b.scene.labels.append(Label("SENSE", "local", (13, 3.6, 17, 4.8), 0.0))

    _, nets = netlist(b.scene, rules=ALTIUM)
    # Pin numbers are hidden: Altium parts turned upright have pin 1 at the bottom.
    assert nets["GND"].pins == [("R1", "1")]
    assert nets["SENSE"].pins == [("R1", "2")]


def test_altium_ground_overlapping_a_pin_is_a_separate_part():
    """Values come before the graphics and the designator after, as Altium draws them."""
    black, blue, dark_red = (0, 0, 0), (0, 0, 255), (128, 0, 0)
    b = SceneBuilder()
    b.field("1μF", 12, 9)
    b.shape((10, 5), (10, 8), color=black)
    b.shape((9, 8), (11, 8), color=blue)
    b.shape((9, 8.5), (11, 8.5), color=blue)
    b.shape((10, 8.5), (10, 11.5), color=black)
    b.field("C1", 12, 7)
    # The ground stem runs back over the end of the pin.
    b.shape((10, 11), (10, 12), color=dark_red)
    for i, half in enumerate((1.5, 1.0, 0.5)):
        b.shape((10 - half, 12 + 0.5 * i), (10 + half, 12 + 0.5 * i), color=dark_red)
    b.scene.wires.append(((10, 5), (20, 5)))
    b.scene.labels.append(Label("VIN", "local", (13, 3.6, 17, 4.8), 0.0))

    components, nets = netlist(b.scene, rules=ALTIUM)
    assert "C1" in components
    assert nets["GND"].pins == [("C1", "1")]
    assert nets["VIN"].pins == [("C1", "2")]


def test_wire_hop_does_not_join_the_crossed_wire():
    navy = (0, 0, 128)
    arc = [(10 + 0.5 * math.sin(math.pi * i / 8), 9.5 + i / 8) for i in range(9)]
    page = Page(1, 100, 100)
    page.paths = [
        Path(0, [[(0, 10), (20, 10)]], 0.2, navy, None),
        Path(1, [[(10, 0), (10, 9.5)]], 0.2, navy, None),
        Path(2, [arc], 0.2, navy, None, curved=True),
        Path(3, [[(10, 10.5), (10, 20)]], 0.2, navy, None),
    ]
    for i, path in enumerate(page.paths):
        path.seq = i
    built = build_scene(page, ALTIUM)
    netlister = Netlister()
    netlister.add_page(built, [])
    net = [netlister.uf.find(("w", 1, i)) for i in range(len(built.wires))]
    assert len(built.wires) == 4
    assert net[0] != net[1]
    assert net[1] == net[2] == net[3]


def test_altium_triangle_ground():
    black, blue, dark_red = (0, 0, 0), (0, 0, 255), (128, 0, 0)
    b = SceneBuilder()
    b.shape((10, 5), (10, 8), color=black)
    b.shape((10, 8), (11, 9), (9, 10), (11, 11), (10, 12), color=blue)
    b.shape((10, 12), (10, 15), color=black)
    b.field("R1", 12, 9)
    b.shape((10, 15), (10, 17), color=dark_red)
    b.shape((8.5, 17), (11.5, 17), color=dark_red)
    b.shape((8.5, 17), (10, 18.5), color=dark_red)
    b.shape((11.5, 17), (10, 18.5), color=dark_red)

    _, nets = netlist(b.scene, rules=ALTIUM)
    assert nets["GND"].pins == [("R1", "1")]


def test_altium_pins_in_body_colour_where_wires_meet_them():
    blue = (0, 0, 255)
    b = SceneBuilder()
    b.shape((10, 5), (10, 8), color=blue)
    b.shape((9, 8), (11, 8), color=blue)
    b.shape((9, 8.5), (11, 8.5), color=blue)
    b.shape((10, 8.5), (10, 11.5), color=blue)
    b.field("C1", 12, 7)
    b.scene.wires += [((10, 5), (20, 5)), ((10, 11.5), (20, 11.5))]
    b.scene.labels.append(Label("VIN", "local", (13, 3.6, 17, 4.8), 0.0))
    b.scene.labels.append(Label("OUT", "local", (13, 10.1, 17, 11.3), 0.0))

    _, nets = netlist(b.scene, rules=ALTIUM)
    assert nets["VIN"].pins == [("C1", "2")]
    assert nets["OUT"].pins == [("C1", "1")]


def test_altium_net_labels_join_across_pages_but_kicad_ones_do_not():
    pages = []
    for page, ref in ((1, "R1"), (2, "R2")):
        b = SceneBuilder()
        b.scene.page = page
        b.resistor(10, 10, ref, "1k")
        b.scene.wires.append(((10, 7.46), (20, 7.46)))
        b.scene.labels.append(Label("SDA", "local", (13, 6.0, 16, 7.2), 0.0))
        pages.append(b.scene)

    _, nets = netlist(*pages, rules=ALTIUM)
    assert nets["SDA"].pins == [("R1", "1"), ("R2", "1")]
    _, nets = netlist(*pages, rules=KICAD)
    assert nets["SDA"].pins in ([("R1", "1")], [("R2", "1")])


def test_kicad_ground_with_hidden_name():
    """KiCad's ground: stem and triangle in one polyline, base drawn in two halves."""
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    b.shape((10, 17.54), (10, 18.81), (11.27, 18.81), (10, 20.08), (8.73, 18.81), (10, 18.81))

    _, nets = netlist(b.scene)
    assert nets["GND"].pins == [("R1", "2")]


def test_lone_triangle_ground_on_a_wire():
    """Older KiCad grounds are a bare triangle; the wire meets the middle of its base."""
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    b.scene.wires.append(((10, 17.54), (10, 20)))
    b.shape((8.73, 20), (10, 21.27), (11.27, 20), (8.73, 20))

    _, nets = netlist(b.scene)
    assert nets["GND"].pins == [("R1", "2")]


def test_recoloured_label_text_is_read_where_its_outline_meets_a_wire():
    dark_red, green, purple = (132, 0, 0), (0, 160, 0), (132, 0, 132)
    page = Page(1, 100, 100)
    flag = [(20, 10), (21, 9), (30, 9), (30, 11), (21, 11), (20, 10)]
    box = [(50, 9), (55, 9), (55, 11), (50, 11), (50, 9)]
    page.paths = [
        Path(0, [[(10, 10), (20, 10)]], 0.15, (0, 150, 0), None),
        Path(1, [flag], 0.15, dark_red, None),
        Path(2, [box], 0.15, dark_red, None),
    ]
    page.texts = [
        Text(0, "in2", (22, 9.4, 26, 10.6), 1.27, 0.0, green),
        Text(1, "RA", (51, 9.4, 53, 10.6), 1.27, 0.0, purple),
    ]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, KICAD)
    assert [(lb.text, lb.kind) for lb in built.labels] == [("in2", "global")]


def test_no_connect_cross_is_not_a_bus():
    navy = (0, 0, 132)
    page = Page(1, 100, 100)
    page.paths = [
        Path(0, [[(9.39, 9.39), (10.61, 10.61)]], 0.15, navy, None),
        Path(1, [[(10.61, 9.39), (9.39, 10.61)]], 0.15, navy, None),
    ]
    for seq, path in enumerate(page.paths):
        path.seq = seq
    built = build_scene(page, KICAD)
    assert built.no_connects == [(10.0, 10.0)]
    assert built.buses == []


def test_checks_report_merged_power_and_unconnected_pins():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    b.ground(10, 17.54)
    b.shape((10, 7.46), (10, 6.19), (11.27, 6.19), (10, 4.92), (8.73, 6.19), (10, 6.19))
    b.field("+3V3", 8.5, 3)
    b.resistor(30, 10, "R2", "1k")
    b.scene.no_connects.append((30, 7.46))

    netlister = Netlister()
    netlister.add_page(b.scene, symbols.find(b.scene, KICAD))
    found = netlister.result()
    kinds = [issue.kind for issue in found.issues]
    assert "power_nets_merged" not in kinds
    assert kinds.count("unconnected_pin") == 1  # R2 pin 2; pin 1 is flagged

    b.scene.wires.append(((10, 7.46), (10, 17.54)))
    netlister = Netlister()
    netlister.add_page(b.scene, symbols.find(b.scene, KICAD))
    found = netlister.result()
    assert "power_nets_merged" in [issue.kind for issue in found.issues]
    assert found.nets[0].confidence < 0.8


def test_pin_shared_by_two_units_is_one_net():
    """A dual part's supply pin, drawn in both units, is one pad."""
    scene = Scene(page=1)
    scene.wires += [((0, 0), (5, 0)), ((20, 0), (25, 0))]
    scene.labels += [
        Label("A", "local", (0, -1.5, 2, -0.3), 0.0),
        Label("B", "local", (20, -1.5, 22, -0.3), 0.0),
    ]
    units = [
        symbols.Symbol(
            [0], (5, -1, 10, 1), [symbols.Pin(0, ((7, 0), (5, 0)), "8")], ref="U1", unit=u
        )
        for u in "AB"
    ]
    units[1].pins = [symbols.Pin(1, ((27, 0), (25, 0)), "8")]
    netlister = Netlister()
    netlister.add_page(scene, units)
    nets = netlister.result().nets
    assert len(nets) == 1
    assert nets[0].pins == [("U1", "8")]
    assert sorted(nets[0].names_seen) == ["A", "B"]


def test_eagle_connector_box_joins_the_pins_that_cross_into_it():
    """A connector's box drawn well before its pins: each pin runs in across its edge."""
    red = (128, 0, 0)
    b = SceneBuilder()
    b.shape((20, 10), (26, 10), (26, 20), (20, 20), (20, 10), width=0.4, color=red)
    b.seq += 20  # other drawing in between
    for k, y in enumerate((12.54, 15.08, 17.62)):
        b.shape((16, y), (21.27, y), width=0.15, color=red)
        number = Text(b.seq, str(k + 1), (17, y - 1.6, 17.8, y - 0.3), 1.27, 0.0, red, b.seq)
        b.scene.fields.append(number)
        b.scene.pin_numbers.append(number)
        b.scene.wires.append(((8, y), (16, y)))
        b.scene.labels.append(Label(f"N{k}", "global", (8, y - 1.5, 11, y - 0.2), 0.0))
    b.field("J1", 20, 21)

    parts, nets = netlist(b.scene, rules=profile.load("eagle"))
    assert sorted(p.num for p in parts["J1"].pins) == ["1", "2", "3"]
    assert nets["N1"].pins == [("J1", "2")]


def test_part_values_are_never_pad_numbers():
    assert fields._is_value("10k") and fields._is_value("0.1uF") and fields._is_value("4.7")
    assert not fields._is_value("12") and not fields._is_value("A6")
