"""Write a design as a KiCad netlist or a bill of materials."""

import csv
import io
import re
from collections import defaultdict

from schem2net import __version__, sexpr
from schem2net.ir import Design


def kicad_netlist(design: Design) -> str:
    """A netlist that KiCad's PCB editor can import (Tools > Update PCB from Netlist).

    Footprints are not known from a PDF, so each part has to be given one in KiCad.
    """
    components = ["components"]
    for comp in design.components:
        components.append(
            [
                "comp",
                ["ref", comp.ref],
                ["value", comp.value or "~"],
                ["libsource", ["lib", "schem2net"], ["part", comp.symbol or comp.ref]],
            ]
        )

    nets = ["nets"]
    for code, net in enumerate(design.nets, 1):
        ref, pin = net.pins[0]
        name = net.name or f"Net-({ref}-Pad{pin})"
        nodes = [["node", ["ref", r], ["pin", p]] for r, p in net.pins]
        nets.append(["net", ["code", str(code)], ["name", name], *nodes])

    design_node = [
        "design",
        ["source", design.source.file],
        ["tool", f"schem2net {__version__}"],
    ]
    return sexpr.dump(["export", ["version", "E"], design_node, components, nets]) + "\n"


def bom_csv(design: Design) -> str:
    """Parts grouped by value, one row per value."""
    groups: dict[str, list[str]] = defaultdict(list)
    for comp in design.components:
        groups[comp.value or ""].append(comp.ref)

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["References", "Value", "Quantity"])
    for value, refs in sorted(groups.items(), key=lambda g: _natural(g[1][0])):
        refs.sort(key=_natural)
        writer.writerow([" ".join(refs), value, len(refs)])
    return out.getvalue()


def _natural(ref: str) -> tuple:
    """Sort key that puts R2 before R10."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", ref))


SPICE_PRIMITIVES = {
    "R": "R",
    "C": "C",
    "L": "L",
    "D": "D",
    "LED": "D",
    "Q": "Q",
    "V": "V",
    "I": "I",
}
GROUND_NAMES = {"GND", "0", "AGND", "DGND", "GNDA", "GNDD", "VSS"}


def spice_netlist(design: Design) -> str:
    """A SPICE netlist to start a simulation from.

    Resistors, capacitors, inductors, diodes, transistors and sources become
    primitives; every other part becomes a subcircuit call named after its value.
    Pins are listed in pin-number order, so check the order on polarised parts
    against their models. Ground nets become node 0.
    """
    node_of = {pin: _spice_node(net) for net in design.nets for pin in net.pins}
    lines = [f"* {design.source.file}, extracted by schem2net {__version__}"]
    for comp in sorted(design.components, key=lambda c: _natural(c.ref)):
        pins = sorted({p.num for p in comp.pins}, key=_natural)
        nodes = [node_of.get((comp.ref, p), f"NC_{comp.ref}_{p}") for p in pins]
        if not pins:
            lines.append(f"* {comp.ref} {comp.value or ''}: no pin numbers found".rstrip())
            continue
        prefix = comp.ref.rstrip("0123456789")
        kind = SPICE_PRIMITIVES.get(prefix)
        value = _spice_value(comp.value) if comp.value else "?"
        if kind in ("R", "C", "L", "V", "I") and len(nodes) == 2:
            lines.append(f"{kind}{comp.ref} {' '.join(nodes)} {value}")
        elif kind in ("D", "Q") and len(nodes) in (2, 3):
            lines.append(
                f"{kind}{comp.ref} {' '.join(nodes)} {_spice_name(comp.value or comp.ref)}"
            )
        else:
            lines.append(f"X{comp.ref} {' '.join(nodes)} {_spice_name(comp.value or comp.ref)}")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def _spice_node(net) -> str:
    name = (net.name or "").strip()
    if name.upper() in GROUND_NAMES:
        return "0"
    return _spice_name(name) if name else f"N{net.id[1:]}"


def _spice_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_") or "X"


def _spice_value(value: str) -> str:
    """10k, 4.7uF, 1MΩ or 4R7 written so SPICE reads them: 10k, 4.7u, 1Meg, 4.7."""
    text = value.strip().replace("µ", "u").replace("μ", "u").replace("Ω", "")
    text = re.sub(r"(?i)ohms?$", "", text)
    match = re.fullmatch(r"(\d+)([RpnumkKMG])(\d+)", text)  # 4R7, 2k2
    if match:
        whole, unit, frac = match.groups()
        text = f"{whole}.{frac}{'' if unit == 'R' else unit}"
    text = re.sub(r"(?<=\d)M(?=[A-Za-z]*$)", "Meg", text)
    text = re.sub(r"(?<=\d)K", "k", text)
    text = re.sub(r"(?<=[pnumkg])[FH]$", "", text)
    text = re.sub(r"(?<=\d)R$", "", text)  # 0R, 100R
    return text.replace(" ", "") or "?"
