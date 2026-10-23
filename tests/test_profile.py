import re
import tomllib
from importlib import resources

import pytest

from schem2net import pipeline, profile


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
