"""Stages 5-8 on small hand-built scenes that follow KiCad's drawing conventions."""

from schem2net import buses, geometry, profile, symbols
from schem2net.nets import Netlister
from schem2net.primitives import Text
from schem2net.scene import Label, Scene, Shape, Sheet, SheetPin, _join_runs

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
    netlister = Netlister()
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
    assert nets["GND"].pins == [("R1", "2")]
    assert nets["SENSE"].pins == [("R1", "1")]
