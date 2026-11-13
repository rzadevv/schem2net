"""Roles of paths and texts on pages printed without colour."""

from dataclasses import replace

import numpy as np
import pytest

from schem2net import fields, geometry, nets, profile, roles, scene, symbols
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

    def scores(self, rows, kinds=roles.PATH_ROLES):
        out = np.zeros((len(rows), len(kinds) + 1))
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


def _recolour_texts(texts, rule):
    page = _page(GREY)
    page.texts = texts
    wire, symbol = (roles.PATH_ROLES.index(k) for k in ("wire", "symbol"))
    path_model = _Stub(lambda row: wire if row[6] else symbol)
    return roles.recolour(page, profile.load("kicad"), (path_model, path_model, _Stub(rule)))


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
@pytest.mark.parametrize("number_size", [1.3, 0.9])
def test_fragmented_reference_keeps_one_role_and_its_original_geometry(angle, number_size):
    along, across = geometry.reading_frame(angle)

    def fragment(id_, word, left, right, size):
        corners = [
            (11 + x * along[0] + y * across[0], -4 + x * along[1] + y * across[1])
            for x in (left, right)
            for y in (0, size)
        ]
        return Text(id_, word, geometry.bbox_of(corners), size, angle, GREY, id_)

    pieces = [fragment(3, "R", 0, 1, 1.3), fragment(4, "12", 1, 3, number_size)]
    before = [replace(t) for t in pieces]
    field = roles.TEXT_ROLES.index("field")
    pin = roles.TEXT_ROLES.index("pin_number")
    # The alphabetic fragment looks like a field; the numeric fragment like a pin.
    result = _recolour_texts(pieces, lambda row: field if row[2] else pin)
    assert all(profile.load("kicad").is_("field", t.color) for t in result.texts)
    assert pieces == before
    assert result.texts == [replace(t, color=result.texts[i].color) for i, t in enumerate(before)]
    built = scene.build(result, profile.load("kicad"))
    assert [t.text for t in built.fields] == ["R12"]
    if angle == 0:
        part = symbols.Symbol(
            [],
            (7, -2, 17, 2),
            body=(10, -2, 14, 2),
            pins=[symbols.Pin(0, ((10, 0), (7, 0))), symbols.Pin(1, ((14, 0), (17, 0)))],
        )
        fields.annotate([part], built, profile.load("kicad"), None)
        assert part.ref == "R12"


def test_fragmented_label_keeps_its_identity_and_a_real_word_space():
    pieces = [
        Text(3, "DATA", (11, -4, 15, -2.7), 1.3, 0, GREY, 3),
        Text(4, "OUT", (15.4, -4, 18.4, -2.7), 1.3, 0, GREY, 4),
    ]
    local, field = (roles.TEXT_ROLES.index(k) for k in ("local_label", "field"))
    result = _recolour_texts(pieces, lambda row: local if row[0] > 3 else field)
    assert all(profile.load("kicad").is_("local_label", t.color) for t in result.texts)
    assert [t.text for t in result.texts] == ["DATA", "OUT"]
    built = scene.build(result, profile.load("kicad"))
    assert [(t.text, t.kind) for t in built.labels] == [("DATA OUT", "local")]


def test_consistent_field_survives_a_misleading_joined_label_prediction():
    pieces = [
        Text(3, "R7", (11, -4, 13, -2.7), 1.3, 0, GREY, 3),
        Text(4, "4", (13, -4, 14, -2.7), 1.3, 0, GREY, 4),
    ]
    field, local = (roles.TEXT_ROLES.index(k) for k in ("field", "local_label"))
    rules = profile.load("kicad")
    built = scene.build(_recolour_texts(pieces, lambda row: local if row[0] == 3 else field), rules)
    part = symbols.Symbol(
        [],
        (7, -2, 17, 2),
        body=(10, -2, 14, 2),
        pins=[symbols.Pin(0, ((10, 0), (7, 0))), symbols.Pin(1, ((14, 0), (17, 0)))],
    )
    fields.annotate([part], built, rules, None)
    assert part.ref == "R74"
    other = symbols.Symbol(
        [], (-3, -1, 0, 1), ref="J2", pins=[symbols.Pin(2, ((-2, 0), (0, 0)), "1")]
    )
    netlister = nets.Netlister()
    netlister.add_page(built, [part, other])
    assert any(set(n.pins) == {("R74", "1"), ("J2", "1")} for n in netlister.result().nets)


def test_fragmented_pin_number_reaches_the_intended_terminal():
    pieces = [
        Text(3, "1", (8, -1.5, 8.6, -0.3), 1.3, 0, GREY, 3),
        Text(4, "2", (8.6, -1.5, 9.2, -0.3), 1.3, 0, GREY, 4),
    ]
    pin, field = (roles.TEXT_ROLES.index(k) for k in ("pin_number", "field"))
    result = _recolour_texts(pieces, lambda row: pin if row[0] >= 2 or row[9] < 1 else field)
    assert all(profile.load("kicad").is_("pin_number", t.color) for t in result.texts)
    built = scene.build(result, profile.load("kicad"))
    part = symbols.Symbol(
        [],
        (7, -1, 14, 1),
        body=(10, -1, 14, 1),
        ref="J1",
        pins=[symbols.Pin(0, ((10, 0), (7, 0)))],
    )
    fields._number_pins([part], built, profile.load("kicad"), set())
    assert part.pins[0].number == "12"
    assert part.pins[0].how == "read"
    other = symbols.Symbol(
        [], (-3, -1, 0, 1), ref="J2", pins=[symbols.Pin(1, ((-2, 0), (0, 0)), "1")]
    )
    netlister = nets.Netlister()
    netlister.add_page(built, [part, other])
    assert any(set(n.pins) == {("J1", "12"), ("J2", "1")} for n in netlister.result().nets)
    built.wires = []
    disconnected = nets.Netlister()
    disconnected.add_page(built, [part, other])
    assert not disconnected.result().nets


@pytest.mark.parametrize("boundary", ["angle", "colour", "drawing order", "gap", "baseline"])
def test_distinct_texts_keep_separate_roles(boundary):
    first = Text(3, "R", (11, -4, 12, -2.7), 1.3, 0, GREY, 3)
    second = Text(4, "12", (12, -4, 14, -2.7), 1.3, 0, GREY, 4)
    changes = {
        "angle": {"angle": 90},
        "colour": {"color": (30, 30, 30)},
        "drawing order": {"seq": 6},
        "gap": {"bbox": (20, -4, 22, -2.7)},
        "baseline": {"bbox": (12, 0, 14, 1.3)},
    }
    second = replace(second, **changes[boundary])
    field, pin = (roles.TEXT_ROLES.index(k) for k in ("field", "pin_number"))
    result = _recolour_texts([first, second], lambda row: field if row[2] else pin)
    assert profile.load("kicad").is_("field", result.texts[0].color)
    assert profile.load("kicad").is_("pin_number", result.texts[1].color)


def test_complete_designator_does_not_absorb_a_neighboring_label_or_number():
    pieces = [
        Text(3, "R12", (11, -4, 14, -2.7), 1.3, 0, GREY, 3),
        Text(4, "DATA", (14.4, -4, 18.4, -2.7), 1.3, 0, GREY, 4),
        Text(5, "7", (18.4, -1, 19, 0.3), 1.3, 0, GREY, 5),
        Text(6, "hidden", (0, 0, 2, 1), 1.3, 0, GREY, 6, visible=False),
    ]
    field, local, pin = (roles.TEXT_ROLES.index(k) for k in ("field", "local_label", "pin_number"))
    result = _recolour_texts(pieces, lambda row: pin if row[4] else field if row[1] else local)
    rules = profile.load("kicad")
    assert [
        rules.is_(kind, t.color)
        for kind, t in zip(("field", "local_label", "pin_number"), result.texts[:3], strict=True)
    ] == [True, True, True]
    assert result.texts[3] == pieces[3]


@pytest.mark.parametrize("size", [1.0, 1.8])
@pytest.mark.parametrize("shorted", [False, True])
def test_recovered_reference_preserves_voltage_and_ground_connections(size, shorted):
    """Isolate roles -> scene -> field assignment -> nets with known symbol geometry.

    A joined prediction alone would erase the voltage labels. A deliberately added
    short must still produce a real supply-conflict warning and capped confidence.
    """
    page = Page(1, 50, 40)
    parts = []

    def shape(*points):
        k = len(page.paths)
        page.paths.append(Path(k, [list(points)], 0.152, GREY, None, seq=k))

    def text(word, box, seq):
        page.texts.append(Text(seq, word, box, size, 0, GREY, seq))

    for x in (10, 30):
        k = len(page.paths)
        shape((x - 1, 10), (x + 1, 10), (x + 1, 15), (x - 1, 15), (x - 1, 10))
        shape((x, 10), (x, 7.46))
        shape((x, 15), (x, 17.54))
        shape((x, 7.46), (x, 6.19))
        shape((x - 1.27, 6.19), (x + 1.27, 6.19))
        shape((x, 17.54), (x, 18.81), (x + 1.27, 18.81), (x, 20.08), (x - 1.27, 18.81), (x, 18.81))
        body = (x - 1, 10, x + 1, 15)
        parts.append(
            symbols.Symbol(
                [k, k + 1, k + 2],
                (x - 1, 7.46, x + 1, 17.54),
                body=body,
                pins=[
                    symbols.Pin(k + 1, ((x, 10), (x, 7.46))),
                    symbols.Pin(k + 2, ((x, 15), (x, 17.54))),
                ],
            )
        )
        for indices, box in [
            ([k + 3, k + 4], (x - 1.27, 6.19, x + 1.27, 7.46)),
            ([k + 5], (x - 1.27, 17.54, x + 1.27, 20.08)),
        ]:
            parts.append(symbols.Symbol(indices, box, body=box))
    text("R", (12, 11, 12.8, 12.27), 20)
    text("12", (12.8, 11, 14.4, 12.27), 21)
    text("R2", (32, 11, 34, 12.27), 23)
    for i, x in enumerate((10, 30)):
        text("9", (x - 1.2, 3.5, x - 0.4, 4.77), 25 + 3 * i)
        text("V", (x - 0.4, 3.5, x + 0.4, 4.77), 26 + 3 * i)
    field, pin, local = (roles.TEXT_ROLES.index(k) for k in ("field", "pin_number", "local_label"))

    def rule(row):
        if row[10] < 2:  # the power head is near both voltage fragments
            return local if row[0] == 1 else field
        return field if row[2] else pin

    drawing = _Stub(lambda row: roles.PATH_ROLES.index("symbol"))
    rules = profile.load("altium")
    built = scene.build(roles.recolour(page, rules, (drawing, drawing, _Stub(rule))), rules)
    fields.annotate(parts, built, rules, symbols.Runs(parts, built, rules))
    if shorted:
        built.wires.append(((10, 7.46), (10, 17.54)))
    netlister = nets.Netlister()
    netlister.add_page(built, parts)
    found = netlister.result()
    assert {c.ref for c in found.components} == {"R12", "R2"}
    if shorted:
        assert any(i.kind == "power_nets_merged" for i in found.issues)
        assert all(n.confidence < 0.8 for n in found.nets)
    else:
        by_name = {n.name: set(n.pins) for n in found.nets}
        assert by_name == {"9V": {("R12", "2"), ("R2", "2")}, "GND": {("R12", "1"), ("R2", "1")}}
        assert not found.issues
        assert [s.power_hidden for s in parts if s.power == "9V"] == [False, False]
        assert [s.power_hidden for s in parts if s.power == "GND"] == [True, True]


def test_complete_label_keeps_its_fragment_context_beside_a_recovered_reference():
    pieces = [
        Text(3, "R", (11, -4, 12, -2.7), 1.3, 0, GREY, 3),
        Text(4, "12", (12, -4, 14, -2.7), 1.3, 0, GREY, 4),
        Text(6, "SYNC", (14.4, -4, 18.4, -2.7), 1.3, 0, GREY, 6),
    ]
    field, pin, local = (roles.TEXT_ROLES.index(k) for k in ("field", "pin_number", "local_label"))

    def rule(row):
        if row[0] == 4:
            return local if row[13] >= 2 else field
        return field if row[2] else pin

    built = scene.build(_recolour_texts(pieces, rule), profile.load("kicad"))
    assert [t.text for t in built.fields] == ["R12"]
    assert [t.text for t in built.labels] == ["SYNC"]
    built.wires = [((15, -2.4), (20, -2.4))]
    parts = [
        symbols.Symbol(
            [], (13, -3, 15, -2), ref="R12", pins=[symbols.Pin(0, ((14, -2.4), (15, -2.4)), "1")]
        ),
        symbols.Symbol(
            [], (20, -3, 22, -2), ref="J2", pins=[symbols.Pin(1, ((21, -2.4), (20, -2.4)), "1")]
        ),
    ]
    netlister = nets.Netlister()
    netlister.add_page(built, parts)
    (connected,) = netlister.result().nets
    assert connected.name == "SYNC"
    assert set(connected.pins) == {("R12", "1"), ("J2", "1")}
    built.wires = []
    disconnected = nets.Netlister()
    disconnected.add_page(built, parts)
    (labelled_pin,) = disconnected.result().nets
    assert labelled_pin.name == "SYNC"
    assert labelled_pin.pins == [("R12", "1")]


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


def test_texts_of_one_unknown_colour_share_the_role_most_of_them_have():
    """A theme gives each kind of text its colour: net labels in the theme's label colour
    are labels, though the model takes one of them, alone, for a field. Which kind of
    label each is, local or global, it keeps."""
    kicad = profile.load("kicad")
    local, other, field = (
        roles.TEXT_ROLES.index(r) for r in ("local_label", "global_label", "field")
    )
    page = _page((0, 150, 0))
    page.texts = [
        Text(k, name, (10 * k, -4, 10 * k + 3, -2.5), 1.3, 0.0, (194, 0, 0), k)
        for k, name in enumerate(("SDA", "SCL", "MISO", "USB"), 3)
    ]
    found = iter((local, field, local, other))
    models = (None, None, _Stub(lambda row: next(found)))
    named = roles.name_unknown_texts(page, kicad, models)
    kinds = [
        "global_label"
        if kicad.is_("global_label", t.color)
        else "local_label"
        if kicad.is_("local_label", t.color)
        else None
        for t in named.texts
    ]
    assert kinds == ["local_label", "local_label", "local_label", "global_label"]


def test_a_name_drawn_with_a_mark_of_its_colour_is_not_a_net_label():
    """A net label has no drawing of its own; a directive's name sits by its mark."""
    red = (255, 0, 0)
    name = Text(1, "USB", (10, 9, 13, 10), 1.0, 0.0, red, 1)
    wire = Path(2, [[(0, 10.3), (20, 10.3)]], 0.15, red, None, seq=2)  # laid along
    mark = Path(3, [[(7, 9.5), (8, 9.0), (9, 9.5)]], 0.15, red, None, seq=3)

    def drawn_with(paths):
        index = roles.geometry.GridIndex(cell=2.0)
        for k, p in enumerate(paths):
            index.add(k, p.bbox)
        return roles._drawn_with(name, paths, index)

    assert not drawn_with([wire])
    assert drawn_with([wire, mark])


def test_fields_take_the_designators_own_colour_where_there_is_one():
    """OrCAD prints designators and values navy and other properties black: a text
    found to be a field is given navy, so it may be read as a designator."""
    field = roles.TEXT_ROLES.index("field")
    assert roles._colour(profile.load("orcad"), roles.TEXT_ROLES, field) == (0, 0, 128)
    assert roles._colour(profile.load("kicad"), roles.TEXT_ROLES, field) == (0, 100, 100)


def test_a_page_made_black_keeps_its_white():
    from schem2net.pipeline import _in_black

    page = Page(1, 10, 10)
    page.paths = [
        Path(0, [[(0, 0), (1, 1)]], 0.1, (255, 0, 0), None),
        Path(1, [[(0, 0), (1, 0), (1, 1), (0, 0)]], 0.1, None, (255, 255, 255)),
    ]
    page.texts = [Text(0, "U1", (0, 0, 1, 1), 1.0, 0.0, (0, 0, 128))]
    black = _in_black(page)
    assert [p.stroke or p.fill for p in black.paths] == [(0, 0, 0), (255, 255, 255)]
    assert roles.colourless(black) and black.texts[0].color == (0, 0, 0)


def test_learned_files_are_read_from_a_folder_given(tmp_path):
    assert roles.learned("kicad")
    profile.use_learned(tmp_path)  # a folder where nothing was learned
    try:
        assert not roles.learned("kicad")
    finally:
        profile.use_learned(None)
    assert roles.learned("kicad")
