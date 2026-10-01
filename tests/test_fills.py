"""Text printed as filled glyph outlines."""

from unittest import mock

from schem2net import fills
from schem2net.primitives import Path

# Two letters as outlines one unit high: an O with its hole, and an L.
O_RINGS = [
    [(0.0, 0.0), (0.7, 0.0), (0.7, 1.0), (0.0, 1.0)],
    [(0.15, 0.15), (0.55, 0.15), (0.55, 0.85), (0.15, 0.85)],
]
L_RINGS = [[(0.0, 0.0), (0.15, 0.0), (0.15, 0.85), (0.6, 0.85), (0.6, 1.0), (0.0, 1.0)]]


def _path(word: str, x: float, y: float, height: float, seq: int, stroke=None) -> Path:
    """A word as one filled path, letters left to right, its baseline at y."""
    rings, left = [], x
    for char in word:
        for ring in {"O": O_RINGS, "L": L_RINGS}[char]:
            rings.append([(left + u * height, y - height + v * height) for u, v in ring])
        left += 0.85 * height
    return Path(seq, rings, 0.0, stroke, (80, 80, 80), curved=True, seq=seq)


def _table():
    """The two letters as a learned table would hold them."""
    found = []
    for char in "OL":
        line = fills.lines([_path(char, 0, 10, 1.5, 0)])[0]
        found.append((char, fills.shape(line.glyphs[0], line)))
    return fills.table_of(found)


def test_filled_text_is_read():
    paths = [_path("LOL", 10, 20, 1.6, 1), _path("OL", 30, 40, 2.0, 2)]
    with mock.patch.object(fills, "_font", lambda name: _table()):
        texts, used = fills.read(paths, "eagle")
    assert sorted(t.text for t in texts) == ["LOL", "OL"]  # the O's hole stays in the O
    assert used == {1, 2}


def test_filled_and_stroked_shapes_are_drawing():
    with mock.patch.object(fills, "_font", lambda name: _table()):
        texts, used = fills.read([_path("LOL", 10, 20, 1.6, 1, stroke=(80, 80, 80))], "eagle")
    assert texts == [] and used == set()


def test_i_or_l_follows_the_word():
    assert fills._i_or_l("ReIeased PCIe I2C AIike") == "Released PCIe I2C Alike"
