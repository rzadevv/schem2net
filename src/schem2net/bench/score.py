"""Score a predicted design against ground truth.

Nets are unnamed sets of (refdes, pin) pairs. Predicted nets are matched to
true nets one-to-one by maximising Jaccard overlap (Hungarian algorithm), then
every pin is checked against its matched net. See docs/benchmark.md.
"""

import re
from collections import Counter
from dataclasses import dataclass, fields

import numpy as np
from scipy.optimize import linear_sum_assignment

from schem2net.ir import LOW_CONFIDENCE, Component, Design, PinRef

# Two-pin parts whose pins are interchangeable; swapping them is not an error.
SYMMETRIC_SYMBOLS = {
    "R", "R_Small", "R_US", "R_Small_US",
    "C", "C_Small", "L", "L_Small",
    "FerriteBead", "FerriteBead_Small", "Ferrite_Bead", "Ferrite_Bead_Small",
    "Fuse", "Fuse_Small", "Crystal", "Crystal_Small",
}  # fmt: skip
# Parts named after their value or package ("R0402_10K", "C_100n_0402") are
# recognised by designator, unless the name marks them as polarised.
SYMMETRIC_PREFIXES = {"R", "C", "L", "FB", "F"}
POLARISED = re.compile(r"pol|^CP|elec|tant", re.I)

POWER_NET = re.compile(r"^([+-].*|\d+(\.\d+)?V\d*|V(CC|DD|EE|SS|BUS|BAT)\w*|\w*GND\w*)$", re.I)


@dataclass
class Counts:
    """Raw counts. Summing them across designs gives corpus-level metrics."""

    designs: int = 0
    perfect_designs: int = 0
    pins: int = 0
    pins_correct: int = 0
    signal_pins: int = 0
    signal_pins_correct: int = 0
    nets: int = 0
    nets_exact: int = 0
    pairs_true: int = 0
    pairs_predicted: int = 0
    pairs_correct: int = 0
    refs_true: int = 0
    refs_predicted: int = 0
    refs_common: int = 0
    values_known: int = 0  # parts in common whose truth gives a value
    values_correct: int = 0
    wrong_nets: int = 0
    flagged_nets: int = 0
    wrong_flagged: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))

    def metrics(self) -> dict[str, float | None]:
        return {
            "pin_accuracy": _ratio(self.pins_correct, self.pins),
            "signal_pin_accuracy": _ratio(self.signal_pins_correct, self.signal_pins),
            "net_exact": _ratio(self.nets_exact, self.nets),
            "connection_precision": _ratio(self.pairs_correct, self.pairs_predicted),
            "connection_recall": _ratio(self.pairs_correct, self.pairs_true),
            "connection_f1": _ratio(2 * self.pairs_correct, self.pairs_predicted + self.pairs_true),
            "component_precision": _ratio(self.refs_common, self.refs_predicted),
            "component_recall": _ratio(self.refs_common, self.refs_true),
            "value_accuracy": _ratio(self.values_correct, self.values_known),
            "flag_recall": _ratio(self.wrong_flagged, self.wrong_nets),
            "flag_precision": _ratio(self.wrong_flagged, self.flagged_nets),
            "perfect_designs": _ratio(self.perfect_designs, self.designs),
        }


def score(predicted: Design, truth: Design, low_confidence: float = LOW_CONFIDENCE) -> Counts:
    scored = [n for n in truth.nets if len(set(n.pins)) >= 2]
    true_nets = [set(n.pins) for n in scored]
    power = [bool(POWER_NET.match(_short_name(n.name))) for n in scored]
    nonempty = [n for n in predicted.nets if n.pins]
    # A pin drawn with its name and no number is known by that name, when the name
    # is unique on its part.
    aliases = _pin_aliases(truth)
    pred_nets = [{aliases.get(p, p) for p in n.pins} for n in nonempty]
    confidence = [n.confidence for n in nonempty]

    # Pins of symmetric parts may be swapped, so they take no part in the first match.
    loose = {(c.ref, n) for c in truth.components if _is_symmetric(c) for n in ("1", "2")}
    match = match_nets([n - loose for n in true_nets], [n - loose for n in pred_nets])
    pred_nets = _undo_symmetric_swaps(pred_nets, true_nets, match, truth.components)
    match = match_nets(true_nets, pred_nets)

    true_owner = _owners(true_nets)
    pred_owner = _owners(pred_nets)
    c = Counts(designs=1)

    for t, net in enumerate(true_nets):
        p = match.get(t)
        correct = sum(p is not None and pred_owner.get(pin) == p for pin in net)
        c.pins += len(net)
        c.pins_correct += correct
        if not power[t]:
            c.signal_pins += len(net)
            c.signal_pins_correct += correct
            c.pairs_true += _pairs(len(net))
        c.nets += 1
        c.nets_exact += p is not None and pred_nets[p] == net

    signal = {pin for t, net in enumerate(true_nets) if not power[t] for pin in net}
    for net in pred_nets:
        inside = [pin for pin in net if pin in signal]
        c.pairs_predicted += _pairs(len(inside))
        c.pairs_correct += sum(
            _pairs(n) for n in Counter(true_owner[pin] for pin in inside).values()
        )

    true_refs = {comp.ref: comp for comp in truth.components if not comp.ref.startswith("#")}
    pred_refs = {comp.ref: comp for comp in predicted.components}
    common = true_refs.keys() & pred_refs.keys()
    c.refs_true, c.refs_predicted, c.refs_common = len(true_refs), len(pred_refs), len(common)
    # A netlist writes "~" for a part with no value; there is nothing to score.
    known = [r for r in common if (true_refs[r].value or "~").strip() not in ("", "~")]
    c.values_known = len(known)
    c.values_correct = sum(_same_value(true_refs[r].value, pred_refs[r].value) for r in known)

    matched_true = {p: t for t, p in match.items()}
    for p, net in enumerate(pred_nets):
        if not net & true_owner.keys():
            continue  # only pins that are unconnected in the truth; nothing to judge
        wrong = p not in matched_true or net != true_nets[matched_true[p]]
        flagged = confidence[p] < low_confidence
        c.wrong_nets += wrong
        c.flagged_nets += flagged
        c.wrong_flagged += wrong and flagged

    c.perfect_designs = int(c.nets_exact == c.nets and c.wrong_nets == 0)
    return c


def _pin_aliases(truth: Design) -> dict[PinRef, PinRef]:
    """A pin drawn with its name and no number is known by that name, when the name is
    unique on its part. KiCad netlists may write a pin's function as its name and
    number, as in D_1 for pin 1 named D; the name alone counts too."""
    known = {p for n in truth.nets for p in n.pins}
    aliases = {}
    for comp in truth.components:
        names = Counter(n for p in comp.pins for n in _names(p))
        for pin in comp.pins:
            for name in _names(pin):
                alias = (comp.ref, name)
                if names[name] == 1 and alias not in known:
                    aliases[alias] = (comp.ref, pin.num)
    return aliases


def _names(pin) -> set[str]:
    if not pin.name:
        return set()
    names = {pin.name, _drawn(pin.name)}
    suffix = f"_{pin.num}"
    if pin.name.endswith(suffix) and len(pin.name) > len(suffix):
        names |= {n[: -len(suffix)] for n in names}
    return names


def _drawn(name: str) -> str:
    """A name as drawn, without the markup for a bar over it: KiCad's ~{CS}, Eagle's
    !CS and Altium's C\\S\\."""
    return _OVERBAR.sub(r"\1", name).replace("!", "").replace("\\", "")


_OVERBAR = re.compile(r"~\{([^}]*)\}")


def match_nets(true_nets: list[set[PinRef]], pred_nets: list[set[PinRef]]) -> dict[int, int]:
    """Pair true and predicted nets one-to-one, maximising total Jaccard overlap."""
    if not true_nets or not pred_nets:
        return {}
    owner = _owners(pred_nets)
    overlap = np.zeros((len(true_nets), len(pred_nets)), dtype=np.float32)
    for t, net in enumerate(true_nets):
        for p, n in Counter(owner[pin] for pin in net if pin in owner).items():
            overlap[t, p] = n / (len(net) + len(pred_nets[p]) - n)
    rows, cols = linear_sum_assignment(overlap, maximize=True)
    return {int(t): int(p) for t, p in zip(rows, cols, strict=True) if overlap[t, p] > 0}


def _undo_symmetric_swaps(
    pred_nets: list[set[PinRef]],
    true_nets: list[set[PinRef]],
    match: dict[int, int],
    components: list[Component],
) -> list[set[PinRef]]:
    nets = [set(net) for net in pred_nets]
    true_owner = _owners(true_nets)
    pred_owner = _owners(nets)

    def hit(pin: PinRef, owner_of: PinRef) -> bool:
        t, p = true_owner.get(pin), pred_owner.get(owner_of)
        return t is not None and p is not None and match.get(t) == p

    for comp in components:
        if not _is_symmetric(comp):
            continue
        a, b = (comp.ref, "1"), (comp.ref, "2")
        if hit(a, b) + hit(b, a) > hit(a, a) + hit(b, b):
            pa, pb = pred_owner.get(a), pred_owner.get(b)
            if pa is not None:
                nets[pa].discard(a)
                nets[pa].add(b)
            if pb is not None:
                nets[pb].discard(b)
                nets[pb].add(a)
    return nets


def _is_symmetric(comp: Component) -> bool:
    pins = {p.num for p in comp.pins}
    if pins and pins != {"1", "2"}:
        return False
    name = (comp.symbol or "").rsplit(":", 1)[-1]
    if name in SYMMETRIC_SYMBOLS:
        return True
    return not POLARISED.search(name) and comp.ref.rstrip("0123456789") in SYMMETRIC_PREFIXES


def _owners(nets: list[set[PinRef]]) -> dict[PinRef, int]:
    return {pin: i for i, net in enumerate(nets) for pin in net}


def _short_name(name: str | None) -> str:
    return (name or "").rsplit("/", 1)[-1]


def _same_value(a: str | None, b: str | None) -> bool:
    """Values match ignoring spaces, case and an ohm sign written or left off: 10kΩ is
    often drawn as 10k."""
    return _plain_value(a) == _plain_value(b)


def _plain_value(value: str | None) -> str:
    return _OHMS.sub("", "".join((value or "").split()).casefold())


_OHMS = re.compile(r"(?<=\d|[pnuμµmkg])(ω|Ω|ohms?)$")


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None
