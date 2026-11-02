"""Numbering pins from KiCad's symbol libraries."""

from schem2net import export, fields, library
from schem2net.ir import Design, Source
from schem2net.nets import Netlister
from schem2net.primitives import Text
from schem2net.scene import Scene
from schem2net.symbols import Pin, Symbol

CHIP = """(kicad_symbol_lib
  (version 20241209)
  (symbol "CHIP"
    (symbol "CHIP_1_1"
      (pin input line (at -7.62 2.54 0) (length 2.54) (name "IN") (number "1"))
      (pin power_in line (at 0 -7.62 90) (length 2.54) (name "GND") (number "2"))
      (pin passive line (at 0 -7.62 90) (length 2.54) (hide yes) (name "GND") (number "3"))
      (pin output line (at 7.62 2.54 180) (length 2.54) (name "OUT") (number "4"))
    )
    (symbol "CHIP_1_2"
      (pin input line (at -7.62 0 0) (length 2.54) (name "IN") (number "1"))
    )
  )
  (symbol "CHIP2" (extends "CHIP"))
  (symbol "LINK"
    (symbol "LINK_0_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))
    )
  )
)
"""


def _library(tmp_path):
    (tmp_path / "Parts.kicad_sym").write_text(CHIP)
    return library.index(tmp_path)


def _pin(body, tip, number=None):
    return Pin(0, (body, tip), number)


def test_index_reads_units_hidden_pins_and_derived_symbols(tmp_path):
    parts = _library(tmp_path)
    name, pins = parts["chip"][0]
    assert name == "Parts:CHIP"
    # The alternate body style draws pin 1 again; it is left out.
    assert [(p.number, p.unit, p.hidden) for p in pins] == [
        ("1", 1, False),
        ("2", 1, False),
        ("3", 1, True),
        ("4", 1, False),
    ]
    assert [p.number for p in parts["chip2"][0][1]] == ["1", "2", "3", "4"]


def test_stacked_and_named_pins_take_their_numbers(tmp_path):
    """Drawn at (100, 50), y downwards: pin 1's number is shown, the ground pin only
    by its name, the output not at all. Pin 3 lies hidden under pin 2."""
    chip = Symbol([], (90, 40, 110, 60), value="CHIP")
    chip.pins = [
        _pin((95.08, 47.46), (92.38, 47.46), "1"),
        _pin((100, 55.08), (100, 57.62), "GND"),
        _pin((104.92, 47.46), (107.62, 47.46)),
    ]
    gained = library.resolve([chip], _library(tmp_path))

    assert sorted((p.number, p.at) for p in chip.pins) == [
        ("1", (92.38, 47.46)),
        ("2", (100, 57.62)),
        ("3", (100, 57.62)),
        ("4", (107.62, 47.46)),
    ]
    assert gained == 3


def test_a_number_the_library_disagrees_with_leaves_the_part_alone(tmp_path):
    chip = Symbol([], (90, 40, 110, 60), value="CHIP")
    chip.pins = [_pin((95.08, 47.46), (92.38, 47.46), "7"), _pin((100, 55.08), (100, 57.62))]
    assert library.resolve([chip], _library(tmp_path)) == 0
    assert [p.number for p in chip.pins] == ["7", None]


def test_a_part_that_fits_two_ways_is_left_unnumbered(tmp_path):
    """Turned half round, a two-pin part fits as well, with its numbers swapped."""
    link = Symbol([], (0, 0, 10, 10), value="LINK")
    link.pins = [_pin((5, 3.73), (5, 2.46)), _pin((5, 6.27), (5, 7.54))]
    assert library.resolve([link], _library(tmp_path)) == 0
    assert [p.number for p in link.pins] == [None, None]


def test_a_renumbered_pin_keeps_its_number_when_the_rest_fit(tmp_path):
    """The designer's copy calls the input 9; the drawing still fits the library."""
    lines = [
        f'(pin passive line (at {x} 0 270) (length 2.54) (name "P{n}") (number "{n}"))'
        for n, x in enumerate(range(0, 30, 3), start=1)
    ]
    lines.append(
        '(pin passive line (at 0 0 270) (length 2.54) (hide yes) (name "P1") (number "11"))'
    )
    text = '(kicad_symbol_lib (symbol "ROW" (symbol "ROW_1_1" ' + " ".join(lines) + ")))"
    (tmp_path / "Rows.kicad_sym").write_text(text)
    row = Symbol([], (0, 0, 40, 10), value="ROW")
    row.pins = [_pin((x + 10, 2.54), (x + 10, 0), str(n)) for n, x in enumerate(range(0, 30, 3), 1)]
    row.pins[4].number = "9"  # where the library has 5

    library.resolve([row], library.index(tmp_path))
    assert sorted(p.number for p in row.pins) == sorted(
        ["1", "11", "2", "3", "4", "9", "6", "7", "8", "9", "10"]
    )


def test_a_redrawn_symbol_still_adds_the_pins_stacked_under_its_numbers(tmp_path):
    """Moved since the design, the symbol no longer fits; its numbers still match."""
    chip = Symbol([], (0, 0, 40, 40), value="CHIP")
    chip.pins = [
        _pin((5, 5), (2, 5), "1"),
        _pin((20, 30), (20, 33), "2"),
        _pin((35, 5), (38, 5), "4"),
    ]
    library.resolve([chip], _library(tmp_path))
    assert sorted(p.number for p in chip.pins) == ["1", "2", "3", "4"]


def test_a_part_whose_value_was_misread_is_found_by_the_name_printed_beside_it(tmp_path):
    chip = Symbol([], (90, 40, 110, 60), value="4")  # a pad number taken for the value
    chip.pins = [
        _pin((95.08, 47.46), (92.38, 47.46), "1"),
        _pin((100, 55.08), (100, 57.62), "GND"),
        _pin((104.92, 47.46), (107.62, 47.46)),
    ]
    printed = [Text(0, "CHIP", (100, 36, 106, 38), 1.27, 0.0, None)]
    library.resolve([chip], _library(tmp_path), texts=printed)
    assert sorted(p.number for p in chip.pins) == ["1", "2", "3", "4"]


LBR = """<?xml version="1.0" encoding="utf-8"?>
<eagle version="9.6.2"><drawing><library>
<symbols>
  <symbol name="AMP">
    <pin name="IN" x="-7.62" y="0" length="short"/>
    <pin name="OUT" x="7.62" y="0" length="short" rot="R180"/>
  </symbol>
  <symbol name="SUPPLY">
    <pin name="V+" x="0" y="5.08" length="short" rot="R270"/>
    <pin name="GND@1" x="0" y="-5.08" length="short" rot="R90"/>
  </symbol>
</symbols>
<devicesets>
  <deviceset name="DUAL_AMP" prefix="U">
    <gates>
      <gate name="A" symbol="AMP" x="0" y="0"/>
      <gate name="B" symbol="AMP" x="0" y="10"/>
      <gate name="P" symbol="SUPPLY" x="0" y="20" addlevel="request"/>
    </gates>
    <devices>
      <device name="-SOIC" package="SO8">
        <connects>
          <connect gate="A" pin="IN" pad="3"/><connect gate="A" pin="OUT" pad="1"/>
          <connect gate="B" pin="IN" pad="5"/><connect gate="B" pin="OUT" pad="7"/>
          <connect gate="P" pin="V+" pad="8"/><connect gate="P" pin="GND@1" pad="4 9"/>
        </connects>
        <technologies><technology name="">
          <attribute name="VALUE" value="LM358"/>
        </technology></technologies>
      </device>
    </devices>
  </deviceset>
</devicesets>
</library></drawing></eagle>
"""


def test_eagle_devices_are_indexed_by_the_values_eagle_prints(tmp_path):
    (tmp_path / "Amps.lbr").write_text(LBR)
    parts = library.index_eagle(tmp_path)
    assert set(parts) == {"dual_amp", "dual_amp-soic", "lm358"}
    name, pins = parts["lm358"][0]
    assert name == "Amps:DUAL_AMP-SOIC"
    # A lettered gate is the unit of its letter, as a designator such as U1B names it;
    # a pin with two pads keeps the first.
    assert [(p.number, p.name, p.unit) for p in pins] == [
        ("3", "IN", 1),
        ("1", "OUT", 1),
        ("5", "IN", 2),
        ("7", "OUT", 2),
        ("8", "V+", 16),
        ("4", "GND", 16),
    ]


def test_numbered_units_disambiguate_identical_library_gates(tmp_path):
    (tmp_path / "Amps.lbr").write_text(LBR)
    for unit in ("B", ".2", "G2", "G$2", "-2"):
        amp = Symbol([], (-8, -1, 8, 1), value="LM358", unit=unit)
        amp.pins = [_pin((-5.08, 0), (-7.62, 0), "IN"), _pin((5.08, 0), (7.62, 0))]
        library.resolve([amp], library.index_eagle(tmp_path))
        assert [p.number for p in amp.pins] == ["5", "7"], unit


def test_a_missing_library_unit_cannot_borrow_another_units_pins(tmp_path):
    for numbers in (("1", None, None), ("1", "2", "4")):
        chip = Symbol([], (90, 40, 110, 60), value="CHIP", unit="B")
        chip.pins = [
            _pin((95.08, 47.46), (92.38, 47.46), numbers[0]),
            _pin((100, 55.08), (100, 57.62), numbers[1]),
            _pin((104.92, 47.46), (107.62, 47.46), numbers[2]),
        ]
        assert library.resolve([chip], _library(tmp_path)) == 0
        assert [p.number for p in chip.pins] == list(numbers)


def test_no_index_is_read_unless_its_folder_is_given(tmp_path):
    pins = [library.LibPin("1", "A", 0, (0.0, 0.0), False)]
    library.save({"r": [("Device:R", pins)]}, library.path(tmp_path, "kicad"))
    assert library.load(tmp_path, "kicad") == {"r": [("Device:R", pins)]}
    assert library.load(None, "kicad") == {} and library.fingerprint(None, "kicad") is None
    assert library.fingerprint(tmp_path, "kicad").startswith("kicad-symbols.json.gz ")


def test_library_pin_names_never_become_board_pad_numbers(tmp_path):
    chip = Symbol([], (90, 40, 110, 60), ref="U1", value="CHIP")
    chip.pins = [
        _pin((95.08, 47.46), (92.38, 47.46), "1"),
        _pin((100, 55.08), (100, 57.62)),
        _pin((104.92, 47.46), (107.62, 47.46)),
    ]
    library.resolve([chip], _library(tmp_path), by_name=True)
    fields.names_apart([chip])
    assert [(p.number, p.name) for p in chip.pins] == [
        ("1", None),
        (None, "GND"),
        (None, "OUT"),
    ]
    for i, pin in enumerate(chip.pins):
        pin.shape = i
    netlister = Netlister()
    netlister.add_page(Scene(page=1, wires=[((100, 57.62), (107.62, 47.46))]), [chip])
    found = netlister.result()
    design = Design(source=Source(file="x"), components=found.components, nets=found.nets)
    assert all(p[1].startswith("?") for net in design.nets for p in net.pins)
    assert '(pin "GND")' not in export.kicad_netlist(design)
    assert '(pin "OUT")' not in export.kicad_netlist(design)
