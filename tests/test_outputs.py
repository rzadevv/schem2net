"""Export, queries and the HTML report, on a small made-up design."""

from schem2net import export, kicad, report, symbols
from schem2net.ir import Component, Design, Net, Pin, Source
from schem2net.nets import Netlister
from schem2net.pipeline import Extraction, PageResult
from schem2net.primitives import Page
from schem2net.query import Query

from .test_extract import KICAD, SceneBuilder


def part(ref, value, *pins):
    return Component(ref=ref, value=value, pins=[Pin(num=p) for p in pins])


DESIGN = Design(
    source=Source(file="board.pdf"),
    components=[
        part("R10", "10k", "1", "2"),
        part("R2", "10k", "1", "2"),
        part("C1", "100n", "1", "2"),
        part("U1", "MCU", "1", "2", "3"),
    ],
    nets=[
        Net(id="n1", name="GND", pins=[("C1", "2"), ("U1", "3")], names_seen=["GND"]),
        Net(id="n2", name=None, pins=[("R10", "2"), ("U1", "1")]),
        Net(id="n3", name="LED", pins=[("R10", "1"), ("R2", "1")], names_seen=["LED"]),
        Net(id="n4", name="VIN", pins=[("C1", "1"), ("R2", "2"), ("U1", "2")], confidence=0.5),
    ],
)


def test_kicad_netlist_round_trip(tmp_path):
    path = tmp_path / "board.net"
    path.write_text(export.kicad_netlist(DESIGN))
    back = kicad.read_netlist(path)

    assert [c.ref for c in back.components] == ["R10", "R2", "C1", "U1"]
    assert [n.pins for n in back.nets] == [n.pins for n in DESIGN.nets]
    assert back.nets[1].name == "Net-(R10-Pad2)"


def test_bom_groups_by_value():
    lines = export.bom_csv(DESIGN).splitlines()
    assert lines[0] == "References,Value,Quantity"
    assert "R2 R10,10k,2" in lines


def test_queries():
    q = Query(DESIGN)
    assert q.net("U1.1")["pins"] == ["R10.2", "U1.1"]
    assert q.net("gnd") is None and q.net("GND")["id"] == "n1"
    assert q.pins_of("R10") == [{"pin": "1", "net": "LED"}, {"pin": "2", "net": "n2"}]
    assert [row["net"] for row in q.trace("U1.1")] == ["n2", "LED", "VIN"]
    assert [n["id"] for n in q.low_confidence()] == ["n4"]
    assert q.components_list("R") == [
        {"ref": "R10", "value": "10k", "pins": 2},
        {"ref": "R2", "value": "10k", "pins": 2},
    ]


def test_report_draws_each_net():
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "10k")
    b.resistor(20, 10, "R2", "1k")
    b.scene.wires.append(((10, 7.46), (20, 7.46)))
    found = symbols.find(b.scene, KICAD)
    netlister = Netlister()
    netlister.add_page(b.scene, found)
    result = netlister.result()
    design = Design(source=Source(file="board.pdf"), components=result.components, nets=result.nets)
    page = Page(number=1, width=100, height=50)

    html = report.render(Extraction(design, [PageResult(page, b.scene, found)], result.wire_nets))

    (net,) = design.nets
    assert f'data-net="{net.id}"' in html
    assert "R1.1" in html and "<svg" in html
