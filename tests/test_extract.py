"""Stages 5-8 on small hand-built scenes that follow KiCad's drawing conventions."""

import math

from schem2net import buses, fields, geometry, profile, symbols
from schem2net.nets import Netlister
from schem2net.primitives import Page, Path, Text
from schem2net.refdes import REFDES, is_common_ref
from schem2net.scene import Label, Scene, Shape, Sheet, SheetPin, _join_runs, drop_sheet_references
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


def test_sheet_references_leave_label_names():
    page = Scene(page=1)
    for text in ("MCLK/2", "LRCK /3.4B", "TX/1", "D/9"):
        page.labels.append(Label(text, "global", (0, 0, 5, 1), 0.0))
    drop_sheet_references(page, sheets=3)
    # Sheet 1 is this one and there is no sheet 9: those are parts of names.
    assert [label.text for label in page.labels] == ["MCLK", "LRCK", "TX/1", "D/9"]


def test_supply_name_anchored_at_one_end_overhangs_its_arrow():
    """Eagle anchors a supply's name at its left end, so a long name overhangs the arrow."""
    red, grey = (128, 0, 0), (80, 80, 80)
    b = SceneBuilder()
    b.shape((10, 15), (10, 12.5), width=0.15, color=red)  # stem, met by the wire below
    b.shape((9.2, 13.5), (10, 12.5), (10.8, 13.5), width=0.3, color=red)  # arrow head
    b.seq += 1
    name = Text(b.seq, "3.3V", (9.6, 10.4, 14.4, 12.0), 1.6, 0.0, grey, b.seq)
    b.scene.fields.append(name)
    b.scene.wires.append(((10, 15), (10, 25)))

    found = symbols.find(b.scene, profile.load("eagle"))
    assert [s.power for s in found] == ["3.3V"]


def test_eagle_label_laid_on_a_wire():
    """Classic Eagle labels: a name just above its wire, in the colour of names and values."""
    green, grey = (0, 128, 0), (128, 128, 128)
    page = Page(1, 100, 100)
    page.paths = [
        Path(0, [[(10, 20), (40, 20)]], 0.15, green, None),
        Path(1, [[(10, 30), (40, 30)]], 0.15, green, None),
    ]
    page.texts = [
        Text(0, "ETXD0", (14, 18, 22, 19.5), 1.5, 0.0, grey),  # on the first wire
        Text(1, "220nF", (14, 28, 20, 29.5), 1.5, 0.0, grey),  # a value over a wire
        Text(2, "SDA", (60, 18, 64, 19.5), 1.5, 0.0, grey),  # near no wire
    ]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, profile.load("eagle"))
    assert [(lb.text, lb.kind) for lb in built.labels] == [("ETXD0", "local")]


def test_eagle_designator_outside_the_box_beats_a_pin_name_inside():
    """A chip whose pins are named like designators (A0, A1), a little in from the pins,
    beyond where pin names are looked for: its name sits above the box."""
    red, grey = (128, 0, 0), (128, 128, 128)
    b = SceneBuilder()
    b.shape((20, 10), (40, 10), (40, 30), (20, 30), (20, 10), width=0.4, color=red)
    for k, y in enumerate((12.54, 15.08, 17.62)):
        b.shape((15, y), (20, y), width=0.15, color=red)
        b.scene.fields.append(
            Text(b.seq, f"A{k}", (24.1, y - 0.7, 25.9, y + 0.7), 1.3, 0.0, grey, b.seq)
        )
        b.scene.wires.append(((5, y), (15, y)))
    b.scene.fields.append(Text(b.seq + 1, "U3", (20, 6.2, 22, 7.6), 1.3, 0.0, grey, b.seq + 1))

    found = symbols.find(b.scene, profile.load("eagle"))
    assert [s.ref for s in found if s.pins] == ["U3"]


def test_pins_leave_the_slanted_sides_of_a_triangle_past_a_polarity_mark():
    """An amplifier's supply pin starts on a slanted side and ends within the triangle's
    box; a "+" drawn against an input is a mark, not a pin."""
    red, blue = (135, 0, 0), (0, 0, 255)
    b = SceneBuilder()
    b.shape((0, 0), (0, 20), (20, 10), (0, 0), width=0.25, color=red)
    b.shape((-5, 5), (0, 5), width=0.25, color=red)
    b.shape((12, 6), (12, 1), width=0.25, color=red)  # the side is at y = 6 here
    b.shape((-2.5, 4.9), (-2.5, 3.9), width=0.25, color=red)  # the "+"
    b.shape((-3, 4.4), (-2, 4.4), width=0.25, color=red)
    for text, box, angle in (("2", (-4.8, 3.4, -4.0, 4.7), 0.0), ("1", (10, 2, 11.3, 2.8), 90.0)):
        b.seq += 1
        number = Text(b.seq, text, box, 1.27, angle, blue, b.seq)
        b.scene.fields.append(number)
        b.scene.pin_numbers.append(number)
    b.scene.wires += [((-10, 5), (-5, 5)), ((12, 1), (12, -4))]
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "U1", (22, 2, 24, 3.3), 1.27, 0.0, (0, 0, 128), b.seq))

    (u1,) = symbols.find(b.scene, profile.load("easyeda"))
    assert sorted((p.number, p.at) for p in u1.pins) == [("1", (12, 1)), ("2", (-5, 5))]


def test_easyeda_ground_with_hidden_name_does_not_take_a_designator():
    """EasyEDA's ground is a stem and three bars drawn apart, its name hidden. The
    stem reads as a pin, since pins and bodies share a colour."""
    red, navy = (135, 0, 0), (0, 0, 128)
    b = SceneBuilder()
    b.shape((9, 10), (11, 10), (11, 15), (9, 15), (9, 10), width=0.25, color=red)
    b.shape((10, 10), (10, 7.46), width=0.25, color=red)
    b.shape((10, 15), (10, 17.54), width=0.25, color=red)
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "R1", (12, 11, 14, 12.3), 1.27, 0.0, navy, b.seq))
    b.shape((10, 20.08), (10, 22), width=0.25, color=red)  # the ground, on a wire
    for half, y in ((2, 22), (1.3, 22.8), (0.6, 23.6)):
        b.shape((10 - half, y), (10 + half, y), width=0.25, color=red)
    b.scene.wires += [((10, 17.54), (10, 20.08)), ((10, 7.46), (20, 7.46))]
    b.scene.labels.append(Label("VIN", "local", (13, 5.7, 16, 6.9), 0.0))

    parts, nets = netlist(b.scene, rules=profile.load("easyeda"))
    assert list(parts) == ["R1"]
    assert nets["GND"].pins == [("R1", "2")]
    assert nets["VIN"].pins == [("R1", "1")]


def test_value_shaped_like_an_inductor_does_not_name_a_part_of_many_pins():
    """A value such as L298 under a driver's box: an inductor has two pins, not six."""
    b = SceneBuilder()
    b.shape((10, 10), (20, 10), (20, 20), (10, 20), (10, 10))
    for y in (12.54, 15.08, 17.62):
        b.shape((10, y), (7.46, y))
        b.shape((20, y), (22.54, y))
    b.field("U2", 11, 8.2)
    b.field("L298", 11, 20.5)

    parts, _ = netlist(b.scene)
    assert list(parts) == ["U2"] and parts["U2"].value == "L298"


def test_easyeda_value_is_drawn_right_before_the_designator():
    """EasyEDA writes a part's value, then its designator, then its drawing. A value
    such as Z80 looks like a designator and may sit nearer the box."""
    red, navy = (135, 0, 0), (0, 0, 128)
    b = SceneBuilder()
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "Z80", (11, 8.6, 14, 9.6), 1.27, 0.0, navy, b.seq))
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "U1", (11, 6.0, 13, 7.0), 1.27, 0.0, navy, b.seq))
    b.shape((10, 10), (20, 10), (20, 20), (10, 20), (10, 10), width=0.25, color=red)
    for y in (12.54, 15.08, 17.62):
        b.shape((10, y), (7.46, y), width=0.25, color=red)
        b.shape((20, y), (22.54, y), width=0.25, color=red)

    parts, _ = netlist(b.scene, rules=profile.load("easyeda"))
    assert list(parts) == ["U1"]


def test_section_frame_drawn_after_a_part_does_not_take_its_pins():
    """A box drawn round a section of the sheet, right after the last part in it."""
    red = (128, 0, 0)
    b = SceneBuilder()
    b.shape((50, 50), (55, 50), (55, 53), (50, 53), (50, 50), width=0.25, color=red)
    b.shape((50, 51.5), (47.46, 51.5), width=0.25, color=red)
    b.shape((55, 51.5), (57.54, 51.5), width=0.25, color=red)
    b.shape((10, 10), (110, 10), (110, 110), (10, 110), (10, 10), width=0.25, color=red)
    b.field("R1", 51, 47)

    (part,) = symbols.find(b.scene, profile.load("eagle"))
    assert part.ref == "R1" and part.bbox == (47.46, 50, 57.54, 53)


def test_pin_number_written_over_its_pin():
    """Some libraries centre the number on the pin line rather than above it."""
    number = (18.6, 112.5, 19.2, 114.5)
    over = fields._number_gap(number, ((17.8, 113.5), (20.3, 113.5)), True)
    below = fields._number_gap(number, ((17.8, 116.1), (20.3, 116.1)), True)
    assert over is not None and over < below


def test_pin_name_and_number_drawn_in_turn_are_not_joined():
    """A pin's name, centred on the pin, and its number above it, on other baselines."""
    blue = (0, 0, 255)
    pieces = [
        Text(1, "SDA", (84.4, 182.6, 89.0, 184.3), 2.3, 0.0, blue, 1),
        Text(2, "5", (90.4, 181.5, 91.6, 183.1), 2.3, 0.0, blue, 2),
    ]
    assert [t.text for t in _join_runs(pieces)] == ["SDA", "5"]
    # A dash alone shares neither the tops nor the baseline of the words beside it.
    note = [
        Text(1, "a 1.65", (0, 0, 9, 2.2), 2.3, 0.0, blue, 1),
        Text(2, "-", (9.1, 0.9, 9.8, 1.2), 2.3, 0.0, blue, 2),
        Text(3, "3.3V", (9.9, 0, 15, 1.7), 2.3, 0.0, blue, 3),
    ]
    assert [t.text for t in _join_runs(note)] == ["a 1.65-3.3V"]


def test_switch_lever_ending_on_a_contact_ring_is_not_a_pin():
    """A line from a bar to a small ring has no closed outline at its other end to
    compare the ring with, so it is drawing, not a pin with a flag on its tip."""
    b = SceneBuilder()
    b.shape((0, 0), (4, 0))
    b.shape((2, 0), (2, 1.3))
    ring = [
        (2 + 0.2 * math.sin(k * math.pi / 6), 1.5 - 0.2 * math.cos(k * math.pi / 6))
        for k in range(13)
    ]
    b.shape(*ring)
    index = geometry.GridIndex()
    for shape in b.scene.shapes:
        index.add(shape.id, shape.bbox)
    lever = b.scene.shapes[1]
    assert symbols._flag_on_tip([lever], *lever.points, b.scene, index) is None


def test_easyeda_parts_whose_pins_meet_tip_to_tip_stay_apart():
    """Two capacitors stacked pin on pin. Neither pin's end lands on a body, so drawing
    order tells which end is whose: EasyEDA draws each part whole."""
    red, navy = (161, 0, 0), (0, 0, 128)
    b = SceneBuilder()

    def capacitor(ref, y):  # plates at y, pins out to y - 3.2 and y + 4.5
        b.seq += 1
        b.scene.fields.append(Text(b.seq, ref, (12, y, 14, y + 1.2), 1.27, 0.0, navy, b.seq))
        b.shape((10, y - 1.3), (10, y - 3.2), width=0.18, color=red)
        b.shape((10, y - 1.3), (10, y - 0.03), width=0.18, color=red)
        b.shape(
            (8.6, y), (11.4, y), (11.4, y + 0.3), (8.6, y + 0.3), (8.6, y), width=0.18, color=red
        )
        b.shape(
            (8.6, y + 0.9),
            (11.4, y + 0.9),
            (11.4, y + 1.2),
            (8.6, y + 1.2),
            (8.6, y + 0.9),
            width=0.18,
            color=red,
        )
        b.shape((10, y + 1.2), (10, y + 2.6), width=0.18, color=red)
        b.shape((10, y + 2.6), (10, y + 4.5), width=0.18, color=red)

    capacitor("C2", 10)
    capacitor("C1", 17.7)
    b.scene.wires += [((10, 6.8), (20, 6.8)), ((10, 22.2), (20, 22.2))]
    b.scene.labels += [Label("TOP", "local", (15, 5.5, 18, 6.6), 0.0)]
    b.scene.labels += [Label("BOTTOM", "local", (15, 20.9, 18, 22), 0.0)]

    parts, nets = netlist(b.scene, rules=profile.load("easyeda"))
    assert sorted(parts) == ["C1", "C2"]
    assert all(len(p.pins) == 2 for p in parts.values())


def test_rows_numbered_from_marks_at_their_ends():
    """A card socket marks only the first pin of each row, or the first and last."""
    b = SceneBuilder()
    b.shape((10, 10), (16, 10), (16, 22), (10, 22), (10, 10))
    for k in range(4):
        y = 12.54 + 2.54 * k
        b.shape((16, y), (18.54, y))
        b.shape((10, y), (7.46, y))
    # "1" beside its pin, "5" and "8" past the ends of their row.
    for text, x, y in (("1", 17, 10.8), ("5", 8, 8.7), ("8", 8, 22.8)):
        number = Text(b.seq + 1, text, (x, y, x + 0.8, y + 1.2), 1.27, 0.0, (0, 0, 0), b.seq + 1)
        b.seq += 1
        b.scene.pin_numbers.append(number)
    b.scene.fields.append(Text(99, "J1", (10, 7, 12, 8.2), 1.27, 0.0, (0, 0, 128), 99))

    (part,) = symbols.find(b.scene, profile.load("easyeda"))
    numbers = {p.number: (p.at[0], round(p.at[1], 2)) for p in part.pins}
    assert numbers["1"] == (18.54, 12.54) and numbers["4"] == (18.54, 20.16)
    assert numbers["5"] == (7.46, 12.54) and numbers["8"] == (7.46, 20.16)


def test_net_name_shaped_like_a_designator_in_another_colour():
    """EasyEDA designators are navy, so a blue A15 beside a port flag is a net name."""
    easyeda = profile.load("easyeda")
    blue, navy = (0, 0, 255), (0, 0, 128)
    assert fields._is_power_name(Text(1, "A15", (0, 0, 2, 1), 1.0, 0.0, blue, 1), easyeda)
    assert not fields._is_power_name(Text(1, "A15", (0, 0, 2, 1), 1.0, 0.0, navy, 1), easyeda)
    assert not fields._is_power_name(Text(1, "A15", (0, 0, 2, 1), 1.0, 0.0, blue, 1), KICAD)


def test_power_name_sits_away_from_the_wire():
    """A ground set on a pin, its stem pointing left: the pin number beside the stem
    is not its name; the name is past the bars."""
    ground = symbols.Symbol([], (10, 9, 13, 11), [symbols.Pin(0, ((12, 10), (10, 10)))])
    left = Text(1, "A1", (8, 9.4, 9.6, 10.6), 1.0, 0.0, (0, 0, 0), 1)
    right = Text(2, "GND", (13.5, 9.4, 16.5, 10.6), 1.0, 0.0, (0, 0, 255), 2)
    assert not fields._in_line(ground, left) and fields._in_line(ground, right)


def test_easyeda_numbered_units():
    match = REFDES.match("U3.1")
    assert match and match.groups() == ("U", "3", ".1") and is_common_ref("U10.2")
    assert not REFDES.match("OLED0.66")  # a value


def _mosfet(b, x, y):
    """EasyEDA's N-channel MOSFET with a body diode, gate on the left, drawn in its
    order: the gate stands apart from the channel, and the two are drawn interleaved."""
    red, navy = (135, 0, 0), (0, 0, 128)
    b.seq += 1
    b.scene.fields.append(
        Text(b.seq, "Q3", (x + 26, y + 13, x + 30, y + 15), 1.27, 0.0, navy, b.seq)
    )
    lines = [
        [(7.8, 15.15), (12.87, 15.15)],  # gate pin
        [(10.33, 15.15), (14.4, 15.15)],  # its lead, to the gate bar
        [(15.41, 19.72), (15.41, 17.69)],
        [(15.41, 16.16), (15.41, 14.13)],
        [(15.41, 10.58), (15.41, 12.61)],
        [(14.4, 10.58), (14.4, 19.72)],  # gate bar
        [(20.49, 18.7), (15.41, 18.7)],
        [(15.41, 15.15), (20.49, 15.15), (20.49, 20.23), (25.57, 20.23), (25.57, 16.67)],
        [(15.41, 11.59), (20.49, 11.59), (20.49, 10.07), (25.57, 10.07), (25.57, 14.13)],
        [(25.57, 14.13), (24.04, 16.67), (27.09, 16.67), (25.57, 14.13)],  # diode
        [(27.6, 14.13), (23.54, 14.13)],
        [(15.41, 15.15), (18.46, 16.16), (18.46, 14.13), (15.41, 15.15)],  # arrow
        [(20.49, 20.23), (20.49, 25.3)],  # source pin
        [(20.49, 10.07), (20.49, 4.99)],  # drain pin
    ]
    for points in lines:
        b.shape(*[(x + px, y + py) for px, py in points], width=0.25, color=red)
    b.scene.wires += [
        ((x + 2, y + 15.15), (x + 7.8, y + 15.15)),
        ((x + 20.49, y + 25.3), (x + 20.49, y + 30)),
        ((x + 20.49, y + 4.99), (x + 20.49, y)),
    ]


def test_easyeda_mosfet_drawn_in_pieces_is_one_part_with_named_pins():
    """Its numbers are hidden, so its pins are known by role: the gate leads to the
    bar, the source is nearer the arrow along the drawing than the drain."""
    b = SceneBuilder()
    _mosfet(b, 0, 0)

    (part,) = symbols.find(b.scene, profile.load("easyeda"))
    assert part.ref == "Q3"
    assert {p.number: p.at for p in part.pins} == {
        "G": (7.8, 15.15),
        "S": (20.49, 25.3),
        "D": (20.49, 4.99),
    }


def test_pnp_transistor_with_its_arrow_over_the_emitter_slant():
    """The emitter's slant ends under the arrowhead at the bar, not on its outline."""
    red, navy = (135, 0, 0), (0, 0, 128)
    b = SceneBuilder()
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "Q1", (25, 128, 27, 129.2), 1.27, 0.0, navy, b.seq))
    for points in (
        [(16.51, 131.24), (16.51, 133.78)],
        [(19.05, 128.7), (24.13, 128.7)],
        [(16.51, 126.16), (16.51, 123.62)],
        [(19.05, 127.94), (17.53, 127.68), (18.29, 126.67), (19.05, 127.94)],
        [(19.05, 130.99), (19.05, 126.41)],
        [(16.51, 131.24), (19.05, 129.46)],
        [(18.29, 127.43), (16.51, 126.16)],
    ):
        b.shape(*points, width=0.25, color=red)
    b.scene.wires += [((16.51, 123.62), (16.51, 120)), ((16.51, 133.78), (16.51, 137))]
    b.scene.wires.append(((24.13, 128.7), (28, 128.7)))

    (part,) = symbols.find(b.scene, profile.load("easyeda"))
    assert {p.number: p.at for p in part.pins} == {
        "B": (24.13, 128.7),
        "E": (16.51, 123.62),
        "C": (16.51, 133.78),
    }


def test_eagle_value_drawn_among_values_does_not_name_the_part():
    """Eagle draws layer by layer, values together and names together. A20 below the
    box looks like a designator and sits as near as U1 above it."""
    b = SceneBuilder()
    b.shape((10, 10), (20, 10), (20, 30), (10, 30), (10, 10))
    for y in (12.54, 15.08, 17.62, 20.16):
        b.shape((10, y), (7.46, y))
        b.shape((20, y), (22.54, y))
    for text in ("10k", "3.3V", "22uF", "100nF", "1k", "NA", "47pF"):
        b.field(text, 60, 60)
    b.field("A20", 11, 30.69)
    for text in ("4k7", "1uF", "GND", "10k", "2.2k", "0R", "5V"):
        b.field(text, 60, 60)
    for text in ("R1", "C2", "C3"):
        b.field(text, 70, 70)
    b.field("U1", 11, 8.0)
    for text in ("R2", "C4", "L1"):
        b.field(text, 70, 70)

    (part,) = [s for s in symbols.find(b.scene, profile.load("eagle")) if len(s.pins) == 8]
    assert part.ref == "U1"


def test_solder_jumper_pins_end_inside_filled_pads():
    """A three-way solder jumper: its pins end inside the pads, and its hidden numbers
    count from the top, then the left."""
    red = (128, 0, 0)
    b = SceneBuilder()
    for y0, y1 in ((20.4, 21.7), (22.5, 23.8), (24.5, 25.8)):  # top, middle, bottom pads
        b.shape((20.4, y0), (23.0, y0), (23.0, y1), (20.4, y1), (20.4, y0), width=0, color=red)
        b.scene.shapes[-1].filled = True
    b.shape((21.7, 25.7), (21.7, 28.2), width=0.15, color=red)
    b.shape((21.7, 18.0), (21.7, 20.6), width=0.15, color=red)
    b.shape((22.8, 23.1), (26.8, 23.1), width=0.15, color=red)
    b.scene.wires += [
        ((21.7, 28.2), (21.7, 33)),
        ((21.7, 18.0), (21.7, 13)),
        ((26.8, 23.1), (31, 23.1)),
    ]
    b.field("SJ1", 24, 18)

    found = [s for s in symbols.find(b.scene, profile.load("eagle")) if s.ref == "SJ1"]
    numbers = {p.number: p.at for s in found for p in s.pins}
    assert numbers == {"1": (21.7, 18.0), "2": (26.8, 23.1), "3": (21.7, 28.2)}


def test_potentiometer_wiper_is_pin_two():
    """Hidden numbers: the wiper, square to the two ends facing apart, is pin 2."""
    b = SceneBuilder()
    b.shape((10, 20), (20, 20), (20, 23), (10, 23), (10, 20))
    b.shape((10, 21.5), (7.46, 21.5))
    b.shape((20, 21.5), (22.54, 21.5))
    b.shape((15, 23), (14.5, 24), (15.5, 24), (15, 23))  # the wiper's arrowhead
    b.shape((15, 24), (15, 26.54))
    b.field("VR1", 11, 17)
    b.scene.wires += [
        ((7.46, 21.5), (3, 21.5)),
        ((22.54, 21.5), (27, 21.5)),
        ((15, 26.54), (15, 30)),
    ]

    (part,) = [s for s in symbols.find(b.scene, profile.load("eagle")) if s.ref]
    assert {p.number: p.at for p in part.pins} == {
        "1": (7.46, 21.5),
        "2": (15, 26.54),
        "3": (22.54, 21.5),
    }


def test_mosfet_with_its_gate_at_the_end_of_its_bar_is_not_a_potentiometer():
    """Its pins face like a potentiometer's, but the gate meets a bar: no numbers are
    made up for it when its arrow cannot be told."""
    b = SceneBuilder()
    b.shape((29.1, 50.68), (29.1, 54.58))  # gate bar
    b.shape((29.69, 50.2), (29.69, 55.07))  # channel
    b.shape((31.05, 50.68), (29.69, 50.68))
    b.shape((31.05, 54.58), (29.69, 54.58))
    b.shape((29.1, 54.58), (27.15, 54.58))  # gate pin
    b.shape((31.05, 54.58), (31.05, 56.53))
    b.shape((31.05, 50.68), (31.05, 48.73))
    b.field("Q2", 32, 52)
    b.scene.wires += [((27.15, 54.58), (24, 54.58)), ((31.05, 56.53), (31.05, 60))]
    b.scene.wires.append(((31.05, 48.73), (31.05, 45)))

    found = [s for s in symbols.find(b.scene, profile.load("eagle")) if s.ref == "Q2"]
    assert found and all(p.number is None for s in found for p in s.pins)


def test_eagle_part_named_by_its_function():
    """A jumper named I2C has no number in its name; a note beside it is no name."""
    b = SceneBuilder()
    b.shape((10, 10), (14, 10), (14, 13), (10, 13), (10, 10))
    b.shape((10, 11.5), (7.46, 11.5))
    b.shape((14, 11.5), (16.54, 11.5))
    b.scene.wires += [((7.46, 11.5), (3, 11.5)), ((16.54, 11.5), (21, 11.5))]
    b.field("Open by default", 10, 14.5)
    b.field("I2C", 10.5, 8.2)

    found = symbols.find(b.scene, profile.load("eagle"))
    fields.whole_names([found])
    (part,) = [s for s in found if s.ref]
    assert part.ref == "I2C"


def test_letters_after_a_designator_are_units_where_the_document_shows_others():
    def part(ref, unit):
        return symbols.Symbol([], (0, 0, 1, 1), ref=ref, unit=unit)

    one, two, alone = part("CM1", "A"), part("CM1", "B"), part("I2", "C")
    usual = part("U5", "A")
    fields.whole_names([[one, alone], [two, usual]])
    assert (one.ref, one.unit, two.unit) == ("CM1", "A", "B")
    assert (alone.ref, alone.unit) == ("I2C", None)
    assert (usual.ref, usual.unit) == ("U5", "A")
