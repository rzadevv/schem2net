"""Reference designators, such as R12 or U5A."""

import re

# Prefix, number, optional unit: "R12", "U5A", "SW_POWER0", "Bat+1", "U$4", Eagle's
# gates, as in "U2G1", and EasyEDA's numbered units, as in "U3.1".
REFDES = re.compile(r"^([A-Za-z][A-Za-z_+\-$]*?)(\d+)([A-Z]|G\$?\d+|\.[1-9])?$")
COMMON_PREFIXES = {
    "A", "BT", "C", "CN", "CON", "D", "DS", "F", "FB", "FD", "FID", "H", "IC", "J", "JP", "K",
    "L", "LCD", "LED", "LS", "M", "MH", "P", "Q", "R", "RN", "RV", "S", "SW", "T", "TH", "TP",
    "U", "VR", "X", "Y", "Z",
}  # fmt: skip
TWO_TERMINAL_PREFIXES = {"C", "F", "FB", "L", "R"}  # at most a few pins, as a choke has


def is_common_ref(text: str) -> bool:
    match = REFDES.match(text)
    # Eagle names parts it was given no prefix for "U$1", "C$2" and so on.
    return bool(match) and match.group(1).rstrip("$") in COMMON_PREFIXES


# A part value such as 100nF, 4.7uH, 10k or 0R, which is never a net name.
PART_VALUE = re.compile(r"^\d+([.,]\d+)?\s*[pnuμµmkKMG]?\s*(F|H|R|Ω|ohms?)?$")
