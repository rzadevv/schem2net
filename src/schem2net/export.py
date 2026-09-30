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
