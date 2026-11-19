"""Write a design as a KiCad netlist."""

from schem2net import __version__, sexpr
from schem2net.ir import Design, Net, unnumbered


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

    names = {(c.ref, p.num): p.name for c in design.components for p in c.pins if p.name}
    # KiCad's board editor knows nets by name: two nets of one name would be joined.
    # A pin whose number the drawing does not show has no pad to go to on a board.
    drawn = [
        net.model_copy(update={"pins": pins})
        for net in design.nets
        if (pins := [p for p in net.pins if not unnumbered(p[1])])
    ]
    unique = unique_names(
        drawn, lambda net: net.name or f"Net-({net.pins[0][0]}-Pad{net.pins[0][1]})"
    )
    nets = ["nets"]
    for code, net in enumerate(drawn, 1):
        name = unique[net.id]
        nodes = [
            [
                "node",
                ["ref", r],
                ["pin", p],
                *([["pinfunction", names[r, p]]] if (r, p) in names else []),
            ]
            for r, p in net.pins
        ]
        nets.append(["net", ["code", str(code)], ["name", name], *nodes])

    design_node = [
        "design",
        ["source", design.source.file],
        ["tool", f"schem2net {__version__}"],
    ]
    return sexpr.dump(["export", ["version", "E"], design_node, components, nets]) + "\n"


def unique_names(nets: list[Net], name_of) -> dict[str, str]:
    """A name for every net, by id, none given twice: a name already taken gets _2, _3."""
    names, taken = {}, set()
    for net in nets:
        base = name_of(net)
        name, k = base, 2
        while name in taken:
            name, k = f"{base}_{k}", k + 1
        taken.add(name)
        names[net.id] = name
    return names
