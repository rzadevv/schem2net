import re
import tomllib
from importlib import resources

import pytest

from schem2net import pipeline, profile, symbols
from schem2net.primitives import Page, Path, Text
from schem2net.scene import build as build_scene


@pytest.mark.parametrize("name", sorted(pipeline.PROFILES))
def test_every_profile_loads(name):
    assert profile.load(name).name == name


@pytest.mark.parametrize(
    ("section", "key", "named"),
    [
        ("pins", "max_widht", "pins.max_widht"),
        ("colors", "wires", "colors.wires"),
        ("pinz", "x", "[pinz]"),
    ],
)
def test_a_misspelt_key_is_an_error(section, key, named):
    text = resources.files("schem2net").joinpath("profiles", "kicad.toml").read_text()
    data = tomllib.loads(text)
    data.setdefault(section, {})[key] = [[0, 0, 0]] if section == "colors" else 1.0
    with pytest.raises(ValueError, match=re.escape(named)):
        profile.parse("kicad", data)


@pytest.mark.parametrize(
    "body, field, number",
    [
        ((132, 0, 0), (0, 100, 100), (169, 0, 0)),
        ((156, 155, 152), (147, 147, 145), (165, 164, 162)),
        ((161, 161, 161), (152, 152, 152), (170, 170, 170)),
    ],
)
def test_kicad_unpopulated_parts_keep_their_fields_and_pin_numbers(body, field, number):
    rules = profile.load("kicad")
    page = Page(1, 50, 50)
    points = [
        [(10, 10), (14, 10), (14, 16), (10, 16), (10, 10)],
        [(10, 12), (7.46, 12)],
        [(10, 14.54), (7.46, 14.54)],
    ]
    page.paths = [Path(i, [p], 0.152, body, None, seq=i) for i, p in enumerate(points)]
    page.texts = [
        Text(0, "1", (8, 10.9, 8.6, 11.6), 0.7, 0, number, 3),
        Text(1, "2", (8, 13.44, 8.6, 14.14), 0.7, 0, number, 4),
        Text(2, "J1", (10, 8, 12, 9), 1, 0, field, 5),
        Text(3, "NA(HEADER)", (10, 17, 16, 18), 1, 0, field, 6),
    ]
    # The DNP cross, pale fill and neutral annotation are not symbol geometry.
    for color in ((235, 58, 61), (240, 240, 240), (72, 72, 72)):
        page.paths.append(Path(len(page.paths), [[(9, 9), (15, 17)]], 0.15, color, None))
    scene = build_scene(page, rules)
    assert len(scene.shapes) == 3
    assert {t.text for t in scene.fields} == {"J1", "NA(HEADER)"}
    assert {t.text for t in scene.pin_numbers} == {"1", "2"}
    parts = symbols.find(scene, rules)
    assert [(s.ref, s.value, sorted(p.number for p in s.pins)) for s in parts] == [
        ("J1", "NA(HEADER)", ["1", "2"])
    ]
