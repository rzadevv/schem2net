"""Read the netlist of an Eagle schematic (.sch, XML).

Used as ground truth for Eagle PDFs. Nets join pins by name in the schematic;
each pin is mapped to the pad of its package, which is what the PDF numbers. A pin
on several pads is drawn with the first of them and a count ("1*56"), so it is
that one pad here. Parts without pads, such as frames, supply symbols and logos,
are not components.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from schem2net.ir import Component, Design, Net, Pin, Source


def read(path: str | Path) -> Design:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        raise ValueError(f"{path}: not an Eagle schematic in XML, as Eagle 6 on writes") from None
    schematic = root.find("drawing/schematic")
    if schematic is None:
        raise ValueError(f"{path}: not an Eagle schematic")

    # (library, deviceset, device) -> {(gate, pin name): pad}
    pads: dict[tuple[str, str, str], dict[tuple[str, str], str]] = {}
    for library in schematic.iterfind("libraries/library"):
        lib = _library_key(library.get("name", ""), library.get("urn"))
        for deviceset in library.iterfind("devicesets/deviceset"):
            for device in deviceset.iterfind("devices/device"):
                if not device.get("package"):
                    continue
                key = (lib, deviceset.get("name", ""), device.get("name", ""))
                pads[key] = {
                    (c.get("gate", ""), c.get("pin", "")): c.get("pad", "").split()[0]
                    for c in device.iterfind("connects/connect")
                    if c.get("pad", "").strip()
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
        named = {pad: pin.split("@")[0] for (_, pin), pad in pads[key].items()}
        pins = [Pin(num=pad, name=named[pad]) for pad in sorted(named)]
        symbol = part.get("deviceset", "")  # what the part is: JUMPER-SMT_2_NO, CRYSTAL...
        components.append(Component(ref=name, value=part.get("value"), symbol=symbol, pins=pins))

    members: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for sheet in schematic.iterfind("sheets/sheet"):
        for net in sheet.iterfind("nets/net"):
            for ref in net.iterfind("segment/pinref"):
                part = ref.get("part", "")
                if part not in parts:
                    continue
                pad = pads[parts[part]].get((ref.get("gate", ""), ref.get("pin", "")))
                if pad:
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
