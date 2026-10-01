"""Reference designators, such as R12 or U5A."""

import re

# Prefix, number, optional unit: "R12", "U5A", "SW_POWER0", "Bat+1", "U$4", and Eagle's
# gates, as in "U2G1".
REFDES = re.compile(r"^([A-Za-z][A-Za-z_+\-$]*?)(\d+)([A-Z]|G\$?\d+)?$")
COMMON_PREFIXES = {
    "A", "BT", "C", "CN", "CON", "D", "DS", "F", "FB", "FD", "FID", "H", "IC", "J", "JP", "K",
    "L", "LCD", "LED", "LS", "M", "MH", "P", "Q", "R", "RN", "RV", "S", "SW", "T", "TH", "TP",
    "U", "VR", "X", "Y", "Z",
}  # fmt: skip


def is_common_ref(text: str) -> bool:
    match = REFDES.match(text)
    # Eagle names parts it was given no prefix for "U$1", "C$2" and so on.
    return bool(match) and match.group(1).rstrip("$") in COMMON_PREFIXES
