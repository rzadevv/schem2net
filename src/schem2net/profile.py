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
    pin_numbers_above: bool = False
    hidden_pin_one_at_bottom: bool = False
    pins_at_body_edge: bool = False
    pin_name_gap: float = 1.5  # mm between a pin's inner end and its name
    diode_pin_one_is_anode: bool = False
    fields_follow_symbol: bool = False
    designator_first: bool = False
    wires_drawn_together: bool = False
    thick_wires_are_buses: bool = False
    wire_grids: tuple[float, ...] = ()  # mm; usual grids of wire ends, standard first
    infer_wire_colour: bool = False
    designators_in_any_colour: bool = False
    designators_in_pin_colour: bool = False
    labels_span_pages: bool = False
    labels_in_outlines: bool = False
    labels_show_sheet: bool = False  # "NAME/2": the sheet the net goes on to
    text_font: str | None = None
    not_power_nets: frozenset[str] = frozenset()
    power_names_in_labels: bool = False
    unnamed_ground: str | None = None
    sheet_file_prefix: str | None = None
    sheet_path_prefix: str | None = None

    def is_(self, role: str, color: Color | None) -> bool:
        return color is not None and color in self.colors.get(role, frozenset())


def load(name: str) -> Profile:
    text = resources.files("schem2net").joinpath("profiles", f"{name}.toml").read_text()
    data = tomllib.loads(text)
    sections = ("pins", "order", "power", "sheets", "wires", "labels", "text")
    pins, order, power, sheets, wires, labels, text = (data.get(k, {}) for k in sections)
    return Profile(
        name=name,
        colors={
            role: frozenset(tuple(c) for c in values) for role, values in data["colors"].items()
        },
        pin_max_width=pins["max_width"],
        pin_min_length=pins["min_length"],
        pin_numbers_above=pins.get("numbers_above", False),
        hidden_pin_one_at_bottom=pins.get("hidden_one_at_bottom", False),
        pins_at_body_edge=pins.get("at_body_edge", False),
        pin_name_gap=pins.get("name_gap", 1.5),
        diode_pin_one_is_anode=pins.get("diode_one_is_anode", False),
        fields_follow_symbol=order.get("fields_follow_symbol", False),
        designator_first=order.get("designator_first", False),
        wires_drawn_together=order.get("wires_drawn_together", False),
        thick_wires_are_buses=wires.get("thick_are_buses", False),
        infer_wire_colour=wires.get("infer_colour", False),
        wire_grids=tuple(_listed(wires.get("grid", []))),
        designators_in_any_colour=order.get("designators_in_any_colour", False),
        designators_in_pin_colour=order.get("designators_in_pin_colour", False),
        labels_span_pages=labels.get("span_pages", False),
        labels_in_outlines=labels.get("in_outlines", False),
        labels_show_sheet=labels.get("sheet_reference", False),
        text_font=text.get("font"),
        not_power_nets=frozenset(power.get("not_nets", [])),
        power_names_in_labels=power.get("names_in_labels", False),
        unnamed_ground=power.get("unnamed_ground"),
        sheet_file_prefix=sheets.get("file_prefix"),
        sheet_path_prefix=sheets.get("path_prefix"),
    )


def _listed(value) -> list:
    return value if isinstance(value, list) else [value]
