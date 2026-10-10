"""Export, queries and the HTML report, on a small made-up design."""

import pytest
import typer

from schem2net import bookmarks, diff, export, kicad, kicad_sch, report, sexpr, symbols
from schem2net.ir import Component, Design, Issue, Net, Pin, Source
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
    design = DESIGN.model_copy(deep=True)
    design.issues = [Issue(kind="dangling_wire", page=1), Issue(kind="power_nets_merged")]
    assert [i["kind"] for i in Query(design).issues("power_nets_merged")] == ["power_nets_merged"]
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


def test_netlist_from_altium_bookmarks():
    outline = [
        (0, "Schematic Prints"),
        (1, "Board.SchDoc"),
        (2, "Components"),
        (3, "C1"),
        (3, "J-1"),
        (2, "Nets"),
        (3, "GND"),
        (4, "Pins"),
        (5, "C1-2"),
        (5, "J-1-3"),
        (4, "NetLabels"),
        (3, "NetC1_1"),
        (4, "Pins"),
        (5, "C1-1"),
        (5, "J-1-1"),
    ]
    design = bookmarks.from_outline(outline, Source(file="board.pdf"))
    assert {n.name: n.pins for n in design.nets} == {
        "GND": [("C1", "2"), ("J-1", "3")],
        "NetC1_1": [("C1", "1"), ("J-1", "1")],
    }
    assert bookmarks.from_outline([(0, "Page 1")], Source(file="x.pdf")) is None


def test_kicad_schematic_places_parts_where_they_were_drawn(tmp_path):
    b = SceneBuilder()
    b.resistor(10, 10, "R1", "10k")
    b.resistor(20, 10, "R2", "1k")
    b.ground(10, 17.54)
    b.scene.wires.append(((10, 7.46), (20, 7.46)))
    found = symbols.find(b.scene, KICAD)
    netlister = Netlister()
    netlister.add_page(b.scene, found)
    result = netlister.result()
    design = Design(source=Source(file="board.pdf"), components=result.components, nets=result.nets)
    page = Page(number=1, width=100, height=50)
    extraction = Extraction(design, [PageResult(page, b.scene, found)], result.wire_nets)

    root = kicad_sch.write(extraction, tmp_path, "board")

    sheet = sexpr.parse((tmp_path / "board-page1.kicad_sch").read_text())
    placed = {sexpr.value(p, "lib_id"): p for p in sexpr.children(sheet, "symbol")}
    assert set(placed) == {"schem2net:R1", "schem2net:R2"}
    # Pins keep their drawn positions: the symbol origin plus the pin's offset, y flipped.
    lib = {s[1]: s for s in sexpr.children(sexpr.child(sheet, "lib_symbols"), "symbol")}
    unit = sexpr.children(lib["schem2net:R1"], "symbol")[0]
    _, x, y = sexpr.child(placed["schem2net:R1"], "at")[:3]
    tips = sorted(
        (round(float(x) + float(at[1]), 2), round(float(y) - float(at[2]), 2))
        for at in (sexpr.child(pin, "at") for pin in sexpr.children(unit, "pin"))
    )
    assert tips == [(10, 7.46), (10, 17.54)]
    # GND reaches R1 through a label on its pin, since no wire ends there.
    assert [lb[1] for lb in sexpr.children(sheet, "global_label")] == ["GND"]
    assert len(sexpr.children(sheet, "wire")) == 1
    assert root.name == "board.kicad_sch"
    assert (tmp_path / "board.kicad_sym").exists() and (tmp_path / "sym-lib-table").exists()


def test_spice_netlist():
    text = export.spice_netlist(DESIGN)
    lines = text.splitlines()
    assert "RR10 LED N2 10k" in lines
    assert "CC1 VIN 0 100n" in lines  # GND is node 0
    assert "XU1 N2 VIN 0 MCU" in lines
    assert lines[-1] == ".end"


def test_spice_values():
    values = ["10k", "4.7uF", "1MΩ", "4R7", "2k2", "0R", "22pF", "100pF 50V"]
    assert [export._spice_value(v) for v in values] == [
        "10k",
        "4.7u",
        "1Meg",
        "4.7",
        "2.2k",
        "0",
        "22p",
        "100p",
    ]


def test_diff_reports_changed_parts_and_moved_pins():
    new = DESIGN.model_copy(deep=True)
    new.components = [c for c in new.components if c.ref != "R2"] + [part("R3", "1k", "1", "2")]
    new.components[0].value = "4k7"  # R10
    gnd, unnamed, led, vin = new.nets
    gnd.name = "AGND"  # renamed only
    unnamed.pins = [("R10", "2")]
    vin.pins = [*vin.pins, ("U1", "1")]

    change = diff.diff(DESIGN, new)

    assert change.added == ["R3"] and change.removed == ["R2"]
    assert change.revalued == [("R10", "10k", "4k7")]
    moved = {net.name: (net.joined, net.left) for net in change.nets}
    assert moved["VIN"] == ([("U1", "1")], [])
    assert "AGND" not in moved
    assert diff.diff(DESIGN, DESIGN).empty


def test_a_pdf_no_profile_reads_fails_loudly(capsys):
    """A PDF from a tool schem2net does not read gives nothing: say so, and fail."""
    from schem2net import cli

    design = Design(
        source=Source(file="pi.pdf"),
        issues=[Issue(kind="no_profile", severity="error", detail="Microsoft: Print To PDF")],
    )
    with pytest.raises(typer.Exit) as stop:
        cli._refuse(design)
    assert stop.value.exit_code == 2
    assert "Microsoft: Print To PDF" in capsys.readouterr().err


def test_the_report_lists_what_to_check_with_its_pins():
    issue = Issue(kind="pin_number_guessed", detail="D1", pins=[("D1", "1"), ("D1", "2")])
    design = Design(source=Source(file="x.pdf"), issues=[issue])
    html = report.render(Extraction(design, []))
    assert "To check (1)" in html and "pin numbers not shown, guessed" in html and "D1" in html


def test_a_run_that_reads_nothing_leaves_an_earlier_output_as_it_was(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from schem2net import cli, pipeline

    pdf = tmp_path / "board.rev2.pdf"
    pdf.write_bytes(b"%PDF")
    earlier = tmp_path / "board.rev2.ir.json"
    earlier.write_text("earlier")
    nothing = Design(source=Source(file=str(pdf)), issues=[Issue(kind="no_profile")])
    monkeypatch.setattr(pipeline, "extract", lambda *a, **k: nothing)
    result = CliRunner().invoke(cli.app, ["extract", str(pdf)])
    assert result.exit_code == 2 and earlier.read_text() == "earlier"

    monkeypatch.setattr(pipeline, "extract", lambda *a, **k: DESIGN)
    result = CliRunner().invoke(cli.app, ["export", str(pdf), "--to", "bom"])
    assert result.exit_code == 0 and (tmp_path / "board.rev2.bom.csv").exists()


def test_input_that_cannot_be_read_is_told_plainly(tmp_path):
    from schem2net import pdf, pipeline

    not_pdf = tmp_path / "notes.pdf"
    not_pdf.write_text("hello")
    with pytest.raises(pdf.InputError):
        pdf.read(not_pdf)
    for bad in ("garbage", "0:0,0,10,10", "1:0,0,10"):
        with pytest.raises(ValueError):
            pipeline.Region.parse(bad)


def test_nets_of_one_name_are_written_apart():
    design = Design(
        source=Source(file="x.pdf"),
        components=[
            part("R1", "10k", "1", "2"),
            part("R2", "1k", "1", "2"),
            part("R3", "1k", "1", "2"),
        ],
        nets=[
            Net(id="n1", name="+3V3", pins=[("R1", "1")]),
            Net(id="n2", name="3V3", pins=[("R1", "2")]),
            Net(id="n3", name="AGND", pins=[("R2", "1")]),
            Net(id="n4", name="GND", pins=[("R2", "2")]),
            Net(id="n5", name="LED", pins=[("R3", "1")]),
            Net(id="n6", name="LED", pins=[("R3", "2")]),
        ],
    )
    tree = sexpr.parse(export.kicad_netlist(design))
    names = [n[2][1] for n in tree[4][1:]]
    assert len(names) == len(set(names)) and "LED_2" in names

    spice = export.spice_netlist(design)
    assert "RR1 3V3 3V3_2 10k" in spice
    assert "RR2 AGND 0 1k" in spice


def test_bom_values_are_not_taken_for_formulas():
    design = Design(
        source=Source(file="x.pdf"),
        components=[part("R1", '=HYPERLINK("http://x")'), part("R2", "-12V"), part("R3", "+cmd")],
    )
    bom = export.bom_csv(design)
    assert "'=HYPERLINK" in bom and ",-12V," in bom and "'+cmd" in bom


def test_trace_passes_a_part_whose_pins_share_a_number():
    design = Design(
        source=Source(file="x.pdf"),
        components=[part("R3", "10k", "1", "1")],
        nets=[Net(id="n1", name="A", pins=[("R3", "1")])],
    )
    assert Query(design).trace("R3.1")


def test_a_page_the_reader_trips_on_is_reported_and_the_rest_read(monkeypatch):
    from schem2net import pipeline
    from schem2net.primitives import Document

    read = pipeline._read_page

    def trip(result, *args):
        if result.page.number == 1:
            raise ValueError("odd page")
        return read(result, *args)

    monkeypatch.setattr(pipeline, "_read_page", trip)
    doc = Document(pages=[Page(1, 100, 100), Page(2, 100, 100)], metadata={})
    found = pipeline._extract(doc, Design(source=Source(file="x.pdf")), "kicad", False, None)
    failed = [i for i in found.design.issues if i.kind == "page_failed"]
    assert [(i.page, i.detail) for i in failed] == [(1, "ValueError: odd page")]


def test_a_bench_worse_than_its_baseline_is_told():
    from schem2net.cli import _worse

    before = {"pin_accuracy": 0.90, "connection_f1": 0.90, "silent_error_rate": 0.010}
    same = {"pin_accuracy": 0.899, "connection_f1": 0.91, "silent_error_rate": 0.0105}
    assert _worse(before, same) == []
    worse = {"pin_accuracy": 0.89, "connection_f1": 0.90, "silent_error_rate": 0.02}
    assert [line.split()[0] for line in _worse(before, worse)] == [
        "pin_accuracy",
        "silent_error_rate",
    ]
