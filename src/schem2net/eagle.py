"""Read the netlist of an Eagle schematic (.sch, XML).

Used as ground truth for Eagle PDFs. Nets join pins by name in the schematic;
each pin is mapped to the pads of its package, which are what the PDF numbers.
Parts without pads, such as frames, supply symbols and logos, are not components.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from schem2net.ir import Component, Design, Net, Pin, Source


def read(path: str | Path) -> Design:
    root = ET.parse(path).getroot()
    schematic = root.find("drawing/schematic")
    if schematic is None:
        raise ValueError(f"{path}: not an Eagle schematic")

    # (library, deviceset, device) -> {(gate, pin name): [pads]}
    pads: dict[tuple[str, str, str], dict[tuple[str, str], list[str]]] = {}
    for library in schematic.iterfind("libraries/library"):
        lib = _library_key(library.get("name", ""), library.get("urn"))
        for deviceset in library.iterfind("devicesets/deviceset"):
            for device in deviceset.iterfind("devices/device"):
                if not device.get("package"):
                    continue
                key = (lib, deviceset.get("name", ""), device.get("name", ""))
                pads[key] = {
                    (c.get("gate", ""), c.get("pin", "")): c.get("pad", "").split()
                    for c in device.iterfind("connects/connect")
                }

    parts: dict[str, tuple[str, str, str]] = {}
    components = []
    for part in schematic.iterfind("parts/part"):
        lib = _library_key(part.get("library", ""), part.get("library_urn"))
        key = (lib, part.get("deviceset", ""), part.get("device", ""))
        if not pads.get(key):  # no package, or a logo or fiducial with no pads
            continue
        name = part.get("name", "")
        parts[name] = key
        # Pins sharing a name are told apart by "@2" and so on, which is never drawn.
        named = {pad: pin.split("@")[0] for (_, pin), pins in pads[key].items() for pad in pins}
        pins = [Pin(num=pad, name=named[pad]) for pad in sorted(named)]
        components.append(Component(ref=name, value=part.get("value"), pins=pins))

    members: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for sheet in schematic.iterfind("sheets/sheet"):
        for net in sheet.iterfind("nets/net"):
            for ref in net.iterfind("segment/pinref"):
                part = ref.get("part", "")
                if part not in parts:
                    continue
                for pad in pads[parts[part]].get((ref.get("gate", ""), ref.get("pin", "")), []):
                    members[net.get("name", "")].add((part, pad))

    nets = [
        Net(id=f"n{i}", name=name, names_seen=[name], pins=sorted(pins))
        for i, (name, pins) in enumerate(sorted(members.items()), 1)
    ]
    source = Source(
        file=Path(path).name, generator="eagle", pages=len(schematic.findall("sheets/sheet"))
    )
    return Design(source=source, components=components, nets=nets)


def _library_key(name: str, urn: str | None) -> str:
    """Libraries are told apart by name and, in newer files, by their managed URN."""
    return f"{name}@{urn}" if urn else name
