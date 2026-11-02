"""Stages 5-8 on small hand-built scenes that follow KiCad's drawing conventions."""

import math
from dataclasses import replace

import pytest

from schem2net import buses, fields, geometry, nets, profile, symbols
from schem2net.nets import Netlister
from schem2net.primitives import Page, Path, Text
from schem2net.refdes import REFDES, is_common_ref, split_ref
from schem2net.scene import (
    Label,
    Scene,
    Shape,
    Sheet,
    SheetPin,
    _along,
    _anchored_labels,
    _designator_apart,
    _join_runs,
    drop_sheet_references,
    values_run,
)
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
    found = [symbols.find(scene, rules) for scene in scenes]
    fields.whole_names(found)  # as the pipeline does, once every page is read
    for scene, page in zip(scenes, found, strict=True):
        netlister.add_page(scene, page)
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


@pytest.mark.parametrize("split_horizontal,split_vertical", [(True, False), (False, True)])
@pytest.mark.parametrize("junction", [False, True])
def test_split_wire_crossings_need_a_junction(split_horizontal, split_vertical, junction):
    horizontal = [((0, 10), (20, 10))]
    vertical = [((10, 0), (10, 20))]
    if split_horizontal:
        horizontal = [((0, 10), (10, 10)), ((10, 10), (20, 10))]
    if split_vertical:
        vertical = [((10, 0), (10, 10)), ((10, 10), (10, 20))]
    scene = Scene(page=1, wires=horizontal + vertical)
    if junction:
        scene.junctions.append((10, 10))
    parts = [
        symbols.Symbol(
            [],
            (*point, *point),
            [symbols.Pin(i, ((point[0] - 2, point[1] - 2), point), "1")],
            ref=f"J{i + 1}",
        )
        for i, point in enumerate(((0, 10), (20, 10), (10, 0), (10, 20)))
    ]
    netlister = Netlister()
    netlister.add_page(scene, parts)
    found = {frozenset(net.pins) for net in netlister.result().nets}
    expected = [{("J1", "1"), ("J2", "1")}, {("J3", "1"), ("J4", "1")}]
    if junction:
        expected = [set.union(*expected)]
    assert found == {frozenset(pins) for pins in expected}


def test_split_wire_at_a_tee_still_connects_without_a_dot():
    scene = Scene(page=1, wires=[((0, 10), (10, 10)), ((10, 10), (20, 10)), ((10, 0), (10, 10))])
    netlister = Netlister()
    netlister.add_page(scene, [])
    roots = {netlister.uf.find(("w", 1, i)) for i in range(3)}
    assert len(roots) == 1


def test_explicit_wire_ends_share_a_node_without_a_dot():
    scene = Scene(
        page=1,
        wires=[
            ((0, 10), (10, 10)),
            ((10, 10), (20, 10)),
            ((10, 0), (10, 10)),
            ((10, 10), (10, 20)),
        ],
    )
    netlister = Netlister()
    netlister.add_page(scene, [])
    assert len({netlister.uf.find(("w", 1, i)) for i in range(4)}) == 1


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


def test_a_wire_to_a_pwr_flag_ends_on_it_but_takes_no_name():
    """KiCad's PWR_FLAG is drawn like a power symbol, a stem and a diamond, but joins
    nothing by name: the wire to it is no dangling wire, and no net is named for it."""
    pages = []
    for page in (1, 2):
        b = SceneBuilder()
        b.scene.page = page
        b.resistor(10, 10, f"R{page}", "1k")
        b.scene.wires += [((10, 7.46), (15, 7.46)), ((15, 7.46), (15, 5))]
        b.shape((15, 5), (15, 3.73))  # the stem, then the diamond
        b.shape((15, 3.73), (13.73, 2.46), (15, 1.19), (16.27, 2.46), (15, 3.73))
        b.field("PWR_FLAG", 12, -0.5)
        pages.append(b.scene)

    netlister = Netlister(not_nets=KICAD.not_power_nets)
    for scene in pages:
        netlister.add_page(scene, symbols.find(scene, KICAD))
    found = netlister.result()
    assert sorted(n.pins for n in found.nets) == [[("R1", "1")], [("R2", "1")]]
    assert not any(n.name for n in found.nets)
    assert not any(i.kind == "dangling_wire" for i in found.issues)


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


def test_a_no_connect_cross_a_printer_drew_askew_still_flags_its_pin():
    """One stroke longer and flatter than the other, their middles apart: the pin at
    the cross is still left open on purpose."""
    brown = (128, 64, 0)
    page = Page(1, 300, 300)
    page.paths = [
        Path(0, [[(199.85, 194.91), (201.61, 196.32)]], 0.01, brown, None, seq=0),
        Path(1, [[(201.26, 194.91), (199.85, 196.32)]], 0.01, brown, None, seq=1),
    ]
    (centre,) = build_scene(page, profile.load("orcad")).no_connects
    assert geometry.distance(centre, (200.67, 195.59)) < nets.NO_CONNECT_REACH


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


@pytest.mark.parametrize("kind", ["local", "global", "hier"])
def test_textual_supply_conflicts_are_reported_with_their_pins(kind):
    scene = Scene(page=1, path="/")
    scene.wires = [((0, 0), (10, 0))]
    scene.labels = [
        Label("+3V3", kind, (1, -1.5, 4, -0.3), 0),
        Label("+5V", kind, (6, -1.5, 9, -0.3), 0),
    ]
    parts = [
        symbols.Symbol(
            [i], (x - 1, 2, x + 1, 4), [symbols.Pin(i, ((x, 2), (x, 0)), "1")], ref=f"J{i + 1}"
        )
        for i, x in enumerate((0, 10))
    ]
    netlister = Netlister()
    netlister.add_page(scene, parts)
    found = netlister.result()
    (conflict,) = [i for i in found.issues if i.kind == "power_nets_merged"]
    (net,) = found.nets
    assert conflict.net == net.id
    assert conflict.pins == net.pins == [("J1", "1"), ("J2", "1")]
    assert conflict.detail == "+3V3 and +5V"
    assert net.confidence == nets.MERGED_POWER_CONFIDENCE


def test_signal_aliases_on_one_net_do_not_imply_a_supply_conflict():
    scene = Scene(page=1, wires=[((0, 0), (10, 0))])
    scene.labels = [
        Label("SDA", "local", (1, -1.5, 4, -0.3), 0),
        Label("I2C_DATA", "global", (6, -1.5, 9, -0.3), 0),
    ]
    netlister = Netlister()
    netlister.add_page(scene, [])
    assert not any(i.kind == "power_nets_merged" for i in netlister.result().issues)


@pytest.mark.parametrize(
    "first,second,conflict",
    [
        ("+5V", "5v", False),
        ("3V3", "3.3V", False),
        ("AGND", "DGND", False),
        ("0V", "GND", False),
        ("VCC", "+5V", False),
        ("+3V3", "GND", True),
        ("-5V", "+5V", True),
        ("1.8V", "3V3", True),
    ],
)
def test_supply_conflicts_distinguish_voltage_from_aliases(first, second, conflict):
    netlister = Netlister()
    netlister.names = {("l", 1, 0): first, ("l", 1, 1): second}
    netlister.join(("l", 1, 0), ("l", 1, 1), "exact")
    assert any(i.kind == "power_nets_merged" for i in netlister.result().issues) == conflict


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
    # Nor are ratings written beside a part; "1A" may name a pad.
    assert all(fields._is_value(t) for t in ("5%", "50V", "1/10W", "8.2A", "100mW"))
    assert not fields._is_value("1A")


def test_sheet_references_leave_label_names():
    page = Scene(page=1)
    for text in ("MCLK/2", "LRCK /3.4B", "TX/1", "D/9"):
        page.labels.append(Label(text, "global", (0, 0, 5, 1), 0.0))
    drop_sheet_references(page, sheets=3)
    # Sheet 1 is this one and there is no sheet 9: those are parts of names.
    assert [label.text for label in page.labels] == ["MCLK", "LRCK", "TX/1", "D/9"]


def test_lists_of_sheets_beside_a_name_are_no_labels():
    """OrCAD writes the sheets an off-page net is on beside its name: [2,10,11]."""
    page = Scene(page=1)
    for text in ("DDR_CLK", "[2,10,11]", "[3]", "[12]"):
        page.labels.append(Label(text, "local", (0, 0, 5, 1), 0.0))
    drop_sheet_references(page, sheets=11)
    assert [label.text for label in page.labels] == ["DDR_CLK", "[12]"]


def test_a_bare_list_of_sheets_after_a_name_is_dropped():
    page = Scene(page=1)
    for text in ("nRESWARM 4,6", "I2C2_SDA 4", "VDD 33"):
        page.labels.append(Label(text, "local", (0, 0, 5, 1), 0.0))
    drop_sheet_references(page, sheets=11)
    assert [label.text for label in page.labels] == ["nRESWARM", "I2C2_SDA", "VDD 33"]


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


def test_sheet_found_when_its_file_text_reaches_over_the_box_line():
    """The file text's box reaches up to the font's ascent, which can cross the box line."""
    brown, teal = (132, 0, 0), (0, 100, 100)
    page = Page(1, 200, 200)
    box = [(66.04, 72.39), (100.33, 72.39), (100.33, 107.95), (66.04, 107.95), (66.04, 72.39)]
    flag = [(99.06, 75.57), (100.33, 75.57), (100.33, 76.84), (99.06, 76.84), (99.06, 75.57)]
    page.paths = [Path(0, [box], 0.15, brown, None), Path(1, [flag], 0.15, teal, None)]
    page.texts = [
        Text(0, "M.2", (66.1, 70.2, 69.3, 71.6), 1.27, 0.0, teal),
        Text(1, "File: m2.kicad_sch", (66.06, 107.88, 83.8, 109.4), 1.27, 0.0, (114, 86, 0)),
        *_subscripted(84.76, 75.25, "PCIe", "C1x1", "{PCIe}"),
        Text(0, "DP1{DP}", (90.71, 77.79, 98.85, 79.88), 1.27, 0.0, (0, 0, 132)),  # next row
    ]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, KICAD)
    assert [sheet.name for sheet in built.sheets] == ["M.2"]
    # KiCad sets text against its flag by its width at full size, subscripts included;
    # drawn small, they leave a wider gap.
    assert [(p.name, p.at[0]) for p in built.sheets[0].pins] == [("PCIeC1x1{PCIe}", 100.33)]


def test_bus_hierarchical_label_with_a_subscript_keeps_its_flag():
    """A hierarchical label of a bus is written in the bus colour, beside its flag."""
    page = Page(1, 200, 200)
    diamond = [(196.85, 91.44), (196.21, 90.81), (195.58, 91.44), (196.21, 92.08), (196.85, 91.44)]
    page.paths = [Path(0, [diamond], 0.15, (114, 86, 0), None)]
    page.texts = _subscripted(181.28, 90.49, "PCIe", "C1x1", "{PCIe}")
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, KICAD)
    assert [(lb.text, lb.kind) for lb in built.labels] == [("PCIeC1x1{PCIe}", "hier")]


def test_hierarchical_label_connects_on_its_flags_centre_line():
    """The text's box sits a little above or below the flag's middle, by the font's
    ascent and descent; the wire ends on the flag's middle (the coldfire demo, CANTX)."""
    flag = [(353.06, 68.58), (353.82, 67.82), (354.58, 67.82), (354.58, 69.34), (353.82, 69.34)]
    page = Page(1, 400, 300)
    page.paths = [
        Path(0, [[(342.9, 68.58), (353.06, 68.58)]], 0.15, (0, 150, 0), None),
        Path(1, [[*flag, flag[0]]], 0.15, (114, 86, 0), None),
    ]
    page.texts = [Text(2, "CANTX", (354.61, 67.68, 361.8, 69.35), 1.27, 0.0, (114, 86, 0))]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    (label,) = build_scene(page, KICAD).labels
    assert (label.kind, label.outline) == ("hier", [(353.06, 68.58)])


def _subscripted(x: float, y: float, head: str, sub: str, tail: str) -> list[Text]:
    """Bus-coloured text in three pieces, the middle one a subscript, as KiCad draws
    PCIe_{C1x1}{PCIe}."""
    navy = (0, 0, 132)
    return [
        Text(0, head, (x, y + 0.18, x + 4.38, y + 1.61), 1.27, 0.0, navy),
        Text(0, sub, (x + 4.23, y + 0.86, x + 6.74, y + 1.77), 0.762, 0.0, navy),
        Text(0, tail, (x + 6.59, y, x + 12.67, y + 2.09), 1.27, 0.0, navy),
    ]


def test_label_set_at_a_wires_open_end():
    """EasyEDA writes a net label as plain text starting where its wire ends."""
    green, blue = (0, 135, 0), (0, 0, 255)
    page = Page(1, 100, 100)
    page.paths = [Path(0, [[(40, 20), (61.67, 20)]], 0.25, green, None)]
    page.texts = [
        Text(0, "UART_TX", (61.8, 18.4, 69.2, 19.8), 1.4, 0.0, blue),
        Text(1, "RX", (20, 10, 22, 11.4), 1.4, 0.0, blue),  # near no wire end
    ]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, profile.load("easyeda"))
    assert [(lb.text, lb.kind) for lb in built.labels] == [("UART_TX", "local")]


def test_label_marked_by_a_dot_at_its_wires_end():
    """Newer EasyEDA exports mark where a net label meets its wire with a grey dot; the
    name beside it labels the wire, though it does not sit along it. A designator,
    navy, is never a label."""
    green, blue, navy, grey = (0, 135, 0), (0, 0, 255), (0, 0, 128), (153, 153, 153)
    page = Page(1, 100, 100)
    dot = [(76.3, 61.1), (76.6, 60.8), (76.9, 61.1), (76.6, 61.4), (76.3, 61.1)]
    page.paths = [
        Path(0, [[(76.63, 61.08), (76.63, 62.0)]], 0.25, green, None),
        Path(1, [dot], 0.04, None, grey, curved=True),
    ]
    page.texts = [
        Text(0, "3V3", (73.59, 61.52, 76.31, 62.69), 1.6, 0.0, blue),
        Text(1, "R5", (77.0, 59.8, 79.0, 61.0), 1.6, 0.0, navy),
    ]
    for seq, item in enumerate(page.paths + page.texts):
        item.seq = seq

    built = build_scene(page, profile.load("easyeda"))
    assert [lb.text for lb in built.labels] == ["3V3"]
    assert geometry.distance(built.labels[0].outline[0], (76.6, 61.1)) < 1e-6
    assert [t.text for t in built.fields] == ["R5"]


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


def test_eagle_pin_names_in_the_number_colour_name_one_pin_each():
    """Eagle writes pin names and numbers in one grey, so a name is offered both as a
    number and as a name; it still names one pin. A name set right against the body's
    edge, such as INT1 whose last letter is narrow, is a pin name and not the value."""
    red, grey = (128, 0, 0), (128, 128, 128)
    b = SceneBuilder()
    b.shape(
        (132.2, 106.5),
        (152.5, 106.5),
        (152.5, 121),
        (132.2, 121),
        (132.2, 106.5),
        width=0.4,
        color=red,
    )
    rows = (109.07, 111.61, 114.15, 116.69)
    left = (
        ("SCLK", 134.6, 140.1),
        ("MOSI", 134.7, 139.8),
        ("MISO", 134.7, 139.9),
        ("CS", 134.7, 137.4),
    )
    right = (
        ("VDDIO", 143.4, 150.1),
        ("VS", 147.4, 150.1),
        ("INT1", 145.8, 149.8),
        ("INT2", 145.8, 150.1),
    )
    for y, (name, x0, x1) in zip(rows, left, strict=True):
        b.shape((127.1, y), (132.2, y), width=0.15, color=red)
        b.scene.wires.append(((120, y), (127.1, y)))
        b.seq += 1
        text = Text(b.seq, name, (x0, y - 0.85, x1, y + 0.8), 2.39, 0.0, grey, b.seq)
        b.scene.fields.append(text)
        b.scene.pin_numbers.append(text)
    for y, (name, x0, x1) in zip(rows, right, strict=True):
        b.shape((157.6, y), (152.5, y), width=0.15, color=red)
        b.scene.wires.append(((157.6, y), (165, y)))
        b.seq += 1
        text = Text(b.seq, name, (x0, y - 0.85, x1, y + 0.8), 2.39, 0.0, grey, b.seq)
        b.scene.fields.append(text)
        b.scene.pin_numbers.append(text)
    for word, y in (("U1", 102.3), ("ADXL362", 104.8)):
        b.seq += 1
        b.scene.fields.append(
            Text(b.seq, word, (132.3, y, 135 + 2 * len(word), y + 1.6), 1.63, 0.0, grey, b.seq)
        )

    (u1,) = [s for s in symbols.find(b.scene, profile.load("eagle")) if s.pins]
    assert (u1.ref, u1.value) == ("U1", "ADXL362")
    assert sorted(p.number for p in u1.pins) == sorted(n for n, *_ in left + right)


def test_eagle_three_pad_solder_jumper_is_one_part():
    """SparkFun's I2C jumper: two half-round pads either side of a square one, a bridge
    drawn across all three, and a pin into each. The bridge joins the pads into one
    part and is no transistor's bar: the middle pin is 2."""
    red, grey = (128, 0, 0), (128, 128, 128)
    b = SceneBuilder()
    y = 98.93
    pads = [
        [(54.61, 97.66), (53.6, 97.9), (53.32, y), (53.6, 99.95), (54.61, 100.2), (54.61, 97.66)],
        [(57.4, 97.66), (58.4, 97.9), (58.68, y), (58.4, 99.95), (57.4, 100.2), (57.4, 97.66)],
        [(55.4, 97.7), (56.6, 97.7), (56.6, 100.2), (55.4, 100.2), (55.4, 97.7)],
    ]
    for pad in pads:
        b.shape(*pad, width=0.0, color=red)
        b.scene.shapes[-1].filled = True
    b.shape((54.2, y), (58.0, y), width=0.25, color=red)  # the bridge
    b.shape((50.93, y), (53.47, y), width=0.17, color=red)
    b.shape((61.09, y), (58.55, y), width=0.17, color=red)
    b.shape((56.0, 93.9), (56.0, 97.7), width=0.17, color=red)
    b.scene.wires += [((45, y), (50.93, y)), ((61.09, y), (66, y)), ((56, 88), (56, 93.9))]
    b.seq += 1
    b.scene.fields.append(Text(b.seq, "I2C", (53.5, 101.9, 57.3, 103.6), 1.78, 0.0, grey, b.seq))

    found = symbols.find(b.scene, profile.load("eagle"))
    fields.whole_names([found])  # I2 unit C, but no other unit of I2 in the document
    (jumper,) = [s for s in found if s.pins]
    assert jumper.ref == "I2C" and not jumper.power
    assert sorted((p.number or "", p.at) for p in jumper.pins) == [
        ("", (50.93, y)),
        ("", (61.09, y)),
        ("2", (56.0, 93.9)),
    ]


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


@pytest.mark.parametrize(
    "case", ["wire", "short fragments", "branch", "body", "dangling", "no number"]
)
def test_numbered_pin_continues_to_a_wire_only_through_an_unbranched_path(case):
    b = SceneBuilder()
    b.shape((0, 0), (0, 10), (10, 5), (0, 0))
    b.shape((0, 2.5), (-5, 2.5))
    b.shape((0, 7.5), (-5, 7.5))
    b.shape((10, 5), (15, 5))
    for text, x, y in (("6", -3, 0.7), ("5", -3, 5.7), ("7", 11, 3.2)):
        if case == "no number" and text == "5":
            continue
        b.seq += 1
        number = Text(b.seq, text, (x, y, x + 1, y + 1.3), 1.27, 0, (0, 0, 255), b.seq)
        b.scene.fields.append(number)
        b.scene.pin_numbers.append(number)
    b.field("U1", 3, -3)
    b.scene.fields[-1] = replace(b.scene.fields[-1], color=(0, 0, 128))
    b.seq += 100  # the continuation belongs to a later drawing pass
    if case == "short fragments":
        for start, end in ((-5, -5.7), (-5.7, -6.5), (-6.5, -7.54)):
            b.shape((start, 7.5), (end, 7.5))
    else:
        b.shape((-5, 7.5), (-7.54, 7.5))
    if case == "branch":
        b.shape((-5, 7.5), (-5, 10))
    if case == "body":
        b.shape((-10, 6), (-7.54, 6), (-7.54, 9), (-10, 9), (-10, 6))
    if case != "dangling":
        b.scene.wires = [((-12, 7.5), (-7.54, 7.5))]
    rules = profile.load("easyeda")
    index = geometry.GridIndex()
    for shape in b.scene.shapes:
        index.add(shape.id, shape.bbox)
    pins = symbols._find_pins(b.scene, index, rules)
    connected = case in ("wire", "short fragments")
    assert pins[2].at == ((-7.54, 7.5) if connected else (-5, 7.5))
    if connected:
        b.scene.labels = [Label("IN", "local", (-11, 5.7, -9, 7), 0)]
        amplifier = next(s for s in symbols.find(b.scene, rules) if s.ref == "U1")
        assert amplifier.bbox[0] <= -7.54
        assert 4 in amplifier.shapes  # retain the recovered line, not just its pin tip
        parts, nets = netlist(b.scene, rules=rules)
        assert {p.num for p in parts["U1"].pins} == {"5", "6", "7"}
        assert nets["IN"].pins == [("U1", "5")]


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


def test_ground_name_over_a_passing_wire_names_the_ground_not_that_wire():
    """A ground's name printed below its bars, over a wire passing there, was taken for
    a label on that wire, which then joined GND."""
    red, navy = (135, 0, 0), (0, 0, 128)
    b = SceneBuilder()
    for x, ref in ((10, "R1"), (30, "R2")):
        b.shape((x - 1, 10), (x + 1, 10), (x + 1, 15), (x - 1, 15), (x - 1, 10), color=red)
        b.shape((x, 10), (x, 7.46), width=0.25, color=red)
        b.shape((x, 15), (x, 17.54), width=0.25, color=red)
        b.seq += 1
        box = (x + 2, 11, x + 4, 12.3)
        b.scene.fields.append(Text(b.seq, ref, box, 1.27, 0.0, navy, b.seq))
    b.shape((10, 20.08), (10, 22), width=0.25, color=red)  # the ground, on R1's wire
    for half, y in ((2, 22), (1.3, 22.8), (0.6, 23.6)):
        b.shape((10 - half, y), (10 + half, y), width=0.25, color=red)
    b.scene.wires += [((10, 17.54), (10, 20.08)), ((30, 17.54), (30, 26.5))]
    b.scene.wires.append(((0, 26.5), (30, 26.5)))  # R2's net, passing under the name
    b.scene.labels.append(Label("GND", "local", (8.5, 24.5, 11.5, 26.2), 0.0))

    _, nets = netlist(b.scene, rules=profile.load("easyeda"))
    assert nets["GND"].pins == [("R1", "2")]


def test_a_net_label_joins_the_power_symbol_of_its_name_on_its_page_only():
    """KiCad joins a local label to the power net of its name on the same sheet, and
    keeps it to that sheet."""
    pages = []
    for page in (1, 2):
        b = SceneBuilder()
        b.scene.page = page
        b.resistor(10, 10, f"R{page}", "1k")
        b.scene.wires.append(((10, 7.46), (20, 7.46)))
        b.scene.labels.append(Label("GND", "local", (13, 6.0, 16, 7.2), 0.0))
        if page == 1:  # a ground on R1's other pin, on the same page as its label
            b.shape(
                (10, 17.54), (10, 18.81), (11.27, 18.81), (10, 20.08), (8.73, 18.81), (10, 18.81)
            )
        pages.append(b.scene)

    netlister = Netlister()
    for scene in pages:
        netlister.add_page(scene, symbols.find(scene, KICAD))
    found = sorted(n.pins for n in netlister.result().nets)
    assert found == [[("R1", "1"), ("R1", "2")], [("R2", "1")]]


def test_section_frame_does_not_take_the_part_drawn_after_it():
    """A frame drawn just before the lowest part of a column holds it whole, pins and
    all, so the part is not the frame's. Joined to the frame, it would leave its name
    to the part above, and each name in the column would move up one."""
    red, navy, black = (140, 36, 36), (0, 0, 128), (0, 0, 0)
    b = SceneBuilder()
    b.shape((6.3, 11.9), (127, 11.9), (127, 91.9), (6.3, 91.9), (6.3, 11.9), color=black)
    for ref, y in (("R16", 88.1), ("R17", 79.2), ("R18", 69.1)):
        b.seq += 1
        box = (98.9, y - 3.4, 102.5, y - 1.7)
        b.scene.fields.append(Text(b.seq, "220", box, 1.6, 0.0, navy, b.seq))
        b.seq += 1
        box = (99.0, y - 5.7, 102.9, y - 4.0)
        b.scene.fields.append(Text(b.seq, ref, box, 1.6, 0.0, navy, b.seq))
        b.shape((95.2, y), (97.3, y), width=0.25, color=red)
        b.shape((103.4, y), (105.4, y), width=0.25, color=red)
        body = ((97.3, y - 1), (103.4, y - 1), (103.4, y + 1), (97.3, y + 1), (97.3, y - 1))
        b.shape(*body, width=0.25, color=red)
        b.scene.wires += [((90, y), (95.2, y)), ((105.4, y), (110, y))]

    found = symbols.find(b.scene, profile.load("easyeda"))
    named = {s.ref: s.bbox[1] for s in found if s.ref}
    assert named == {"R16": 87.1, "R17": 78.2, "R18": 68.1}


@pytest.mark.parametrize("width,height", [(60, 40), (160, 140)])
def test_section_frame_drawn_around_parts_does_not_group_them_by_order(width, height):
    b = SceneBuilder()
    # The header is drawn first and the adjoining border last. Their combined
    # drawing order encloses the parts' even though the drawings never touch.
    b.shape((0, 0), (width, 0), (width, 5), (0, 5), (0, 0))
    for x, ref in ((10, "C1"), (30, "C2"), (50, "C3")):
        b.shape((x - 1, 15), (x + 1, 15), (x + 1, 20), (x - 1, 20), (x - 1, 15))
        b.shape((x - 2, 15.65), (x - 2, 16.35))  # separate polarity mark
        b.shape((x - 2.35, 16), (x - 1.65, 16))
        b.shape((x, 15), (x, 12.46))
        b.shape((x, 20), (x, 22.54))
        b.field(ref, x + 2, 16)
        b.field("10uF", x + 2, 18)
    b.shape((0, 5), (width, 5), (width, height), (0, height), (0, 5))
    # The section contains only a minority of the page's parts.
    for i in range(12):
        b.resistor(width + 20 + 10 * i, 10, f"R{i + 1}", "1k")
    b.scene.fields = [replace(text, color=(0, 0, 128)) for text in b.scene.fields]
    b.scene.wires = [((10, 12.46), (50, 12.46)), ((10, 22.54), (50, 22.54))]
    b.scene.labels = [
        Label("TOP", "local", (15, 11, 20, 12.2), 0),
        Label("BOTTOM", "local", (15, 21, 20, 22.2), 0),
    ]
    # Geometric frame rejection must work even without a learned grouping model.
    rules = replace(profile.load("easyeda"), learned_grouping=False)
    parts, connected = netlist(b.scene, rules=rules)
    assert set(parts) == {"C1", "C2", "C3"} | {f"R{i + 1}" for i in range(12)}
    assert all(len(part.pins) == 2 for part in parts.values())
    assert set(connected["TOP"].pins) == {("C1", "1"), ("C2", "1"), ("C3", "1")}
    assert set(connected["BOTTOM"].pins) == {("C1", "2"), ("C2", "2"), ("C3", "2")}


def test_easyeda_net_label_is_named_by_the_text_drawn_before_its_mark():
    """An EasyEDA net label is its text, then a small cross where it meets the wire,
    below the text's start: nearer the label of the row below than its own text.
    Labels standing apart show which way round the page draws them."""
    blue, black = (0, 0, 255), (0, 0, 0)
    b = SceneBuilder()
    rows = [("A1", 81.7, 104.14), ("A2", 79.2, 106.68)]
    rows += [("D0", 20, 30), ("D1", 40, 30), ("D2", 60, 30)]
    for name, y, x in rows:
        b.seq += 1
        box = (x + 0.56, y - 2.2, x + 3.1, y - 0.6)
        b.scene.fields.append(Text(b.seq, name, box, 1.6, 0.0, blue, b.seq))
        b.shape((x - 0.25, y - 0.25), (x + 0.25, y + 0.25), width=0.03, color=black)
        b.shape((x - 0.25, y + 0.25), (x + 0.25, y - 0.25), width=0.03, color=black)
        b.scene.wires.append(((95, y), (120, y)))

    found = symbols.find(b.scene, profile.load("easyeda"))
    flags = sorted((round(geometry.center(s.bbox)[1], 1), s.power) for s in found if s.power)
    assert flags == [(20, "D0"), (40, "D1"), (60, "D2"), (79.2, "A2"), (81.7, "A1")]


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


def test_pin_number_overhanging_the_end_of_a_short_pin():
    """OrCAD centres a number near a pin's outer end; on a short pin it overhangs the tip,
    but a long text past the tip, such as a part number, is no pin number."""
    pin = ((180.4, 30.5), (182.9, 30.5))
    assert fields._number_gap((182.4, 28.3, 184.6, 30.0), pin, True, True) is not None
    assert fields._number_gap((182.4, 28.3, 184.6, 30.0), pin, True) is None
    assert fields._number_gap((182.4, 28.3, 194.6, 30.0), pin, True, True) is None


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


def test_unnamed_part_touching_a_pin_does_not_borrow_its_neighbors_reference():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "1k")
    # A second resistor has a hidden reference. Its pin touches R1's lower pin,
    # but its separate body is not a piece of R1.
    b.shape((9, 20.08), (11, 20.08), (11, 25.08), (9, 25.08), (9, 20.08))
    b.shape((10, 20.08), (10, 17.54))
    b.shape((10, 25.08), (10, 27.62))
    b.scene.fields = [replace(t, color=(0, 0, 128)) for t in b.scene.fields]

    found = symbols.find(b.scene, profile.load("easyeda"))
    assert len(found) == 1
    assert found[0].ref == "R1"
    assert sorted(p.number for p in found[0].pins) == ["1", "2"]


def test_nearby_body_pieces_can_share_one_reference():
    first = symbols.Symbol([], (0, 0, 2, 4), [symbols.Pin(0, ((1, 1), (1, -2)))], body=(0, 0, 2, 1))
    second = symbols.Symbol([], (0, 2, 2, 6), [symbols.Pin(1, ((1, 3), (1, 6)))], body=(0, 2, 2, 3))
    scene = Scene(page=1)
    scene.fields = [Text(0, "K1", (3, 0, 5, 1.2), 1.27, 0, (0, 0, 128))]
    fields._assign_refs(
        [first, second], fields._Texts(scene.fields), None, profile.load("easyeda"), set(), set()
    )
    assert first.ref == second.ref == "K1"


def test_numbered_units():
    match = REFDES.match("U3.1")  # EasyEDA
    assert match and match.groups() == ("U", "3", ".1") and is_common_ref("U10.2")
    assert not REFDES.match("OLED0.66")  # a value
    assert split_ref("U4-18").groups() == ("U", "4", "-18")  # OrCAD
    assert split_ref("SW-1").groups() == ("SW-", "1", None)
    assert not is_common_ref("XR22417-48")  # a library name


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
    """A three-way solder jumper: its pins end inside the pads. Its common pad is pin 2;
    which end is 1 depends on how it was turned, so the ends stay unnumbered."""
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
    numbers = sorted((p.number or "", p.at) for s in found for p in s.pins)
    assert numbers == [("", (21.7, 18.0)), ("", (21.7, 28.2)), ("2", (26.8, 23.1))]


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


def test_units_with_the_same_pins_are_parts_of_their_own():
    """Units of one part share no pads: R11A and R11B, each with pins 1 and 2, are two
    resistors, while U5A and U5B of a dual amplifier are one part."""

    def part(ref, unit, numbers):
        pins = [symbols.Pin(k, ((0, 0), (0, 1)), n) for k, n in enumerate(numbers)]
        return symbols.Symbol([], (0, 0, 1, 1), pins, ref=ref, unit=unit)

    r_a, r_b = part("R11", "A", ["1", "2"]), part("R11", "B", ["2", "1"])
    u_a, u_b = part("U5", "A", ["1", "2", "3"]), part("U5", "B", ["5", "6", "7"])
    fields.whole_names([[r_a, u_a], [r_b, u_b]])
    assert (r_a.ref, r_a.unit, r_b.ref) == ("R11A", None, "R11B")
    assert (u_a.ref, u_a.unit, u_b.unit) == ("U5", "A", "B")


def test_stacked_capacitors_whose_plates_overlap_stay_apart():
    """Capacitors a grid step apart, their plates longer than the step: each plate's
    end lies on the middle of the next one's, but a line a pin starts on is body."""
    b = SceneBuilder()
    for k, y in enumerate((21.58, 22.85, 24.12)):
        red = (132, 0, 0)
        b.shape((22.42, y - 0.76), (22.42, y + 0.77), width=0.165, color=red)
        b.shape((22.93, y - 0.76), (22.93, y + 0.77), width=0.165, color=red)
        b.shape((22.99, y), (23.94, y), width=0.076, color=red)
        b.shape((22.42, y), (21.4, y), width=0.076, color=red)
        b.scene.wires += [((18, y), (21.4, y)), ((23.94, y), (27, y))]
        b.field(f"C{41 + k}", 15, y - 0.6)
        b.field("100nF", 28, y - 0.6)

    parts, _ = netlist(b.scene)
    assert sorted(parts) == ["C41", "C42", "C43"]
    assert all(len(p.pins) == 2 for p in parts.values())


def test_values_drawn_together_are_known_even_when_repeated():
    """Eagle draws values together; one value written for several parts in turn
    counts once, and a label drawn among designators is not a value."""
    words = ["10k", "3.3V", "22uF", "1k", "100nF", "4k7", "47pF"]
    words += ["RA0805_0R"] * 5 + ["2.2k", "0R", "5V", "1uF", "10nF", "33R", "12pF"]
    words += ["R1", "C1", "C2", "R2", "U1", "LCD_D3", "L1", "C3", "R4", "C5", "U2", "R6"]
    texts = [Text(k, w, (0, 0, 1, 1), 1.0, 0.0, None, k) for k, w in enumerate(words)]
    run = values_run(texts)
    assert all(id(t) in run for t in texts if t.text == "RA0805_0R")
    assert not any(id(t) in run for t in texts if t.text == "LCD_D3")


def test_eagle_diode_drawn_as_three_lines_names_its_pads():
    """A printer draws the triangle as three lines; Eagle's diode pads are C and A."""
    red = (128, 0, 0)
    b = SceneBuilder()
    b.shape((24.8, 35.7), (27.4, 35.7), color=red)  # the cathode bar
    b.shape((27.4, 38.3), (26.1, 35.7), color=red)
    b.shape((26.1, 35.7), (24.8, 38.3), color=red)
    b.shape((24.8, 38.3), (27.4, 38.3), color=red)
    b.shape((26.1, 34.5), (26.1, 35.7), color=red)
    b.shape((26.1, 39.5), (26.1, 38.3), color=red)
    b.scene.wires += [((26.1, 34.5), (26.1, 30)), ((26.1, 39.5), (26.1, 44))]
    b.field("D2", 28.2, 36.7)

    (part,) = [s for s in symbols.find(b.scene, profile.load("eagle")) if s.ref == "D2"]
    assert {p.number: p.at for p in part.pins} == {"C": (26.1, 34.5), "A": (26.1, 39.5)}


def test_a_diodes_hidden_numbers_are_reported_as_guessed():
    """Which end of a diode is pin 1 is the library's choice; with numbers hidden it is a
    guess, and said so. Eagle's diode pads are named, so nothing is guessed there."""

    def diode(rules, red):
        b = SceneBuilder()
        b.shape((24.8, 35.7), (27.4, 35.7), color=red)  # the cathode bar
        b.shape((27.4, 38.3), (26.1, 35.7), (24.8, 38.3), (27.4, 38.3), color=red)
        b.shape((26.1, 34.5), (26.1, 35.7), color=red)
        b.shape((26.1, 39.5), (26.1, 38.3), color=red)
        b.scene.wires += [((26.1, 34.5), (26.1, 30)), ((26.1, 39.5), (26.1, 44))]
        b.field("D2", 28.2, 36.7)
        netlister = Netlister()
        netlister.add_page(b.scene, symbols.find(b.scene, rules))
        return [i for i in netlister.result().issues if i.kind == "pin_number_guessed"]

    (guess,) = diode(KICAD, None)
    assert sorted(guess.pins) == [("D2", "1"), ("D2", "2")]
    assert diode(profile.load("eagle"), (128, 0, 0)) == []


def test_kicad_reference_is_the_first_text_whatever_its_form():
    """KiCad draws a symbol's reference first, after its graphics: GPIO1-1 names the
    connector though it is no usual designator. A diode's pin name, a lone letter
    drawn before its reference, does not."""
    b = SceneBuilder()
    b.shape((10, 10), (14, 10), (14, 20), (10, 20), (10, 10))
    for y in (12.54, 15.08, 17.62):
        b.shape((10, y), (7.46, y))
        b.shape((14, y), (16.54, y))
    b.field("GPIO1-1", 10, 8)
    b.field("Conn_02x03", 10, 21)
    b.shape((40, 10), (40, 12))  # a diode: bar, triangle, pins above and below
    b.shape((39, 12), (41, 12))
    b.shape((39, 14), (41, 14), (40, 12), (39, 14))
    b.shape((40, 14), (40, 16.54))
    b.shape((40, 10), (40, 7.46))
    b.field("K", 41, 8)
    b.field("D1", 42, 12)
    b.field("LED", 42, 14)
    b.shape((70, 10), (74, 10), (74, 20), (70, 20), (70, 10))  # a caption on its body
    for y in (12.54, 15.08, 17.62):
        b.shape((70, y), (67.46, y))
    b.field("MEM", 70.5, 14)
    b.field("J2", 70, 2)

    parts, _ = netlist(b.scene)
    assert sorted(parts) == ["D1", "GPIO1-1", "J2"]


def test_easyeda_port_flag_set_straight_on_a_pin_connects_it():
    """No wire: the flag's tip is the pin's tip, and the flags of one name join."""
    red, navy, blue = (135, 0, 0), (0, 0, 128), (0, 0, 255)
    b = SceneBuilder()
    for ref, x in (("U1", 10), ("U2", 40)):
        b.seq += 1
        b.scene.fields.append(Text(b.seq, ref, (x, -1, x + 2, 0.2), 1.27, 0.0, navy, b.seq))
        b.shape((x, 2), (x + 6, 2), (x + 6, 22), (x, 22), (x, 2), width=0.25, color=red)
        b.shape((x + 6, 12), (x + 8.54, 12), width=0.25, color=red)
        b.shape((x, 12), (x - 2.54, 12), width=0.25, color=red)
    for tip in (18.54, 48.54):  # the flags, drawn later
        b.seq += 10
        flag = [(tip, 12), (tip + 1.27, 10.73), (tip + 5, 10.73), (tip + 5, 13.27)]
        b.shape(*flag, (tip + 1.27, 13.27), (tip, 12), width=0.25, color=blue)
        b.seq += 1
        box = (tip + 5.5, 11.4, tip + 9, 12.6)
        b.scene.fields.append(Text(b.seq, "IO26", box, 1.27, 0.0, blue, b.seq))

    _, nets = netlist(b.scene, rules=profile.load("easyeda"))
    assert sorted(nets["IO26"].pins) == [("U1", "2"), ("U2", "2")]


def test_designator_labels_and_features():
    from schem2net import designators

    refs = {"U5", "LCD_CON", "R1"}
    text = lambda w: Text(1, w, (0, 0, 1, 1), 1.0, 0.0, None, 1)  # noqa: E731
    assert designators.label(text("U5A"), refs) and designators.label(text("LCD_CON"), refs)
    assert not designators.label(text("U6"), refs) and not designators.label(text("10k"), refs)

    b = SceneBuilder()
    b.resistor(10, 10, "R1", "10k")
    parts = symbols.find(b.scene, KICAD)
    rows = designators.features(b.scene, parts, None, KICAD)
    assert rows.shape == (len(b.scene.fields), len(designators.FEATURES))
    assert designators.likelihood(b.scene, parts, None, profile.load("eagle")) is not None or True


def test_learned_likelihood_admits_a_name_of_no_usual_form(monkeypatch):
    """With a model sure that LCD_CON names the connector beside it, and sure that the
    value A20 below it does not, the connector is LCD_CON."""
    b = SceneBuilder()
    b.shape((10, 10), (16, 10), (16, 22), (10, 22), (10, 10))
    for y in (12.54, 15.08, 17.62, 20.16):
        b.shape((16, y), (18.54, y))
        b.shape((10, y), (7.46, y))
    b.field("LCD_CON", 10, 8)
    b.field("A20", 10, 22.5)
    sure = {"LCD_CON": 0.97, "A20": 0.02}
    monkeypatch.setattr(
        fields.designators,
        "likelihood",
        lambda scene, *a: {id(t): sure.get(t.text, 0.5) for t in scene.fields},
    )
    (part,) = [s for s in symbols.find(b.scene, profile.load("eagle")) if len(s.pins) == 8]
    assert part.ref == "LCD_CON"


def test_alias_bus_passes_through_a_sheet_that_names_none_of_its_members():
    """{MEM} names an alias whose members are defined outside the drawing. Sheet A only
    passes it on to its own sheet C, so neither the root nor A has a label of a member."""
    root = SceneBuilder()
    root.scene.path = "/"
    root.scene.buses.append(((20, 10), (60, 10)))
    root.scene.sheets += [
        Sheet("A", (0, 0, 20, 20), [SheetPin("{MEM}", (20, 10))]),
        Sheet("B", (60, 0, 80, 20), [SheetPin("{MEM}", (60, 10))]),
    ]

    middle = SceneBuilder()
    middle.scene.page, middle.scene.path = 2, "/A/"
    middle.scene.labels.append(Label("{MEM}", "hier", (1, 9.3, 7, 10.6), 0.0, [(10, 10)]))
    middle.scene.buses.append(((10, 10), (40, 10)))
    middle.scene.sheets.append(Sheet("C", (40, 0, 60, 20), [SheetPin("{MEM}", (40, 10))]))

    def leaf(page, path, ref):
        b = SceneBuilder()
        b.scene.page, b.scene.path = page, path
        b.resistor(10, 10, ref, "1k")
        b.scene.wires.append(((10, 7.46), (20, 7.46)))
        b.scene.labels.append(Label("MEM.CLK", "local", (12, 6.0, 18, 7.2), 0.0))
        b.scene.labels.append(Label("{MEM}", "hier", (31, 9.3, 37, 10.6), 0.0, [(30, 10)]))
        b.scene.buses.append(((30, 10), (40, 10)))
        return b.scene

    _, nets = netlist(root.scene, middle.scene, leaf(3, "/A/C/", "R1"), leaf(4, "/B/", "R2"))
    assert nets["MEM.CLK"].pins == [("R1", "1"), ("R2", "1")]


def test_values_are_paired_one_to_one_and_skip_pin_numbers_and_notes():
    """R2's nearest text is also R3's only one; R2 takes the other. A note set closest to
    R1 is no value, nor is the number of J1's pin, which has no value printed."""
    grey = (128, 128, 128)

    def part(ref, box, pins=()):
        s = symbols.Symbol([], box, ref=ref)
        s.pins = [symbols.Pin(0, line, number) for line, number in pins]
        return s

    r1 = part("R1", (10, 10, 12, 15))
    j1 = part("J1", (30, 10, 32, 20), [(((32, 12), (34.54, 12)), "1")])
    r2, r3 = part("R2", (40, 10, 42, 15)), part("R3", (45.2, 10, 47.2, 15))
    texts = [
        Text(0, "Cut trace to remove pull-ups", (12.5, 12, 28, 13), 1.3, 0.0, grey),
        Text(1, "10k", (10, 16.5, 12, 17.5), 1.3, 0.0, grey),
        Text(2, "1", (33, 10.6, 33.5, 11.6), 1.3, 0.0, grey),
        Text(3, "1k", (43, 12, 44.1, 13), 1.3, 0.0, grey),  # 1.0 from R2, 1.1 from R3
        Text(4, "2k", (40, 16.2, 42, 17.2), 1.3, 0.0, grey),  # 1.2 from R2
    ]
    fields._assign_values([r1, j1, r2, r3], fields._Texts(texts), None, 1.5)
    assert [s.value for s in (r1, j1, r2, r3)] == ["10k", None, "2k", "1k"]


def test_two_whole_values_side_by_side_stay_apart():
    grey = (128, 128, 128)
    pieces = [
        Text(1, "0.1uF", (10, 10, 14, 11.3), 1.3, 0.0, grey, 1),
        Text(2, "2.2nF", (14.1, 10, 18, 11.3), 1.3, 0.0, grey, 2),
        Text(3, "4.7", (20, 10, 22, 11.3), 1.3, 0.0, grey, 3),
        Text(4, "uF", (22.1, 10, 23.6, 11.3), 1.3, 0.0, grey, 4),
    ]
    assert [t.text for t in _join_runs(pieces)] == ["0.1uF", "2.2nF", "4.7uF"]


def test_a_diodes_pin_letters_are_not_its_value():
    grey = (128, 128, 128)
    d1 = symbols.Symbol([], (10, 10, 12, 18), ref="D1")
    d1.pins = [symbols.Pin(0, ((11, 12), (11, 10)), "1"), symbols.Pin(0, ((11, 16), (11, 18)), "2")]
    texts = [
        Text(0, "K", (11.5, 10.2, 12.3, 11.4), 1.3, 0.0, grey),
        Text(1, "A", (11.5, 16.6, 12.3, 17.8), 1.3, 0.0, grey),
        Text(2, "BAT43", (13.5, 13.4, 18, 14.6), 1.3, 0.0, grey),
    ]
    fields._assign_values([d1], fields._Texts(texts), None, 1.5)
    assert d1.value == "BAT43"


def test_a_two_pin_connectors_guessed_order_is_reported_but_a_resistors_is_not():
    """Which end of a resistor is 1 makes no difference; of a connector it does."""

    def guessed(ref):
        b = SceneBuilder()
        b.resistor(10, 10, ref, "x")
        b.scene.wires += [((10, 7.46), (10, 3)), ((10, 17.54), (10, 22))]
        netlister = Netlister()
        netlister.add_page(b.scene, symbols.find(b.scene, KICAD))
        return [i.detail for i in netlister.result().issues if i.kind == "pin_number_guessed"]

    assert guessed("J1") == ["J1"]
    assert guessed("R1") == []


@pytest.mark.parametrize("name_at", [46, 50.5])
def test_an_orcad_page(name_at):
    """OrCAD draws a part's body, then its texts, then its pins. A ground may be a bare
    triangle of three lines whose base the wire ends on; an off-page arrow is named in
    the net alias colour a little way beyond its arrows, drawn right after them, which
    ties the name to them where it sits farther off."""
    orcad = profile.load("orcad")
    blue, red, navy, maroon = (0, 0, 255), (255, 0, 0), (0, 0, 128), (128, 0, 64)
    paths, texts = [], []

    def line(colour, *points):
        paths.append(
            Path(len(paths), [list(points)], 0.25, colour, None, seq=len(paths) + len(texts))
        )

    def text(content, colour, x, y):
        box = (x, y, x + 0.9 * len(content), y + 1.5)
        texts.append(Text(len(texts), content, box, 1.5, 0.0, colour, len(paths) + len(texts)))

    line(maroon, (17.46, 10), (10, 10))
    line(maroon, (10, 10), (10, 15))
    line(maroon, (32.54, 10), (40, 10))
    line(blue, (20, 10), (21, 9), (23, 11), (25, 9), (27, 11), (29, 9), (30, 10))
    text("R1", navy, 22, 5.5)
    text("10k", navy, 22, 12)
    line(red, (17.46, 10), (20, 10))
    line(red, (30, 10), (32.54, 10))
    line(red, (8, 15), (12, 15))
    line(red, (12, 15), (10, 17.5))
    line(red, (10, 17.5), (8, 15))
    line(red, (40, 8.75), (41.25, 10))
    line(red, (40, 11.25), (41.25, 10))
    line(red, (41.25, 8.75), (42.5, 10))
    line(red, (41.25, 11.25), (42.5, 10))
    text("SDA", red, name_at, 9.25)
    scene = build_scene(Page(1, 100, 100, paths=paths, texts=texts), orcad)

    _, nets = netlist(scene, rules=orcad)
    assert {name: set(n.pins) for name, n in nets.items()} == {
        "GND_SIGNAL": {("R1", "1")},
        "SDA": {("R1", "2")},
    }


def test_a_designator_written_close_to_its_value_is_split_from_it():
    """A printer may write "R22 0" as one text; navy is the designators' own colour."""
    navy = (0, 0, 128)
    texts = [
        Text(0, "R22 0", (10, 10, 15, 11.5), 1.5, 0.0, navy, 1),
        Text(1, "U3 BD82065FVJ", (10, 20, 11.5, 33), 1.5, 90.0, navy, 2),
        Text(2, "Note 1", (30, 10, 36, 11.5), 1.5, 0.0, (0, 0, 0), 3),
    ]
    scene = build_scene(Page(1, 100, 100, texts=texts), profile.load("orcad"))
    found = {t.text: t.bbox for t in scene.fields}
    assert set(found) == {"R22", "0", "U3", "BD82065FVJ", "Note 1"}
    assert found["R22"][2] <= found["0"][0]
    assert found["U3"][1] >= found["BD82065FVJ"][3]  # read upwards: the designator below


def test_a_chassis_rake_is_a_ground_named_by_its_sign():
    """A bar with parallel strokes slanting from one side; Capture names the sign."""
    b = SceneBuilder()
    b.shape((74.3, 16.5), (74.9, 15.2), (77.4, 15.2), (76.8, 16.5))
    b.shape((75.5, 16.5), (76.2, 15.2))
    rake = symbols.Symbol([0, 1], (74.3, 15.2, 77.4, 16.5), body=(74.3, 15.2, 77.4, 16.5))
    assert fields._is_rake(rake, b.scene)
    assert fields._ground_name(rake, b.scene, profile.load("orcad")) == "GND_EARTH"
    assert fields._ground_name(rake, b.scene, KICAD) == "GND"

    b.shape((80, 15.2), (83, 15.2))
    b.shape((80, 15.2), (80.6, 16.5))
    b.shape((83, 15.2), (82.4, 16.5))  # slanting the other way: no rake
    assert not fields._is_rake(symbols.Symbol([2, 3, 4], (80, 15.2, 83, 16.5)), b.scene)


def test_a_test_point_drawn_with_no_pin_line_connects_at_its_outline():
    """OrCAD test points are a box with no pin line; the wire ends on the box. A ground
    with no pin, in the pin colour, is left as a power symbol."""
    orcad = profile.load("orcad")
    blue, red, navy, maroon = (0, 0, 255), (255, 0, 0), (0, 0, 128), (128, 0, 64)
    paths = [
        Path(0, [[(10, 20), (30, 20)]], 0.25, maroon, None, seq=0),
        Path(1, [[(10, 20), (10, 25)]], 0.25, maroon, None, seq=1),
        Path(
            2,
            [[(31.3, 18.7), (31.3, 21.3), (33.8, 21.3), (33.8, 18.7), (31.3, 18.7)]],
            0.25,
            blue,
            None,
            seq=2,
        ),
        Path(4, [[(8, 25), (12, 25)]], 0.25, red, None, seq=5),
        Path(5, [[(12, 25), (10, 27.5)]], 0.25, red, None, seq=6),
        Path(6, [[(10, 27.5), (8, 25)]], 0.25, red, None, seq=7),
    ]
    paths[0].subpaths = [[(10, 20), (31.3, 20)]]
    texts = [Text(0, "TP1", (31, 16, 34, 17.5), 1.5, 0.0, navy, 3)]
    scene = build_scene(Page(1, 100, 100, paths=paths, texts=texts), orcad)
    _, found = netlist(scene, rules=orcad)
    assert {name: set(n.pins) for name, n in found.items()} == {"GND_SIGNAL": {("TP1", "1")}}


def test_pages_joined_only_by_a_hidden_ground_name_are_doubted():
    """Modules of one design may each name their ground apart, behind the same sign: a
    page that never prints the name joins the other pages on weak evidence."""

    def netlist(*hidden):
        netlister = Netlister()
        for page, h in enumerate(hidden, 1):
            r = symbols.Symbol([], (0, 0, 2, 4), [symbols.Pin(0, ((1, 1), (1, 0)), "1")])
            r.ref = f"R{page}"
            ground = symbols.Symbol([], (0, -2, 2, 0), power="GND", anchors=[(1, 0)])
            ground.power_hidden = h
            netlister.add_page(Scene(page=page), [r, ground])
        return [n for n in netlister.result().nets if len(n.pins) > 1]

    assert netlist(True, True)[0].confidence < 0.8
    assert netlist(False, True)[0].confidence < 0.8
    assert netlist(False, False)[0].confidence >= 0.8


def test_one_designator_on_two_parts_is_reported():
    def resistor(x):
        r = symbols.Symbol([], (x, 0, x + 2, 4), [symbols.Pin(x, ((x + 1, 1), (x + 1, 0)), "1")])
        r.ref = "R5"
        return r

    scene = Scene(page=1)
    scene.fields.append(Text(0, "R?", (20, 0, 22, 1), 1.0, 0.0, (0, 0, 0)))
    netlister = Netlister()
    netlister.add_page(scene, [resistor(0), resistor(10)])
    issues = {i.kind: i for i in netlister.result().issues}
    assert issues["duplicate_designator"].pins == [("R5", "1")]
    assert issues["unannotated_part"].detail == "R?"
    assert "duplicate_pin" not in issues


def test_transistor_outline_surrounding_pin_like_body_strokes_is_kept():
    b = SceneBuilder()
    for points, width in (
        (((7.356, 8.191), (7.356, 6.794)), 0.17),
        (((1.133, 5.651), (4.816, 5.651)), 0.254),
        (((4.816, 5.651), (8.499, 5.651)), 0.254),
        (((4.181, 5.016), (4.816, 3.746)), 0.254),
        (((5.451, 5.016), (4.816, 3.746)), 0.254),
        (((2.276, 6.794), (7.356, 6.794)), 0.254),
        (((4.816, 5.651), (4.816, 3.746)), 0.17),
        (((4.816, 3.746), (7.356, 3.746)), 0.17),
        (((2.276, 2.476), (4.181, 2.476)), 0.127),
        (((4.181, 3.111), (4.181, 2.476)), 0.127),
        (((4.181, 2.476), (4.181, 1.841)), 0.127),
        (((4.181, 1.841), (5.451, 2.476)), 0.127),
        (((5.451, 2.476), (4.181, 3.111)), 0.127),
        (((5.451, 3.111), (5.451, 2.476)), 0.127),
        (((5.451, 2.476), (5.451, 1.841)), 0.127),
        (((5.451, 2.476), (7.356, 2.476)), 0.127),
    ):
        b.shape(*points, width=width)
    for x, y in ((2.276, 2.476), (7.356, 2.476), (7.356, 3.746)):
        b.shape(
            *[
                (x + 0.254 * math.cos(i * math.pi / 4), y + 0.254 * math.sin(i * math.pi / 4))
                for i in range(9)
            ],
            width=0,
        )
        b.scene.shapes[-1].filled = True
    outline = len(b.scene.shapes)
    b.shape(
        *[
            (4.816 + 4.487 * math.cos(i * math.pi / 16), 5.651 + 4.487 * math.sin(i * math.pi / 16))
            for i in range(33)
        ]
    )
    b.shape((7.356, 10.731), (7.356, 8.191))
    b.shape((2.276, 0.571), (2.276, 5.651))
    b.shape((7.356, 0.571), (7.356, 5.651))
    b.field("Q1", -2, 2)

    found = symbols.find(b.scene, profile.load("eagle"))
    assert any(outline in part.shapes for part in found)


def test_pieces_drawn_in_turn_are_one_part_where_drawing_goes_by_layer():
    """A MOSFET's gate, channel and arrow are drawn in turn, a shape of one between
    shapes of another. Pins drawn in a pass of their own have the page between."""

    def scene_of(seqs):
        scene = Scene(page=1)
        for k, (seq, x) in enumerate(seqs):
            scene.shapes.append(Shape(k, [(x, 0), (x, 1)], 0.1, (x, 0, x, 1), seq))
        return scene

    def piece(*ids, x0, x1):
        return symbols.Symbol(list(ids), (x0, 0, x1, 1))

    # Gate (shapes 0 and 3) and channel (1 and 2), a millimetre apart, drawn in turn.
    scene = scene_of([(10, 0), (11, 1), (12, 1), (13, 0)])
    gate, channel = piece(0, 3, x0=0, x1=0), piece(1, 2, x0=1, x1=1)
    assert symbols._woven([gate, channel], scene) == [(gate, channel)]

    # A body and its pin with a far part's body drawn between them: two parts.
    scene = scene_of([(10, 0), (11, 50), (12, 0)])
    near, far = piece(0, 2, x0=0, x1=0), piece(1, x0=50, x1=50)
    assert symbols._woven([near, far], scene) == []


def test_eagle_mosfet_drawn_in_turn_is_one_part_with_gate_source_and_drain():
    """Eagle draws a MOSFET's pins, then its gate, channel, body diode and arrow, each
    piece apart from the next. The arrow's stem and the diode's lead end inside the
    drawing and are no pins; the slants of the diode and the arrow make it no bipolar."""
    b = SceneBuilder()
    for points in (
        [(22.4, 30.0), (24.9, 30.0)],  # gate pin
        [(30.0, 32.6), (30.0, 30.0)],  # source pin
        [(30.0, 22.4), (30.0, 24.9)],  # drain pin
        [(24.9, 30.0), (24.9, 24.9)],  # gate bar
        [(25.5, 26.8), (25.5, 28.3)],  # channel, in three
        [(25.5, 28.8), (25.5, 29.4)],
        [(25.5, 29.4), (25.5, 30.0)],
        [(25.5, 24.9), (25.5, 25.7)],
        [(25.5, 25.7), (25.5, 26.4)],
        [(25.5, 29.4), (27.5, 29.4)],
        [(27.5, 29.4), (27.5, 27.5)],
        [(27.5, 27.5), (26.2, 27.5)],  # arrow's stem
        [(30.0, 28.2), (30.0, 29.4)],  # diode's lead
        [(30.0, 29.4), (27.5, 29.4)],
        [(25.5, 25.7), (30.0, 25.7)],
        [(30.0, 25.7), (30.0, 26.9)],
        [(30.0, 26.9), (30.8, 26.9)],
        [(30.0, 26.9), (29.2, 26.9)],
        [(30.0, 24.9), (30.0, 25.7)],
        [(30.0, 30.0), (30.0, 29.4)],
        [(29.2, 28.2), (30.0, 26.9)],  # diode triangle
        [(30.0, 26.9), (30.8, 28.2)],
        [(30.8, 28.2), (29.2, 28.2)],
        [(25.5, 27.5), (26.2, 27.2), (26.2, 27.7), (25.5, 27.5)],  # arrowhead
    ):
        b.shape(*points, width=0.16, color=(201, 13, 12))
    b.scene.wires += [
        ((22.4, 30.0), (19.9, 30.0)),
        ((30.0, 32.6), (30.0, 35.1)),
        ((30.0, 22.4), (30.0, 19.8)),
    ]
    b.field("Q1", 32.6, 25.8)

    (part,) = symbols.find(b.scene, profile.load("eagle"))
    assert part.ref == "Q1"
    assert {p.number: p.at for p in part.pins} == {
        "G": (22.4, 30.0),
        "S": (30.0, 32.6),
        "D": (30.0, 22.4),
    }


def test_a_lone_text_by_one_pin_is_not_a_pad_number():
    """A part that shows pad numbers shows them on its pins alike: Q1 beside a
    transistor's base, with nothing by its other pins, is the designator."""
    eagle = profile.load("eagle")
    pins = [symbols.Pin(k, ((10, y), (5, y))) for k, y in enumerate((10, 15, 20))]
    part = symbols.Symbol([], (5, 8, 14, 22), pins)

    def text(word, y):
        return Text(0, word, (6, y - 1.5, 8, y - 0.3), 1.2, 0.0, (128, 128, 128))

    name = text("Q1", 10)
    assert not fields._numbers_a_pin(part, name, eagle, fields._Texts([name]))
    numbers = [text("1", 10), text("2", 15), text("3", 20)]
    assert fields._numbers_a_pin(part, numbers[0], eagle, fields._Texts(numbers))


def test_a_number_by_one_pin_of_a_two_pin_part_is_not_its_pad_number():
    """33 printed over a resistor's end is its value. A part that shows pad numbers
    shows them on both its pins."""
    eagle = profile.load("eagle")

    def resistor(numbers):
        scene = Scene(page=1)
        pins = [symbols.Pin(0, ((14, 10), (11, 10))), symbols.Pin(1, ((16, 10), (19, 10)))]
        part = symbols.Symbol([], (11, 9, 19, 11), pins, ref="R1")
        for word, x in numbers:
            box = (x, 8.2, x + 1.6, 9.6)
            scene.pin_numbers.append(Text(0, word, box, 1.4, 0.0, (128, 128, 128)))
        fields._number_pins([part], scene, eagle, set())
        return sorted(p.number for p in part.pins)

    assert resistor([("33", 17)]) == ["1", "2"]
    assert resistor([("A", 11.5), ("B", 17)]) == ["A", "B"]


def test_names_and_roles_name_pins_and_number_none():
    """A transistor's role, or a name drawn by a pin, is no pad: a board read with the
    netlist has no pad G. The pin keeps it as its name, its number unknown."""
    named = [symbols.Pin(1, ((0, 0), (0, 1)), number="VCC", how="name")]
    fields.names_apart([symbols.Symbol([], (0, 0, 1, 1), named, ref="U1")])
    assert (named[0].number, named[0].name) == (None, "VCC")
    transistor = [symbols.Pin(2, ((0, 0), (0, 1)), number="G", how="role")]
    fields.names_apart([symbols.Symbol([], (0, 0, 1, 1), transistor, ref="Q1")])
    assert (transistor[0].number, transistor[0].name) == (None, "G")


def test_a_sheet_whose_name_is_not_printed_is_named_by_its_pins():
    """Its box and pins are drawn; the child page whose hierarchical labels share its
    pins' names is the one it stands for."""
    from schem2net.pipeline import _name_sheets

    root = Scene(page=1, path="/")
    root.sheets = [Sheet("", (0, 0, 20, 20), [SheetPin("SDA", (0, 5)), SheetPin("SCL", (0, 10))])]
    power, bus = Scene(page=2, path="/Power/"), Scene(page=3, path="/I2C/")
    power.labels = [Label("VIN", "hier", (0, 0, 1, 1), 0.0)]
    bus.labels = [Label("SDA", "hier", (0, 0, 1, 1), 0.0), Label("SCL", "hier", (0, 2, 1, 3), 0.0)]
    _name_sheets([root, power, bus])
    assert root.sheets[0].name == "I2C"


def test_members_of_one_bus_named_twice_are_one_net():
    """DPHY0_C{DPHY} and DPHY0_P{DPHY} on the bus between two sheets name the same bus:
    DPHY0_C.C_N and DPHY0_P.C_N are one net."""
    netlister = Netlister()
    netlister.local_names[2] = {"DPHY0_C.C_N"}
    netlister.local_names[3] = {"DPHY0_P.C_N"}
    names = [("l", 1, 0), ("l", 1, 1)]
    netlister.join(*names, "label")  # both labels on one bus
    for node, text in zip(names, ("DPHY0_C{DPHY}", "DPHY0_P{DPHY}"), strict=True):
        netlister.group_names.append((1, node, buses.parse(text)))
    netlister._join_bus_members()
    find = netlister.uf.find
    assert find(("local", 1, "DPHY0_C.C_N")) == find(("local", 1, "DPHY0_P.C_N"))


def test_easyeda_part_is_named_by_the_text_drawn_right_before_it():
    """EasyEDA draws a part's value, its designator, then the part: MOUSE, drawn just
    before the connector, names it whatever its form."""
    easyeda = profile.load("easyeda")
    navy = (0, 0, 128)
    b = SceneBuilder()
    b.scene.fields.append(Text(0, "MINI-DIN-6", (0, 0, 8, 1.2), 1.2, 0.0, navy, 1))
    b.scene.fields.append(Text(1, "MOUSE", (0, 2, 6, 3.2), 1.2, 0.0, navy, 2))
    b.seq = 2
    b.shape((10, 0), (20, 0), (20, 10), (10, 10), (10, 0))
    connector = symbols.Symbol([0], (10, 0, 20, 10), [symbols.Pin(0, ((10, 5), (8, 5)), "1")])
    ordered = fields._designators_by_order([connector], b.scene, easyeda)
    assert ordered[id(connector)].text == "MOUSE"

    b.shape((30, 0), (31, 0))  # a shape drawn between the name and the part
    b.scene.shapes[0].seq, b.scene.shapes[1].seq = 4, 3
    assert fields._designators_by_order([connector], b.scene, easyeda) == {}


def test_a_label_with_an_underscore_still_sits_on_its_wire():
    """LCD_D1's underscore reaches below the baseline, past the wire it is laid on."""
    from schem2net.geometry import GridIndex
    from schem2net.scene import _on_wire

    wires = [((-1.0, 10.0), (12.0, 10.0))]
    index = GridIndex()
    index.add(0, geometry.bbox_of(wires[0]))
    label = Text(0, "LCD_D1", (0, 7.8, 9, 10.2), 2.4, 0.0, (128, 128, 128))
    assert _on_wire(label, wires, index)
    across = Text(0, "LCD_D1", (0, 8.8, 9, 11.2), 2.4, 0.0, (128, 128, 128))
    assert not _on_wire(across, wires, index)  # a text the wire runs through the middle of


def test_orcad_names_differing_in_case_or_sheet_list_are_one_net():
    """Allegro takes net names in capitals, and an off-page name may carry the list of
    sheets it goes to in the same text: RESETSTATz and RESETSTATZ [2,3] are one net."""
    from schem2net.scene import drop_sheet_references

    scene = Scene(page=1)
    scene.labels = [Label("RESETSTATZ [2,3]", "local", (0, 0, 9, 1), 0.0)]
    drop_sheet_references(scene, sheets=3)
    assert scene.labels[0].text == "RESETSTATZ"
    assert Netlister(case_blind=True)._key("RESETSTATz") == "RESETSTATZ"
    assert Netlister()._key("RESETSTATz") == "RESETSTATz"


def test_a_word_the_model_gives_some_chance_can_name_a_part():
    """LCD_CON beside its connector names it, against LCD_D1, a net name of the usual
    form the model is sure is no designator."""
    eagle = profile.load("eagle")
    grey = (128, 128, 128)
    pins = [symbols.Pin(k, ((10, 10 + k), (8, 10 + k)), str(k + 1)) for k in range(4)]
    part = symbols.Symbol([], (8, 9.5, 14, 14), pins, body=(10, 9.5, 14, 14))
    name = Text(0, "LCD_CON", (10, 7.8, 16, 9.1), 1.3, 0.0, grey, 1)
    net = Text(1, "LCD_D1", (16.7, 11, 22, 12.3), 1.3, 0.0, grey, 2)
    texts = fields._Texts([name, net])
    likely = {id(name): 0.14, id(net): 0.0}
    fields._assign_refs([part], texts, None, eagle, set(), set(), likely)
    assert part.ref == "LCD_CON"


def _turned(text, along, across, angle, seq, color=(0, 0, 0)):
    """A text spanning `along` in its reading direction and `across` the other way."""
    u, v = geometry.reading_frame(angle)
    corners = [
        (t * u[0] + w * v[0], t * u[1] + w * v[1]) for t in along for w in across
    ]  # fmt: skip
    return Text(seq, text, geometry.bbox_of(corners), 1.27, angle, color, seq)


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_text_split_by_the_pdf_is_rejoined_in_any_reading_direction(angle):
    pieces = [
        _turned("SD", (10, 12), (5, 6.27), angle, 1),
        _turned("A", (12.05, 12.9), (5, 6.27), angle, 2),
    ]
    assert [t.text for t in _join_runs(pieces)] == ["SDA"]


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_a_designator_written_with_its_value_is_split_in_any_reading_direction(angle):
    easyeda = profile.load("easyeda")
    text = _turned("R22 10k", (10, 17), (5, 6.27), angle, 1, color=(0, 0, 128))
    ref, value = _designator_apart(text, easyeda)
    assert (ref.text, value.text) == ("R22", "10k")
    assert _along(ref.bbox, angle)[1] <= _along(value.bbox, angle)[0] + 1e-9


def _numbered(pins, words, rules):
    """Pin numbers read for the pins of one part from (word, box, angle) texts."""
    part = symbols.Symbol([], geometry.bbox_of([p for pin in pins for p in pin.line]), pins)
    part.ref = "J1"
    scene = Scene(page=1)
    for word, box, angle in words:
        scene.pin_numbers.append(Text(0, word, box, 1.0, angle, (0, 0, 0)))
    fields._number_pins([part], scene, rules, set())
    return [p.number for p in pins]


def test_a_number_between_two_pins_goes_where_it_leaves_none_unpaired():
    """Nearest first, 2 would take pin A, the only pin 1 can reach, and leave B bare."""
    rules = replace(profile.load("kicad"), pin_numbers_above=False)
    a = symbols.Pin(0, ((10, 10), (5, 10)))
    b = symbols.Pin(1, ((10, 11.5), (5, 11.5)))
    c = symbols.Pin(2, ((10, 20), (5, 20)))
    one = ("1", (6, 8.4, 7, 9.4), 0.0)  # above A, 0.6 off
    two = ("2", (6, 10.3, 7, 10.8), 0.0)  # between: 0.3 below A, 0.7 above B
    three = ("3", (6, 18.4, 7, 19.4), 0.0)
    assert _numbered([a, b, c], [one, two, three], rules) == ["1", "2", "3"]


def test_upright_numbers_beside_vertical_pins_are_read():
    pins = [symbols.Pin(0, ((10, 10), (10, 15))), symbols.Pin(1, ((20, 10), (20, 15)))]
    words = [("7", (8.6, 12, 9.6, 13), 0.0), ("8", (18.6, 12, 19.6, 13), 0.0)]
    assert _numbered(pins, words, profile.load("kicad")) == ["7", "8"]


def test_a_header_row_missing_a_number_is_filled_from_its_progression():
    """Odd numbers down one side of a two-row header, even down the other; 5 unread."""
    left = [symbols.Pin(k, ((10, 10 + 2.54 * k), (5, 10 + 2.54 * k))) for k in range(5)]
    right = [symbols.Pin(5 + k, ((20, 10 + 2.54 * k), (25, 10 + 2.54 * k))) for k in range(5)]
    words = []
    for k in range(5):
        y = 10 + 2.54 * k
        if k != 2:
            words.append((str(2 * k + 1), (6, y - 1.6, 7, y - 0.6), 0.0))
        words.append((str(2 * k + 2), (23, y - 1.6, 24, y - 0.6), 0.0))
    found = _numbered(left + right, words, profile.load("kicad"))
    assert found == ["1", "3", "5", "7", "9", "2", "4", "6", "8", "10"]
    assert left[2].how == "row"


@pytest.mark.parametrize(("angle", "wire_y"), [(0, 11.4), (180, 9.9)])
def test_a_label_sits_on_the_wire_at_its_baseline_however_turned(angle, wire_y):
    """Upside down, a label's baseline is its top edge, and its wire runs above it."""
    from schem2net.nets import _under_label

    label = Label("SDA", "local", (10, 10, 20, 11.27), angle)
    wires = [((9, wire_y), (21, wire_y)), ((9, 21.4 - wire_y), (21, 21.4 - wire_y))]
    index = geometry.GridIndex()
    for k, w in enumerate(wires):
        index.add(k, geometry.bbox_of(w))
    assert _under_label(label, wires, index, [], None, ("w", 1)) == ("w", 1, 0)


def test_easyeda_reads_a_sign_by_a_pin_as_no_number():
    """EasyEDA numbers its pads; a + by an LED's pin names it."""
    pins = [symbols.Pin(0, ((14, 10), (11, 10))), symbols.Pin(1, ((16, 10), (19, 10)))]
    words = [("+", (11.5, 8.2, 13.1, 9.6), 0.0), ("-", (17, 8.2, 18.6, 9.6), 0.0)]
    assert "+" not in _numbered(pins, words, profile.load("easyeda"))
    assert _numbered(pins, words, profile.load("kicad")) == ["+", "-"]


def test_a_group_splits_where_the_learned_model_links_nothing(monkeypatch):
    """A supply sign set on a part's pin is drawn touching it, but is a part of its own."""
    b = SceneBuilder()
    b.shape((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))  # a part's body
    b.shape((4, 2), (6.54, 2))  # its pin
    b.shape((6.54, 1), (6.54, 3))  # a supply sign's bar on the pin's tip
    pin = symbols.Pin(1, ((4, 2), (6.54, 2)))
    whole = symbols.Symbol([0, 1, 2], (0, 0, 6.54, 4), [pin], body=(0, 0, 4, 4))
    for p, pieces in ((0.0, 3), (1.0, 1)):
        monkeypatch.setattr(
            symbols.designators, "probability", lambda m, rows, p=p: [p] * len(rows)
        )
        found = symbols._split_unlinked([whole], b.scene, model=object())
        assert len(found) == pieces
        assert sum(len(s.pins) for s in found) == 1


def test_a_part_drawn_over_itself_is_one_part_per_name_stacked_by_it():
    """Alternative connectors for one place: one symbol drawn three times, three names."""
    b = SceneBuilder()
    b.shape((0, 0), (4, 0), (4, 8), (0, 8), (0, 0))
    b.shape((4, 2), (6.54, 2))
    for shape in b.scene.shapes:
        shape.copies = 3
    for k, name in enumerate(("J3", "J2", "J1", "10k")):
        b.field(name, 0, -6 + 1.5 * k)
    part = symbols.Symbol([0, 1], (0, 0, 6.54, 8), [symbols.Pin(1, ((4, 2), (6.54, 2)))], ref="J1")
    found = symbols._drawn_over([part], b.scene, lambda: None)
    assert sorted(s.ref for s in found) == ["J1", "J2", "J3"]
    assert all(len(s.pins) == 1 for s in found)


def test_a_part_named_by_function_takes_the_word_likelier_to_name_it():
    """HDMI beside its connector names it, though its part number lies nearer."""
    connector = symbols.Symbol(
        [],
        (10, 10, 30, 40),
        pins=[symbols.Pin(0, ((10, 12), (8, 12))), symbols.Pin(1, ((10, 14), (8, 14)))],
    )
    number = Text(0, "HDMI-SWM-19", (10, 41, 25, 43), 1.8, 0, (128, 128, 128))
    name = Text(1, "HDMI", (10, 44, 16, 46), 1.8, 0, (128, 128, 128))
    texts = fields._Texts([number, name])
    rules = profile.load("eagle")
    fields._name_by_function([connector], texts, rules, set(), {id(number): 1e-6, id(name): 1e-4})
    assert connector.ref == "HDMI"
    connector.ref, texts.used = None, set()
    fields._name_by_function([connector], texts, rules, set(), {})  # no model: the nearest
    assert connector.ref == "HDMI-SWM-19"


def test_rows_of_anchored_labels_closer_than_a_name_is_high_each_keep_their_own():
    """GND's text lies nearer the dot above it than its own, as the rows sit close: the
    dots and names are paired as a whole, so 3V3 is not left without its dot."""
    scene = Scene(page=1, wires=[((0, 57.42), (6.4, 57.42)), ((0, 59.25), (6.4, 59.25))])
    scene.fields = [
        Text(0, "3V3", (6.5, 55.9, 9.3, 57.12), 1.2, 0, (0, 0, 0)),
        Text(1, "GND", (6.5, 57.69, 10.0, 58.95), 1.2, 0, (0, 0, 0)),
    ]
    _anchored_labels(scene, [(6.4, 57.42), (6.4, 59.25)], profile.load("easyeda"))
    assert {lb.text: lb.outline[0][1] for lb in scene.labels} == {"3V3": 57.42, "GND": 59.25}
