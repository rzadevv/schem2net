"""Roles of paths and texts on pages printed without colour."""

import numpy as np

from schem2net import profile, roles
from schem2net.primitives import Page, Path, Text

GREY = (60, 60, 60)


def _page(ink) -> Page:
    wire = Path(1, [[(0, 0), (10, 0)]], 0.15, ink, None, seq=1)
    body = Path(2, [[(10, -2), (14, -2), (14, 2), (10, 2), (10, -2)]], 0.25, ink, None, seq=2)
    name = Text(3, "R1", (11, -4, 13, -2.5), 1.3, 0.0, ink, 3)
    return Page(1, 50, 50, paths=[wire, body], texts=[name])


def test_a_page_in_black_or_grey_is_colourless():
    assert roles.colourless(_page((0, 0, 0))) and roles.colourless(_page(GREY))
    page = _page(GREY)
    page.paths[0].stroke = (0, 150, 0)
    assert not roles.colourless(page)


def test_forest_sums_tree_scores_per_class():
    # One round of two trees, each one split on feature 0 at 5: low rows score for
    # class 7, high ones for class 9. Node indices count from each tree's start.
    tree = {"feature": [0, 0, 0], "threshold": [5.0, 0, 0], "left": [1, -1, -1]}
    arrays = {
        "m.classes": np.array([7, 9]),
        "m.baseline": np.zeros(2),
        "m.starts": np.array([0, 3]),
        "m.depths": np.array([1, 1]),
        "m.feature": np.array(tree["feature"] * 2),
        "m.threshold": np.array(tree["threshold"] * 2),
        "m.left": np.array(tree["left"] * 2),
        "m.right": np.array([2, -1, -1] * 2),
        "m.value": np.array([0, 1.0, -1.0, 0, -1.0, 1.0]),
    }
    forest = roles.Forest(arrays, "m")
    assert forest.predict(np.array([[2.0], [8.0]])).tolist() == [7, 9]


class _Stub:
    """A model that gives every row the role a rule picks for it."""

    def __init__(self, rule):
        self.rule = rule

    def predict(self, rows):
        return np.array([self.rule(r) for r in rows])

    def scores(self, rows):
        out = np.zeros((len(rows), len(roles.PATH_ROLES) + 1))
        out[np.arange(len(rows)), self.predict(rows)] = 1.0
        return out


def test_recolour_gives_each_role_its_colour():
    eagle = profile.load("eagle")
    wire, symbol = roles.PATH_ROLES.index("wire"), roles.PATH_ROLES.index("symbol")
    field = roles.TEXT_ROLES.index("field")
    lines = _Stub(lambda row: wire if row[6] else symbol)  # lines are wires, the rest symbol
    models = (lines, lines, _Stub(lambda row: field))

    page = roles.recolour(_page((0, 0, 0)), eagle, models)
    assert eagle.is_("wire", page.paths[0].stroke)
    assert eagle.is_("symbol", page.paths[1].stroke)
    assert eagle.is_("field", page.texts[0].color)


def test_texts_in_unknown_colours_take_a_predicted_role():
    """A theme of the designer's own: a label in a colour the profile does not know."""
    kicad = profile.load("kicad")
    local = roles.TEXT_ROLES.index("local_label")
    page = _page((0, 150, 0))  # a wire in KiCad's own colour
    page.texts = [
        Text(3, "SD", (11, -4, 12, -2.5), 1.3, 0.0, (194, 0, 0), 3),  # split in two
        Text(4, "A", (12, -4, 13, -2.5), 1.3, 0.0, (194, 0, 0), 4),
        Text(5, "R1", (20, -4, 22, -2.5), 1.3, 0.0, (0, 100, 100), 5),  # a known field
    ]
    models = (None, None, _Stub(lambda row: local))
    named = roles.name_unknown_texts(page, kicad, models)
    assert [kicad.is_("local_label", t.color) for t in named.texts] == [True, True, False]
