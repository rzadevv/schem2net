"""EasyEDA (Std) schematics as ground truth."""

import json

from schem2net import easyeda


def _resistor(ref: str, x: float, y: float) -> str:
    """A horizontal resistor with pins 1 and 2 ending at x and x + 40."""
    # A pin: its head, its connection point, its line, then its name and number texts.
    pins = [
        "^^".join(
            [
                f"P~show~0~{n}~{px}~{y}~0~p{ref}{n}~0",
                f"{px}~{y}",
                "M 0 0 h 10~#800",
                f"0~0~0~0~{n}~start",
                f"0~0~0~0~{n}~start",
            ]
        )
        for n, px in ((1, x), (2, x + 40))
    ]
    texts = [
        f"T~P~{x}~{y - 10}~0~#000080~Arial~~~~~comment~{ref}~1~start~t1~0~pinpart",
        f"T~N~{x}~{y - 20}~0~#000080~Arial~~~~~comment~10k~1~start~t2~0~pinpart",
        f"T~PK~{x}~{y + 10}~0~#0000FF~Arial~~~~~comment~R0805~1~start~t3~0~pinpart",
    ]
    return "#@$".join([f"LIB~{x}~{y}~package`R0805`~~0~{ref}~", *pins, *texts])


def test_easyeda_netlist_from_drawing(tmp_path):
    shapes = [
        _resistor("R1", 0, 0),
        _resistor("R2", 0, 50),
        "W~40 0 80 0 80 50 40 50~#008800~1~0~none~w1~0",  # R1.2 to R2.2
        "W~60 0 60 -30~#008800~1~0~none~w2~0",  # a branch from the middle of the first leg
        "F~part_netLabel_gnD~60~-30~0~f1~~0^^60~-30^^GND~#000000~0~0~0~start~1",
        "W~0 50 -20 50~#008800~1~0~none~w3~0",
        "N~-20~50~0~#000080~SENSE~n1~start~0~0~Arial~",
    ]
    sheet = {"head": {"docType": "1"}, "shape": shapes}
    path = tmp_path / "board.json"
    # An older file: each sheet stored as a JSON string.
    path.write_text(json.dumps({"schematics": [{"dataStr": json.dumps(sheet)}]}))

    design = easyeda.read(path)
    assert [(c.ref, c.value) for c in design.components] == [("R1", "10k"), ("R2", "10k")]
    nets = {n.name: n.pins for n in design.nets}
    assert nets["GND"] == [("R1", "2"), ("R2", "2")]  # the flag sits on the branch
    assert nets["SENSE"] == [("R2", "1")]
    assert [n.pins for n in design.nets if n.name is None] == [[("R1", "1")]]
