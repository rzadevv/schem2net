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
        fields_follow_symbol=data.get("order", {}).get("fields_follow_symbol", False),
        not_power_nets=frozenset(data.get("power", {}).get("not_nets", [])),
    )
