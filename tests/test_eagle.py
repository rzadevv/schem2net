"""Eagle schematics as ground truth, and text drawn with a stroke font."""

import json
from importlib import resources

from schem2net import eagle, strokes
from schem2net.primitives import Path

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
    assert nets["GND"] == [("R1", "2"), ("U1", "2"), ("U1", "4")]  # one pin, two pads
    u1 = next(c for c in design.components if c.ref == "U1")
    assert {p.num: p.name for p in u1.pins} == {"1": "IN", "2": "GND", "3": "OUT", "4": "GND"}


def _drawn(text: str, x: float, y: float, height: float, seq: int) -> list[Path]:
    """Draw a word with the font's own glyph shapes, the way a PDF would."""
    table = json.loads(
        resources.files("schem2net").joinpath("profiles", "eagle_font.json").read_text()
    )
    shapes = {e["char"]: e["shapes"][0] for e in table}
    paths = []
    for i, char in enumerate(text):
        left = x + i * 0.9 * height
        for (a, b), (c, d) in shapes[char]:
            points = [(left + a * height, y - b * height), (left + c * height, y - d * height)]
            paths.append(Path(seq, [points], 0.15, (80, 80, 80), None, seq=seq))
            seq += 1
    return paths


def test_stroke_text_is_read():
    paths = _drawn("R12", 10, 20, 1.8, 0) + _drawn("10k", 10, 30, 1.8, 100)
    texts, used = strokes.read(paths, "eagle")
    assert sorted(t.text for t in texts) == ["10k", "R12"]
    assert len(used) == len(paths)
