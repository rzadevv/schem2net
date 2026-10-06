"""Numbering pins from KiCad's symbol libraries."""

from schem2net import library
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
