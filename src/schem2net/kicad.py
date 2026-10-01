"""Read KiCad netlists (``kicad-cli sch export netlist``) into the IR."""

from pathlib import Path

from schem2net import sexpr
from schem2net.ir import Component, Design, Net, Pin, Source


def read_netlist(path: str | Path) -> Design:
    path = Path(path)
    root = sexpr.parse(path.read_text())
    if root[0] != "export":
        raise ValueError(f"{path} is not a KiCad netlist")

    components = []
    for comp in sexpr.children(sexpr.child(root, "components") or [], "comp"):
        source = sexpr.child(comp, "libsource")
        symbol = None
        if source:
            symbol = f"{sexpr.value(source, 'lib', '')}:{sexpr.value(source, 'part', '')}"
        units = sexpr.child(comp, "units")
        pins = [
            Pin(num=sexpr.value(pin, "num"))
            for unit in sexpr.children(units or [], "unit")
            for pin in sexpr.children(sexpr.child(unit, "pins") or [], "pin")
        ]
        components.append(
            Component(
                ref=sexpr.value(comp, "ref"),
                value=sexpr.value(comp, "value"),
                symbol=symbol,
                pins=pins,
            )
        )

    nets = []
    named: dict[tuple[str, str], str] = {}  # (ref, pin) -> the pin's function name
    for net in sexpr.children(sexpr.child(root, "nets") or [], "net"):
        nodes = sexpr.children(net, "node")
        pins = [(sexpr.value(n, "ref"), sexpr.value(n, "pin")) for n in nodes]
        for n, pin in zip(nodes, pins, strict=True):
            if sexpr.value(n, "pinfunction"):
                named[pin] = sexpr.value(n, "pinfunction")
        nets.append(
            Net(id=f"n{sexpr.value(net, 'code')}", name=sexpr.value(net, "name"), pins=pins)
        )

    for comp in components:
        known = {p.num for p in comp.pins}
        comp.pins += [Pin(num=num) for ref, num in named if ref == comp.ref and num not in known]
        for pin in comp.pins:
            pin.name = named.get((comp.ref, pin.num), pin.name)
    return Design(
        source=Source(file=path.name, generator="kicad"), components=components, nets=nets
    )
