"""Compare two revisions of a design: parts and connections that changed."""

from dataclasses import dataclass, field

from schem2net.bench.score import match_nets
from schem2net.ir import Design, Net, unnumbered

PinRef = tuple[str, str]


@dataclass
class NetChange:
    name: str
    joined: list[PinRef] = field(default_factory=list)  # pins new to this net
    left: list[PinRef] = field(default_factory=list)  # pins no longer on it


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    revalued: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    nets: list[NetChange] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.revalued or self.nets)


def diff(old: Design, new: Design) -> Diff:
    """Parts are matched by designator, nets by the pins they share, so a renamed
    net is not a change, but a pin moving to another net is."""
    result = Diff()
    old_parts = {c.ref: c for c in old.components}
    new_parts = {c.ref: c for c in new.components}
    result.added = sorted(new_parts.keys() - old_parts.keys())
    result.removed = sorted(old_parts.keys() - new_parts.keys())
    for ref in sorted(old_parts.keys() & new_parts.keys()):
        a, b = old_parts[ref].value, new_parts[ref].value
        if (a or "") != (b or ""):
            result.revalued.append((ref, a, b))

    # Pins of parts that came or went are already reported with the part.
    kept = old_parts.keys() & new_parts.keys()
    old_nets = [n for n in old.nets if _pins(n, kept)]
    new_nets = [n for n in new.nets if _pins(n, kept)]
    pairs = match_nets([_pins(n, kept) for n in old_nets], [_pins(n, kept) for n in new_nets])
    paired_new = set(pairs.values())
    for i, net in enumerate(old_nets):
        before = _pins(net, kept)
        after = _pins(new_nets[pairs[i]], kept) if i in pairs else set()
        name = (new_nets[pairs[i]].name if i in pairs else None) or net.name or _first(before)
        if before != after:
            result.nets.append(NetChange(name, sorted(after - before), sorted(before - after)))
    for j, net in enumerate(new_nets):
        if j not in paired_new:
            pins = _pins(net, kept)
            result.nets.append(NetChange(net.name or _first(pins), joined=sorted(pins)))
    return result


def render(change: Diff) -> str:
    if change.empty:
        return "No changes.\n"
    lines = []
    lines += [f"+ part {ref}" for ref in change.added]
    lines += [f"- part {ref}" for ref in change.removed]
    lines += [f"~ {ref}: {a or '?'} -> {b or '?'}" for ref, a, b in change.revalued]
    for net in change.nets:
        moves = [f"+{r}.{p}" for r, p in net.joined] + [f"-{r}.{p}" for r, p in net.left]
        lines.append(f"  net {net.name}: {' '.join(moves)}")
    return "\n".join(lines) + "\n"


def _pins(net: Net, parts: set[str]) -> set[PinRef]:
    """The net's pins on parts both revisions have. Pins kept without a number are left
    out: their marks are counted afresh in each revision."""
    return {p for p in net.pins if p[0] in parts and not unnumbered(p[1])}


def _first(pins: set[PinRef]) -> str:
    ref, pin = min(pins) if pins else ("?", "?")
    return f"({ref}.{pin})"
