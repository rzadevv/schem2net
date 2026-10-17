"""Generator profiles: the drawing conventions of one EDA tool, stored as data."""

import tomllib
from dataclasses import dataclass, field
from importlib import resources

from schem2net.primitives import Color


@dataclass(frozen=True)
class Profile:
    name: str
    colors: dict[str, frozenset[Color]]
    pin_max_width: float
    pin_min_length: float
    pin_numbers_above: bool = False
    pin_numbers_overhang: bool = False  # a number may overhang the tip of a short pin
    hidden_pin_one_at_bottom: bool = False
    pins_at_body_edge: bool = False
    pinless_at_body_edge: bool = False  # only parts drawn with no pin line at all
    flags_on_pins: bool = False  # port flags may sit straight on a pin's tip
    symbols_in_pieces: bool = False  # symbols drawn as separate lines, as ground bars
    lines_in_pieces: bool = False  # outlines printed one line at a time
    pin_name_gap: float = 1.5  # mm between a pin's inner end and its name
    diode_pin_one_is_anode: bool = False
    diode_pin_names: tuple[str, ...] = ()  # cathode and anode pads, where named so
    pin_numbers_have_digits: bool = False  # a text with no digit by a pin is its name
    learned_grouping: bool = False  # groups split where the learned model links nothing
    # A transistor's pads by role, for each package a part's value may name, as
    # SOT23 = { G = "1", S = "2", D = "3" }; none known yet.
    pin_roles: dict[str, dict[str, str]] = field(default_factory=dict)
    pin_library: str | None = None  # symbol library that numbers the pins left unnumbered
    fields_follow_symbol: bool = False
    pins_after_fields: bool = False  # each symbol's pins are drawn after its texts
    labels_follow_flags: bool = False  # each flag's name, in the label colour, follows it
    drawn_by_part: bool = False  # each part drawn whole, with designators between parts
    designator_first: bool = False
    value_before_designator: bool = False  # each part's value is drawn right before its designator
    names_by_layer: bool = False  # all part names drawn together, and all values
    wires_drawn_together: bool = False
    thick_wires_are_buses: bool = False
    wire_grids: tuple[float, ...] = ()  # mm; usual grids of wire ends, standard first
    page_scale: float | None = None  # the exporter's fixed scale, where it has one
    infer_wire_colour: bool = False
    designators_in_any_colour: bool = False
    designators_in_pin_colour: bool = False
    designators_outside: bool = False  # the libraries place designators outside the body
    labels_span_pages: bool = False
    names_case_blind: bool = False  # net names differing only in case are one net
    labels_in_outlines: bool = False
    labels_on_wires: bool = False  # a field-coloured name laid along a wire is its label
    labels_show_sheet: bool = False  # "NAME/2": the sheet the net goes on to
    text_font: str | None = None
    texts_by_shape: bool = True  # texts in colours of no role take a role learned from shape
    not_power_nets: frozenset[str] = frozenset()
    power_names_in_labels: bool = False
    label_name_gap: float | None = None  # mm from a flag to its name in the label colour
    power_name_gap: float | None = None  # mm from a power symbol to its name
    unnamed_ground: str | None = None
    ground_signs: dict[str, str] = field(default_factory=dict)  # hidden names, by sign
    ground_stems: bool = False  # the unnamed ground's sign has a stem that reads as a pin
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
        pin_numbers_overhang=pins.get("numbers_overhang", False),
        hidden_pin_one_at_bottom=pins.get("hidden_one_at_bottom", False),
        pins_at_body_edge=bool(pins.get("at_body_edge", False)),
        pinless_at_body_edge=pins.get("at_body_edge") == "pinless",
        flags_on_pins=pins.get("flags_on_tips", False),
        symbols_in_pieces=order.get("symbols_in_pieces", False),
        lines_in_pieces=order.get("lines_in_pieces", False),
        pin_name_gap=pins.get("name_gap", 1.5),
        diode_pin_one_is_anode=pins.get("diode_one_is_anode", False),
        diode_pin_names=tuple(pins.get("diode_names", ())),
        pin_roles=pins.get("roles", {}),
        pin_numbers_have_digits=pins.get("numbers_have_digits", False),
        learned_grouping=data.get("parts", {}).get("grouping") == "learned",
        pin_library=pins.get("library"),
        fields_follow_symbol=order.get("fields_follow_symbol", False),
        pins_after_fields=order.get("pins_after_fields", False),
        labels_follow_flags=order.get("labels_follow_flags", False),
        drawn_by_part=order.get("by_part", False) or order.get("fields_follow_symbol", False),
        designator_first=order.get("designator_first", False),
        value_before_designator=order.get("value_before_designator", False),
        names_by_layer=order.get("names_by_layer", False),
        wires_drawn_together=order.get("wires_drawn_together", False),
        thick_wires_are_buses=wires.get("thick_are_buses", False),
        infer_wire_colour=wires.get("infer_colour", False),
        wire_grids=tuple(_listed(wires.get("grid", []))),
        page_scale=data.get("page", {}).get("scale"),
        designators_in_any_colour=order.get("designators_in_any_colour", False),
        designators_in_pin_colour=order.get("designators_in_pin_colour", False),
        designators_outside=order.get("designators_outside", False),
        labels_span_pages=labels.get("span_pages", False),
        names_case_blind=labels.get("case_blind", False),
        labels_in_outlines=labels.get("in_outlines", False),
        labels_on_wires=labels.get("on_wires", False),
        labels_show_sheet=labels.get("sheet_reference", False),
        text_font=text.get("font"),
        texts_by_shape=text.get("by_shape", True),
        not_power_nets=frozenset(power.get("not_nets", [])),
        power_names_in_labels=power.get("names_in_labels", False),
        label_name_gap=power.get("label_gap"),
        power_name_gap=power.get("name_gap"),
        unnamed_ground=power.get("unnamed_ground"),
        ground_signs=power.get("ground_signs", {}),
        ground_stems=power.get("ground_stems", False),
        sheet_file_prefix=sheets.get("file_prefix"),
        sheet_path_prefix=sheets.get("path_prefix"),
    )


def _listed(value) -> list:
    return value if isinstance(value, list) else [value]
