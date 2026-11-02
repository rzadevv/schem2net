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


def test_bench_compare_fails_when_pins_are_lost(tmp_path):
    import json
    from dataclasses import asdict

    from typer.testing import CliRunner

    from schem2net import cli
    from schem2net.bench.score import Counts

    def run(name, correct):
        designs = {
            f"d{i}": asdict(Counts(designs=1, pins=100, pins_correct=correct + i)) for i in range(8)
        }
        (tmp_path / name).write_text(json.dumps({"designs": designs}))
        return str(tmp_path / name)

    before, same, worse = run("a.json", 90), run("b.json", 90), run("c.json", 80)
    assert CliRunner().invoke(cli.app, ["bench-compare", before, same]).exit_code == 0
    failed = CliRunner().invoke(cli.app, ["bench-compare", before, worse])
    assert failed.exit_code == 1 and "pin accuracy is lower" in failed.output


def test_bench_compare_refuses_to_drop_a_design(tmp_path):
    import json
    from dataclasses import asdict

    from typer.testing import CliRunner

    from schem2net import cli
    from schem2net.bench.score import Counts

    good = asdict(Counts(designs=1, pins=100, pins_correct=100))
    bad = asdict(Counts(designs=1, pins=100, pins_correct=0))
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(json.dumps({"designs": {"good": good, "bad": bad}}))
    after.write_text(json.dumps({"designs": {"good": good}}))
    result = CliRunner().invoke(cli.app, ["bench-compare", str(before), str(after)])
    assert result.exit_code == 1
    assert "bad" in result.output and "different designs" in result.output


def test_a_pin_with_no_number_stays_on_its_net_under_a_mark():
    """The drawing shows what the pin connects to, though not which pad it is."""
    led = symbols.Symbol([], (0, 0, 4, 4), [symbols.Pin(0, ((2, 2), (2, 0)))], ref="D1")
    r = symbols.Symbol([], (0, -6, 4, -2), [symbols.Pin(1, ((2, -2), (2, 0)), "1")], ref="R1")
    netlister = Netlister()
    netlister.add_page(SceneBuilder().scene, [led, r])
    found = netlister.result()
    (net,) = found.nets
    assert net.pins == [("D1", "?1"), ("R1", "1")]
    (issue,) = [i for i in found.issues if i.kind == "unnumbered_pin"]
    assert issue.pins == [("D1", "?1")]

    design = Design(source=Source(file="x.pdf"), components=found.components, nets=found.nets)
    assert "?1" not in export.kicad_netlist(design) + export.spice_netlist(design)

    from schem2net.bench.score import score

    truth = Design(
        source=Source(file="x.pdf"),
        components=[part("D1", "~", "1"), part("R1", "~", "1")],
        nets=[Net(id="n1", pins=[("D1", "1"), ("R1", "1")])],
    )
    counts = score(design, truth)
    assert (counts.pins_correct, counts.pins_missed) == (1, 1)


def test_a_reading_that_leaves_designators_without_parts_loses_the_guess(monkeypatch):
    """Read as the wrong generator, a page may join as many pins, but leaves many
    designators naming parts it did not find."""
    from schem2net import pipeline, roles
    from schem2net.primitives import Document

    def reading(joined, lost):
        parts = [part(f"R{k}", "~", "1", "2") for k in range(joined // 2)]
        nets = [Net(id=f"n{k}", pins=[(f"R{k}", "1"), (f"R{k}", "2")]) for k in range(joined // 2)]
        issues = [Issue(kind="designator_without_part")] * lost
        return Design(source=Source(file="x"), components=parts, nets=nets, issues=issues)

    readings = {"eagle": reading(40, 20), "orcad": reading(38, 0)}

    def extract(doc, design, generator, printed, *rest):
        design = readings.get(generator, reading(0, 0))
        design.source.generator = generator
        return Extraction(design, [])

    monkeypatch.setattr(pipeline, "_extract", extract)
    monkeypatch.setattr(roles, "learned", lambda g: True)
    doc = Document(pages=[Page(1, 10, 10)], metadata={})
    found = pipeline._read_as_any(doc, Design(source=Source(file="x")), None)
    assert found.design.source.generator == "orcad"


def test_a_page_with_no_line_in_the_wire_colour_is_known_by_it():
    """Wires drawn blue in a theme of the designer's own leave no line in the wire
    colour: such a page is read by shape too, and the better reading kept."""
    from schem2net import pipeline, profile
    from schem2net.primitives import Path as Line

    easyeda = profile.load("easyeda")
    page = Page(1, 100, 100)
    page.paths = [Line(0, [[(0, 0), (10, 0)]], 0.2, (0, 0, 255), None)]
    assert not pipeline._in_colour(page, easyeda, "wire")
    page.paths.append(Line(1, [[(0, 5), (10, 5)]], 0.2, (0, 135, 0), None))
    assert pipeline._in_colour(page, easyeda, "wire")


def _joined(design):
    return sorted(sorted({ref for ref, _ in net.pins}) for net in design.nets)


def test_a_pdf_in_black_that_names_no_maker_is_read_as_the_best_guess(tmp_path):
    from schem2net import pipeline

    from .conftest import KICAD_INK, resistor_page

    black = dict.fromkeys(KICAD_INK, (0, 0, 0))
    design = pipeline.extract(resistor_page(black).save(tmp_path / "black.pdf"))
    assert any(i.kind == "generator_guessed" for i in design.issues)
    assert _joined(design) == [["R1", "R2"], ["R1", "R2", "R3"]]


def test_a_kicad_page_with_wires_in_a_colour_of_its_own_is_read_by_shape(tmp_path, monkeypatch):
    from schem2net import pdf, pipeline, roles

    from .conftest import KICAD_INK, resistor_page

    file = resistor_page({**KICAD_INK, "wire": (0, 0, 255)}).save(tmp_path / "blue.pdf")

    def read():
        doc = pdf.read(file)
        found = pipeline._extract(doc, Design(source=Source(file="x")), "kicad", False, None)
        return _joined(found.design)

    assert read() == [["R1", "R2"], ["R1", "R2", "R3"]]
    monkeypatch.setattr(roles, "learned", lambda generator: False)
    assert read() == []  # read in its colours alone, the blue lines are no wires


def test_a_transistor_known_by_roles_alone_gives_a_board_no_pads():
    from schem2net import fields
    from schem2net.scene import Scene

    pins = [
        symbols.Pin(k, ((0, k), (1, k)), number=role, how="role") for k, role in enumerate("GSD")
    ]
    transistor = symbols.Symbol([], (0, 0, 1, 3), pins, ref="Q1")
    fields.names_apart([transistor])
    netlister = Netlister()
    netlister.add_page(Scene(page=1), [transistor])
    found = netlister.result()
    design = Design(source=Source(file="x.pdf"), components=found.components, nets=found.nets)
    assert '"Q1"' not in export.kicad_netlist(design).split("(nets", 1)[1]
    assert {p.name for p in design.components[0].pins} == {"G", "S", "D"}


def test_exit_codes_tell_what_was_read(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from schem2net import cli, pipeline

    pdf = tmp_path / "board.pdf"
    pdf.write_bytes(b"%PDF")

    def code(design, *flags):
        monkeypatch.setattr(pipeline, "extract", lambda *a, **k: design)
        return CliRunner().invoke(cli.app, ["extract", str(pdf), *flags]).exit_code

    source = Source(file=str(pdf))
    failed = DESIGN.model_copy(update={"issues": [Issue(kind="page_failed", page=2)]})
    assert code(DESIGN) == 0
    assert code(Design(source=source, issues=[Issue(kind="no_profile")])) == 2
    assert code(Design(source=source, issues=[Issue(kind="board_page", page=1)])) == 3
    assert code(failed) == 0 and code(failed, "--strict") == 3
