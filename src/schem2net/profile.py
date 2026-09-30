"""Generator profiles: the drawing conventions of one EDA tool, stored as data."""

import tomllib
from dataclasses import dataclass
from importlib import resources

from schem2net.primitives import Color


@dataclass(frozen=True)
class Profile:
    name: str
    colors: dict[str, frozenset[Color]]
    pin_max_width: float
    pin_min_length: float
    fields_follow_symbol: bool = False
    not_power_nets: frozenset[str] = frozenset()
    pin_numbers_above: bool = False
    sheet_file_prefix: str | None = None
    sheet_path_prefix: str | None = None

    def is_(self, role: str, color: Color | None) -> bool:
        return color is not None and color in self.colors.get(role, frozenset())


def load(name: str) -> Profile:
    text = resources.files("schem2net").joinpath("profiles", f"{name}.toml").read_text()
    data = tomllib.loads(text)
    colors = {role: frozenset(tuple(c) for c in values) for role, values in data["colors"].items()}
    return Profile(
        name=name,
        colors=colors,
        pin_max_width=data["pins"]["max_width"],
        pin_min_length=data["pins"]["min_length"],
        pin_numbers_above=data["pins"].get("numbers_above", False),
        fields_follow_symbol=data.get("order", {}).get("fields_follow_symbol", False),
        not_power_nets=frozenset(data.get("power", {}).get("not_nets", [])),
        sheet_file_prefix=data.get("sheets", {}).get("file_prefix"),
        sheet_path_prefix=data.get("sheets", {}).get("path_prefix"),
    )
