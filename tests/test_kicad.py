import pytest

from schem2net import kicad, sexpr

NETLIST = """(export (version "E")
  (components
    (comp (ref "R1") (value "10k")
      (libsource (lib "Device") (part "R") (description ""))
      (units (unit (name "A") (pins (pin (num "1")) (pin (num "2")))))))
  (nets
    (net (code "1") (name "/SDA \\"bus\\"") (class "Default")
      (node (ref "R1") (pin "1") (pintype "passive"))
      (node (ref "U1") (pin "5") (pinfunction "SDA") (pintype "bidirectional")))
    (net (code "2") (name "GND")
      (node (ref "R1") (pin "2")))))
"""


def test_parse():
    tree = sexpr.parse('(a "b c" (d 1) (d 2))')
    assert tree == ["a", "b c", ["d", "1"], ["d", "2"]]
    assert sexpr.children(tree, "d") == [["d", "1"], ["d", "2"]]
    assert sexpr.value(tree, "d") == "1"
    assert sexpr.value(tree, "missing", "x") == "x"


@pytest.mark.parametrize("text", ["(a", "(a))", "(a) (b)", ""])
def test_parse_rejects_malformed(text):
    with pytest.raises(ValueError):
        sexpr.parse(text)


def test_read_netlist(tmp_path):
    path = tmp_path / "x.net"
    path.write_text(NETLIST)
    design = kicad.read_netlist(path)

    (r1,) = design.components
    assert (r1.ref, r1.value, r1.symbol) == ("R1", "10k", "Device:R")
    assert [p.num for p in r1.pins] == ["1", "2"]
    sda, gnd = design.nets
    assert sda.name == '/SDA "bus"'
    assert sda.pins == [("R1", "1"), ("U1", "5")]
    assert gnd.pins == [("R1", "2")]
