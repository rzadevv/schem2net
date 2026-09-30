"""Questions about an extracted design, answered from its netlist."""

import re

from schem2net.ir import LOW_CONFIDENCE, Design, Net

PIN = re.compile(r"^\s*([^\s.:]+)\s*[.:\s]\s*(\S+)\s*$")  # U3.14, U3:14, U3 14
PASSIVES = {"R", "C", "L", "FB"}  # designator prefixes a trace may pass through
TRACE_MAX_PINS = 6  # a trace stops at bigger nets, such as power rails


class Query:
    def __init__(self, design: Design):
        self.design = design
        self.components = {c.ref: c for c in design.components}
        self.net_of_pin = {pin: net for net in design.nets for pin in net.pins}

    def components_list(self, prefix: str = "") -> list[dict]:
        return [
            {"ref": c.ref, "value": c.value, "pins": len(c.pins)}
            for c in self.design.components
            if c.ref.startswith(prefix)
        ]

    def net(self, name_or_pin: str) -> dict | None:
        """A net by name ("GND") or by one of its pins ("U3.14")."""
        pin = _pin(name_or_pin)
        if pin and pin in self.net_of_pin:
            return _net(self.net_of_pin[pin])
        wanted = name_or_pin.strip().lstrip("/")
        for net in self.design.nets:
            if any(n.lstrip("/") == wanted for n in net.names_seen):
                return _net(net)
        return None

    def pins_of(self, ref: str) -> list[dict] | None:
        comp = self.components.get(ref)
        if comp is None:
            return None
        rows = []
        for pin in comp.pins:
            net = self.net_of_pin.get((ref, pin.num))
            rows.append({"pin": pin.num, "net": _label(net) if net else None})
        return rows

    def trace(self, pin: str, depth: int = 2) -> list[dict] | None:
        """Nets reached from a pin through two-pin passives, such as series resistors.

        The trace does not continue past large nets such as power rails.
        """
        start = _pin(pin)
        if start is None or start not in self.net_of_pin:
            return None
        seen = {self.net_of_pin[start].id}
        frontier = [(self.net_of_pin[start], [])]
        found = [{"net": _label(frontier[0][0]), "via": []}]
        for _ in range(depth):
            reached = []
            for net, via in frontier:
                if len(net.pins) > TRACE_MAX_PINS:
                    continue
                for ref, num in net.pins:
                    comp = self.components.get(ref)
                    if not comp or len(comp.pins) != 2 or not _passive(ref):
                        continue
                    other = next(p.num for p in comp.pins if p.num != num)
                    far = self.net_of_pin.get((ref, other))
                    if far and far.id not in seen:
                        seen.add(far.id)
                        step = [*via, f"{ref} ({comp.value or '?'})"]
                        reached.append((far, step))
                        found.append({"net": _label(far), "via": step})
            frontier = reached
        return found

    def low_confidence(self) -> list[dict]:
        return [_net(n) for n in self.design.nets if n.confidence < LOW_CONFIDENCE]

    def bom(self) -> list[dict]:
        groups: dict[str, list[str]] = {}
        for comp in self.design.components:
            groups.setdefault(comp.value or "", []).append(comp.ref)
        return [{"value": v, "refs": refs, "quantity": len(refs)} for v, refs in groups.items()]


def _pin(text: str) -> tuple[str, str] | None:
    match = PIN.match(text)
    return (match[1], match[2]) if match else None


def _passive(ref: str) -> bool:
    return ref.rstrip("0123456789") in PASSIVES


def _label(net: Net) -> str:
    return net.name or net.id


def _net(net: Net) -> dict:
    return {
        "id": net.id,
        "name": net.name,
        "other_names": net.names_seen[1:],
        "pins": [f"{ref}.{num}" for ref, num in net.pins],
        "confidence": net.confidence,
        "pages": net.pages,
    }
