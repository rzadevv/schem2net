"""Where each true pin went, and whether confidence ranks the doubtful ones.

Each true pin falls in one bucket. On a predicted net: right, renumbered (its net is
where another pin of its part belongs, so its number was misread), merged (its net
holds pins of other true nets) or split (its net is short of pins). On none: part
missing, number differs (its part has a number the truth lacks), unnumbered (its
part has a pin kept as ?1), on no net (its part lists it, on no net) or pin missing
(its part has no trace of it).
"""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import rankdata

from schem2net.bench.score import Counts, align, score
from schem2net.ir import Design, unnumbered

BUCKETS = (
    "right",
    "renumbered",
    "merged",
    "split",
    "part missing",
    "number differs",
    "unnumbered",
    "on no net",
    "pin missing",
)


@dataclass
class Explanation:
    pins: Counter = field(default_factory=Counter)
    nets: list[tuple[float, bool]] = field(default_factory=list)  # confidence, wrong
    # Pins on a predicted net: their net's confidence, named by an issue, wrong.
    doubts: list[tuple[float, bool, bool]] = field(default_factory=list)


def judge(predicted: Design, truth: Design) -> tuple[Counts, Explanation]:
    return score(predicted, truth), explain(predicted, truth)


def explain(predicted: Design, truth: Design) -> Explanation:
    found = align(predicted, truth)
    true_nets, pred_nets, match = found.true_nets, found.pred_nets, found.match
    true_owner = {pin: t for t, net in enumerate(true_nets) for pin in net}
    pred_owner = {pin: p for p, net in enumerate(pred_nets) for pin in net}
    matched_true = {p: t for t, p in match.items()}
    out = Explanation()

    absent: dict[str, list] = {}
    for t, net in enumerate(true_nets):
        for pin in sorted(net):
            p = pred_owner.get(pin)
            if p is None:
                absent.setdefault(pin[0], []).append(pin)
                continue
            wrong = match.get(t) != p
            out.doubts.append((found.confidence[p], pin in found.doubted, wrong))
            if not wrong:
                out.pins["right"] += 1
            elif p in matched_true and any(
                q[0] == pin[0] for q in true_nets[matched_true[p]] if q != pin
            ):
                out.pins["renumbered"] += 1
            elif any(true_owner.get(q, t) != t for q in pred_nets[p]):
                out.pins["merged"] += 1
            else:
                out.pins["split"] += 1

    true_pins = {p for n in truth.nets for p in n.pins}
    true_pins |= {(c.ref, pin.num) for c in truth.components for pin in c.pins}
    parts = {c.ref: c for c in predicted.components}
    on_nets: dict[str, set] = {}
    for net in predicted.nets:
        for ref, num in net.pins:
            on_nets.setdefault(ref, set()).add(num)
    for ref, pins in absent.items():
        if ref not in parts:
            out.pins["part missing"] += len(pins)
            continue
        drawn = {pin.num for pin in parts[ref].pins} | on_nets.get(ref, set())
        listed = {found.aliases.get((ref, n), (ref, n)) for n in drawn if not unnumbered(n)}
        left = len(pins)
        for bucket, room in (
            ("on no net", sum(pin in listed for pin in pins)),
            ("number differs", len(listed - true_pins)),
            ("unnumbered", sum(unnumbered(n) for n in drawn)),
            ("pin missing", left),
        ):
            taken = min(room, left)
            out.pins[bucket] += taken
            left -= taken

    for p, net in enumerate(pred_nets):
        if net & true_owner.keys():
            wrong = p not in matched_true or net != true_nets[matched_true[p]]
            out.nets.append((found.confidence[p], wrong))
    return out


def report(results: list[tuple[str, Explanation]]) -> list[str]:
    """The ledger per design and in total, then error by confidence."""
    lines = [f"{'design':32} {'pins':>6} " + " ".join(f"{b[:10]:>10}" for b in BUCKETS)]
    total = Explanation()
    for name, found in results:
        lines.append(_ledger(name, found.pins))
        total.pins += found.pins
        total.nets += found.nets
        total.doubts += found.doubts
    lines.append(_ledger("TOTAL", total.pins))

    lines += ["", f"{'confidence':>10} {'nets':>6} {'wrong':>6} {'pins':>7} {'wrong':>6}"]
    nets = _by_confidence(total.nets)
    pins = _by_confidence([(c, w) for c, _, w in total.doubts])
    for bin_ in sorted(nets.keys() | pins.keys(), reverse=True):
        n, p = nets.get(bin_, (0, 0)), pins.get(bin_, (0, 0))
        lines.append(f"{bin_:>10} {n[0]:>6} {_share(n):>6} {p[0]:>7} {_share(p):>6}")
    auc = auroc([1 - c + named for c, named, _ in total.doubts], [w for *_, w in total.doubts])
    lines.append(f"AUROC of pin doubt against pin wrongness: {auc:.3f}" if auc else "")
    return lines


def auroc(scores: list[float], wrong: list[bool]) -> float | None:
    """Chance that a wrong pin is doubted more than a right one, ties counting half."""
    wrong = np.asarray(wrong, dtype=bool)
    if wrong.all() or not wrong.any():
        return None
    ranks = rankdata(scores)
    n = int(wrong.sum())
    return float((ranks[wrong].sum() - n * (n + 1) / 2) / (n * (len(wrong) - n)))


def _ledger(name: str, pins: Counter) -> str:
    total = sum(pins.values())
    shares = " ".join(f"{100 * pins[b] / total if total else 0:>9.1f}%" for b in BUCKETS)
    return f"{name[:32]:32} {total:>6} {shares}"


def _by_confidence(rows: list[tuple[float, bool]]) -> dict[str, tuple[int, int]]:
    """Counts and wrong counts by tenths of confidence; full confidence on its own."""
    out: dict[str, list[int]] = {}
    for confidence, wrong in rows:
        key = "1.0" if confidence >= 1 else f"{int(confidence * 10) / 10:.1f}-"
        counts = out.setdefault(key, [0, 0])
        counts[0] += 1
        counts[1] += wrong
    return {k: (n, w) for k, (n, w) in out.items()}


def _share(counts: tuple[int, int]) -> str:
    return f"{100 * counts[1] / counts[0]:.0f}%" if counts[0] else "-"
