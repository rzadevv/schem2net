"""Reference designators, such as R12 or U5A."""

import re

# Prefix, number, optional unit letter: "R12", "U5A", "SW_POWER0", "Bat+1".
REFDES = re.compile(r"^([A-Za-z][A-Za-z_+\-]*?)(\d+)([A-Z]?)$")
COMMON_PREFIXES = {
    "A", "BT", "C", "CN", "CON", "D", "DS", "F", "FB", "FD", "FID", "H", "IC", "J", "JP", "K",
    "L", "LCD", "LED", "LS", "M", "MH", "P", "Q", "R", "RN", "RV", "S", "SW", "T", "TH", "TP",
    "U", "VR", "X", "Y", "Z",
}  # fmt: skip


def is_common_ref(text: str) -> bool:
    match = REFDES.match(text)
    return bool(match) and match.group(1) in COMMON_PREFIXES
