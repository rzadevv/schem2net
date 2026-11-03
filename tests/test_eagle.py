"""Eagle schematics as ground truth, and text drawn with a stroke font."""

import json
from dataclasses import replace
from importlib import resources

from schem2net import eagle, strokes
from schem2net.primitives import Page, Path, Text

SCHEMATIC = """<?xml version="1.0" encoding="utf-8"?>
<eagle version="9.6.2"><drawing><schematic>
<libraries><library name="parts">
  <devicesets>
    <deviceset name="RESISTOR"><gates><gate name="G$1" symbol="R"/></gates>
      <devices><device name="0603" package="0603">
        <connects>
          <connect gate="G$1" pin="1" pad="1"/><connect gate="G$1" pin="2" pad="2"/>
        </connects>
      </device></devices></deviceset>
    <deviceset name="REGULATOR"><gates><gate name="G$1" symbol="LDO"/></gates>
      <devices><device name="SOT23" package="SOT23">
        <connects><connect gate="G$1" pin="IN" pad="1"/><connect gate="G$1" pin="GND@1" pad="2 4"/>
          <connect gate="G$1" pin="OUT" pad="3"/></connects>
      </device></devices></deviceset>
    <deviceset name="FRAME"><gates><gate name="G$1" symbol="FRAME"/></gates>
      <devices><device name=""/></devices></deviceset>
  </devicesets>
</library></libraries>
<parts>
  <part name="R1" library="parts" deviceset="RESISTOR" device="0603" value="10k"/>
  <part name="U1" library="parts" deviceset="REGULATOR" device="SOT23" value="AP2112"/>
  <part name="FRAME1" library="parts" deviceset="FRAME" device=""/>
</parts>
<sheets><sheet><nets>
  <net name="VOUT"><segment>
    <pinref part="U1" gate="G$1" pin="OUT"/><pinref part="R1" gate="G$1" pin="1"/>
  </segment></net>
  <net name="GND"><segment>
    <pinref part="U1" gate="G$1" pin="GND@1"/><pinref part="R1" gate="G$1" pin="2"/>
  </segment></net>
</nets></sheet></sheets>
</schematic></drawing></eagle>
"""


def test_eagle_netlist_uses_pads(tmp_path):
    path = tmp_path / "board.sch"
    path.write_text(SCHEMATIC)
    design = eagle.read(path)

    assert [c.ref for c in design.components] == ["R1", "U1"]  # the frame has no pads
    nets = {n.name: n.pins for n in design.nets}
    assert nets["VOUT"] == [("R1", "1"), ("U1", "3")]
    # A pin on two pads is drawn as its first pad, "2*2".
    assert nets["GND"] == [("R1", "2"), ("U1", "2")]
    u1 = next(c for c in design.components if c.ref == "U1")
    assert {p.num: p.name for p in u1.pins} == {"1": "IN", "2": "GND", "3": "OUT"}


def _drawn(
    text: str, x: float, y: float, height: float, seq: int, joined: bool = False, shape: int = 0
) -> list[Path]:
    """Draw a word with the font's own glyph shapes, the way a PDF would: a path per
    line, or with `joined`, a polyline wherever lines meet end to end."""
    table = json.loads(
        resources.files("schem2net").joinpath("profiles", "eagle_font.json").read_text()
    )
    shapes = {e["char"]: e["shapes"][min(shape, len(e["shapes"]) - 1)] for e in table}
    paths = []
    for i, char in enumerate(text):
        left = x + i * 0.9 * height
        for (a, b), (c, d) in shapes[char]:
            start, end = (left + a * height, y - b * height), (left + c * height, y - d * height)
            last = paths[-1].subpaths[0] if paths else None
            if joined and last and last[-1] == start and paths[-1].seq == seq - 1:
                last.append(end)
                continue
            paths.append(Path(seq, [[start, end]], 0.15, (80, 80, 80), None, seq=seq))
            seq += 1
    return paths


def test_stroke_text_is_read():
    paths = _drawn("R12", 10, 20, 1.8, 0) + _drawn("10k", 10, 30, 1.8, 100)
    texts, used = strokes.read(paths, "eagle")
    assert sorted(t.text for t in texts) == ["10k", "R12"]
    assert len(used) == len(paths)


def test_pin_numbers_set_one_under_another_are_read_upright():
    """Numbers down a connector are drawn in turn, from the bottom up. Together they
    are taller than wide, as a text turned on its side is; so is a digit alone."""
    paths, seq = [], 0
    for k, number in enumerate(("1", "2", "3", "4", "10", "11")):
        drawn = _drawn(number, 10, 60 - 2.54 * k, 1.4, seq)
        paths += drawn
        seq += len(drawn)
    texts, _ = strokes.read(paths, "eagle")
    assert sorted(t.text for t in texts) == ["1", "10", "11", "2", "3", "4"]
    assert all(round(t.angle) == 0 for t in texts)

    (alone,) = strokes.read(_drawn("6", 10, 20, 1.4, 0), "eagle")[0]
    assert alone.text == "6" and round(alone.angle) == 0


def test_a_letter_of_short_strokes_stays_in_its_word():
    """An S is many short strokes, so the jump from its foot to the top of the C after
    it is far against them; it still lands on the S's line, right after it."""
    s_then_c = [
        ((69.3, 87.0), (69.1, 86.8)),
        ((69.1, 86.8), (68.7, 86.8)),
        ((68.7, 86.8), (68.5, 87.0)),
        ((68.5, 87.0), (68.5, 87.2)),
        ((68.5, 87.2), (68.7, 87.3)),
        ((68.7, 87.3), (69.1, 87.3)),
        ((69.1, 87.3), (69.3, 87.5)),
        ((69.3, 87.5), (69.3, 87.7)),
        ((69.3, 87.7), (69.1, 87.9)),
        ((69.1, 87.9), (68.7, 87.9)),
        ((68.7, 87.9), (68.5, 87.7)),
        ((70.5, 87.0), (70.3, 86.8)),  # the C starts at its top right
        ((70.3, 86.8), (69.9, 86.8)),
        ((69.9, 86.8), (69.7, 87.0)),
        ((69.7, 87.0), (69.7, 87.7)),
        ((69.7, 87.7), (69.9, 87.9)),
        ((69.9, 87.9), (70.3, 87.9)),
    ]
    paths = [
        Path(k, [list(line)], 0.12, (80, 80, 80), None, seq=k) for k, line in enumerate(s_then_c)
    ]
    assert len(strokes._runs(paths)) == 1

    # A text turned on its side is not carried on by one set beside it, level with it.
    def turned(word, x):
        return [
            replace(p, subpaths=[[(x + y, 40.0 - px) for px, y in p.subpaths[0]]])
            for p in _drawn(word, 0, 0, 1.4, 0)
        ]

    assert not strokes._next_letter(turned("R10", 50.0), turned("R11", 52.54))


def test_stroke_text_drawn_as_polylines_is_read():
    # Eagle 9 draws a curve as one polyline of many short pieces.
    paths = _drawn("DOG", 10, 20, 1.8, 0, joined=True, shape=1)
    assert any(len(p.subpaths[0]) > 2 for p in paths)
    texts, _ = strokes.read(paths, "eagle")
    assert [t.text for t in texts] == ["DOG"]


def test_stroke_text_with_a_fill_is_read():
    # Older Qt exports give every line a fill as well; a line has no inside to fill.
    paths = [replace(p, fill=p.stroke) for p in _drawn("C7", 10, 20, 1.8, 0)]
    texts, _ = strokes.read(paths, "eagle")
    assert [t.text for t in texts] == ["C7"]


def test_text_traced_with_an_invisible_copy_is_read_from_the_copy():
    """KiCad 7 draws letters as strokes and lays an invisible copy over them."""
    teal, black = (0, 100, 100), (0, 0, 0)
    letters = [
        Path(k, [[(10 + k * 0.5, 20), (10 + k * 0.5, 21.3)]], 0.15, teal, None, seq=k)
        for k in range(4)
    ]
    pin = Path(9, [[(30, 20), (35, 20)]], 0.15, black, None, seq=9)
    copy = Text(10, "R12", (9.9, 19.9, 11.6, 21.2), 1.3, 0.0, teal, 10, visible=False)
    marker = Text(11, "1", (31, 19.8, 31.6, 20.4), 0.6, 0.0, teal, 11, visible=False)
    page = strokes.traced(Page(1, 50, 50, paths=[*letters, pin], texts=[copy, marker]))
    assert [t.text for t in page.texts if t.visible] == ["R12"]  # the marker has no ink of its own
    assert page.paths == [pin]


def _curved_eight(pieces):
    """The same two loops tessellated with a different number of PDF chords."""
    import math

    points = [
        (0.25 * math.sin(2 * t), 0.5 + 0.5 * math.cos(t))
        for t in (2 * math.pi * k / pieces for k in range(pieces + 1))
    ]
    return list(zip(points, points[1:], strict=False))


def test_glyph_candidates_survive_different_curve_decompositions():
    query = _curved_eight(22)
    assert strokes.match(query, [("8", _curved_eight(32))]) == "8"


def test_ambiguous_excluded_glyphs_do_not_supply_a_character():
    template = _curved_eight(32)
    assert strokes.match(_curved_eight(22), [("8", template), ("B", template)]) is None


def test_new_candidates_do_not_replace_an_existing_strong_reading():
    query = _curved_eight(22)
    assert strokes.match(query, [("B", query), ("8", _curved_eight(32))]) == "B"


def test_a_fragmented_match_still_requires_the_same_geometric_threshold():
    import math

    circle = [(math.cos(k * math.pi / 8), math.sin(k * math.pi / 8)) for k in range(17)]
    assert (
        strokes.match(list(zip(circle, circle[1:], strict=False)), [("8", _curved_eight(32))])
        is None
    )


def test_alphanumeric_pad_labels_keep_their_drawn_characters():
    for word in ("A8", "B8", "2o", "O8", "G8"):
        texts, _ = strokes.read(_drawn(word, 10, 20, 1.8, 0), "eagle")
        assert [t.text for t in texts] == [word]
