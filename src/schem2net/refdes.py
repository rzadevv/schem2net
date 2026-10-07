"""Reference designators, such as R12 or U5A."""

import re

# Prefix, number, optional unit: "R12", "U5A", "SW_POWER0", "Bat+1", "U$4", Eagle's
# gates, as in "U2G1", and EasyEDA's numbered units, as in "U3.1".
REFDES = re.compile(r"^([A-Za-z][A-Za-z_+\-$]*?)(\d+)([A-Z]|G\$?\d+|\.[1-9])?$")
# OrCAD numbers the units of a part split over many sheets after a dash: "U4-18". Only
# after a usual prefix, as a library name such as XR22417-48 has the same form.
NUMBERED_UNIT = re.compile(r"^([A-Z]{1,3})(\d+)(-\d{1,2})$")
COMMON_PREFIXES = {
    "A", "BT", "C", "CN", "CON", "D", "DS", "F", "FB", "FD", "FID", "H", "IC", "J", "JP", "K",
    "L", "LCD", "LED", "LS", "M", "MH", "P", "Q", "R", "RN", "RV", "S", "SW", "T", "TH", "TP",
    "U", "VR", "X", "Y", "Z",
}  # fmt: skip
TWO_TERMINAL_PREFIXES = {"C", "F", "FB", "L", "R"}  # at most a few pins, as a choke has


def is_common_ref(text: str) -> bool:
    match = split_ref(text)
    # Eagle names parts it was given no prefix for "U$1", "C$2" and so on.
    return bool(match) and match.group(1).rstrip("$") in COMMON_PREFIXES


def split_ref(text: str) -> re.Match | None:
    """The designator's prefix, number and unit, if it is one of a usual form."""
    numbered = NUMBERED_UNIT.match(text)
    if numbered and numbered.group(1) in COMMON_PREFIXES:
        return numbered
    return REFDES.match(text)


# A part value such as 100nF, 4.7uH, 10k or 0R, which is never a net name.
PART_VALUE = re.compile(r"^\d+([.,]\d+)?\s*[pnuμµmkKMG]?\s*(F|H|R|Ω|ohms?)?$")
