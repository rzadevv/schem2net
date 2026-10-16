"""Score a predicted design against ground truth.

Nets are unnamed sets of (refdes, pin) pairs. Predicted nets are matched to
true nets one-to-one by maximising Jaccard overlap (Hungarian algorithm), then
every pin is checked against its matched net. See docs/benchmark.md.
"""

import re
from collections import Counter
from dataclasses import astuple, dataclass, fields

import numpy as np
from scipy.optimize import linear_sum_assignment

from schem2net.ir import LOW_CONFIDENCE, Component, Design, PinRef, unnumbered

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
# Two-pin parts named for what they are in any library: their ends are alike too.
ALIKE_ENDS = re.compile(r"jumper|crystal|xtal|resonator|sw_push|momentary|tact|fuse|ferrite", re.I)

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
    # Pin by pin, as a reviewer meets them: a pin is flagged when its net is doubtful or
    # an issue names it; a pin on a wrong net nothing flags is a silent error. A pin on
    # no net at all, such as one of a part left out, is counted apart: the netlist is
    # short of it, rather than wrong about it.
    pins_wrong: int = 0
    pins_wrong_flagged: int = 0
    pins_missed: int = 0
    pins_missed_flagged: int = 0
    # Numbered pins on true parts that the truth has no pin of: invented numbers.
    pins_extra: int = 0
    designs_without_silent_errors: int = 0
    # What a reviewer is handed: each doubtful net, and each issue naming pins, is one
    # thing to check; it is worth checking if something there is wrong.
    pin_issues: int = 0
    pin_issues_wrong: int = 0

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
            "silent_error_rate": _ratio(self.pins_wrong - self.pins_wrong_flagged, self.pins),
            "pin_flag_recall": _ratio(self.pins_wrong_flagged, self.pins_wrong),
            "missed_pin_rate": _ratio(self.pins_missed, self.pins),
            "extra_pin_rate": _ratio(self.pins_extra, self.pins),
            "review_items_per_100_pins": _ratio(
                100 * (self.flagged_nets + self.pin_issues), self.pins
            ),
            "review_precision": _ratio(
                self.wrong_flagged + self.pin_issues_wrong, self.flagged_nets + self.pin_issues
            ),
            "designs_without_silent_errors": _ratio(
                self.designs_without_silent_errors, self.designs
            ),
        }


@dataclass
class Aligned:
    """True and predicted nets as sets of pins, the predicted pins known as the truth
    knows them and swapped ends of symmetric parts put back, and the match of each
    true net to a predicted one."""

    true_nets: list[set[PinRef]]
    power: list[bool]
    pred_nets: list[set[PinRef]]
    confidence: list[float]
    doubted: set[PinRef]
    aliases: dict[PinRef, PinRef]
    match: dict[int, int]


def align(predicted: Design, truth: Design) -> Aligned:
    scored = [n for n in truth.nets if len(set(n.pins)) >= 2]
    true_nets = [set(n.pins) for n in scored]
    power = [bool(POWER_NET.match(_short_name(n.name))) for n in scored]
    # Pins kept without a number cannot be judged: the truth knows every pin by its own.
    # One drawn with its name is known by that name.
    names = {
        (c.ref, p.num): (c.ref, p.name)
        for c in predicted.components
        for p in c.pins
        if p.name and unnumbered(p.num)
    }
    known = [
        [names.get(tuple(p), p) for p in n.pins if not unnumbered(p[1]) or tuple(p) in names]
        for n in predicted.nets
    ]
    nonempty = [
        n.model_copy(update={"pins": pins})
        for n, pins in zip(predicted.nets, known, strict=True)
        if pins
    ]
    # A pin drawn with its name and no number is known by that name, when the name
    # is unique on its part.
    aliases = _pin_aliases(truth)
    pred_nets = [{aliases.get(p, p) for p in n.pins} for n in nonempty]
    confidence = [n.confidence for n in nonempty]
    doubted = {aliases.get(p, tuple(p)) for issue in predicted.issues for p in issue.pins}

    # Pins of symmetric parts may be swapped, so they take no part in the first match.
    loose = {(c.ref, n) for c in truth.components for n in _alike_ends(c) or ()}
    match = match_nets([n - loose for n in true_nets], [n - loose for n in pred_nets])
    pred_nets = _undo_symmetric_swaps(pred_nets, true_nets, match, truth.components)
    match = match_nets(true_nets, pred_nets)
    return Aligned(true_nets, power, pred_nets, confidence, doubted, aliases, match)


def score(predicted: Design, truth: Design, low_confidence: float = LOW_CONFIDENCE) -> Counts:
    found = align(predicted, truth)
    true_nets, power, pred_nets = found.true_nets, found.power, found.pred_nets
    confidence, doubted, aliases, match = (
        found.confidence,
        found.doubted,
        found.aliases,
        found.match,
    )

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
    true_pins = {p for n in truth.nets for p in n.pins}
    true_pins |= {(comp.ref, pin.num) for comp in truth.components for pin in comp.pins}
    numbered = {found.aliases.get(tuple(p), tuple(p)) for n in predicted.nets for p in n.pins}
    c.pins_extra = sum(
        p[0] in true_refs and not unnumbered(p[1]) and p not in true_pins for p in numbered
    )

    matched_true = {p: t for t, p in match.items()}
    for p, net in enumerate(pred_nets):
        if not net & true_owner.keys():
            continue  # only pins that are unconnected in the truth; nothing to judge
        wrong = p not in matched_true or net != true_nets[matched_true[p]]
        flagged = confidence[p] < low_confidence
        c.wrong_nets += wrong
        c.flagged_nets += flagged
        c.wrong_flagged += wrong and flagged

    for t, net in enumerate(true_nets):
        for pin in net:
            if pin not in pred_owner:
                c.pins_missed += 1
                c.pins_missed_flagged += pin in doubted
                continue
            p = pred_owner[pin]
            flagged = confidence[p] < low_confidence or pin in doubted
            wrong = match.get(t) != p
            c.pins_wrong += wrong
            c.pins_wrong_flagged += wrong and flagged
    right = {
        pin
        for t, net in enumerate(true_nets)
        for pin in net
        if pin in pred_owner and match.get(t) == pred_owner[pin]
    }
    for issue in predicted.issues:
        named = {aliases.get(tuple(p), tuple(p)) for p in issue.pins} & true_owner.keys()
        if named:
            c.pin_issues += 1
            c.pin_issues_wrong += bool(named - right)
    c.designs_without_silent_errors = int(c.pins_wrong == c.pins_wrong_flagged)
    c.perfect_designs = int(c.nets_exact == c.nets and c.wrong_nets == 0)
    return c


# Metrics also given as the mean over designs, so one large design cannot set them alone.
MACRO = ("pin_accuracy", "connection_f1")


def summary(designs: list[Counts], weights: np.ndarray | None = None) -> dict[str, float | None]:
    """Metrics over designs, pooled and as MACRO means, each design counted as often as
    its weight says (once by default)."""
    if weights is None:
        weights = np.ones(len(designs), dtype=int)
    rows = np.array([astuple(d) for d in designs], dtype=np.int64).reshape(len(designs), -1)
    out = Counts(*(int(v) for v in weights @ rows)).metrics()
    for name in MACRO:
        values = [d.metrics()[name] for d in designs]
        kept = [(w, v) for w, v in zip(weights, values, strict=True) if v is not None and w]
        total = sum(w for w, _ in kept)
        out[f"macro_{name}"] = sum(w * v for w, v in kept) / total if total else None
    return out


def compare(
    before: list[Counts], after: list[Counts], resamples: int = 2000, seed: int = 0
) -> dict[str, tuple[float, float, float, float, float]]:
    """Each metric before and after, the change, and a 95% interval of the change from a
    bootstrap over designs: the same designs, paired, are drawn for both runs."""
    first, second = summary(before), summary(after)
    drawn = [(summary(before, w), summary(after, w)) for w in _draws(len(before), resamples, seed)]
    out = {}
    for name in first:
        if first[name] is None or second[name] is None:
            continue
        changes = [b[name] - a[name] for a, b in drawn if None not in (a[name], b[name])]
        low, high = np.percentile(changes, [2.5, 97.5])
        out[name] = (first[name], second[name], second[name] - first[name], low, high)
    return out


def intervals(
    designs: list[Counts], resamples: int = 2000, seed: int = 0
) -> dict[str, tuple[float, float]]:
    """A 95% interval of each metric from a bootstrap over designs."""
    drawn = [summary(designs, w) for w in _draws(len(designs), resamples, seed)]
    out = {}
    for name in drawn[0]:
        values = [d[name] for d in drawn if d[name] is not None]
        if values:
            low, high = np.percentile(values, [2.5, 97.5])
            out[name] = (float(low), float(high))
    return out


def _draws(n: int, resamples: int, seed: int) -> np.ndarray:
    """How often each of n designs is drawn, in each resample."""
    return np.random.default_rng(seed).multinomial(n, np.full(n, 1 / n), size=resamples)


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
        ends = _alike_ends(comp)
        if not ends:
            continue
        a, b = (comp.ref, ends[0]), (comp.ref, ends[1])
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
    return _alike_ends(comp) is not None


def _alike_ends(comp: Component) -> tuple[str, str] | None:
    """The two pins of a part whose ends are interchangeable, or None."""
    pins = sorted({p.num for p in comp.pins}) or ["1", "2"]
    if len(pins) != 2:
        return None
    name = (comp.symbol or "").rsplit(":", 1)[-1]
    alike = name in SYMMETRIC_SYMBOLS or ALIKE_ENDS.search(name)
    alike = alike or (
        not POLARISED.search(name) and comp.ref.rstrip("0123456789") in SYMMETRIC_PREFIXES
    )
    return (pins[0], pins[1]) if alike else None


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
