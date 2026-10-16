from schem2net.bench.explain import auroc, explain
from schem2net.ir import Component, Pin

from .test_score import design


def test_every_true_pin_lands_in_one_bucket():
    truth = design(
        {
            "A": [("U1", "1"), ("R1", "1"), ("J1", "1")],
            "B": [("U1", "2"), ("R1", "2"), ("J1", "2"), ("U1", "3")],
            "C": [("U4", "1"), ("U5", "1")],
            "D": [("U6", "1"), ("U7", "1")],
            "E": [("U2", "1"), ("U8", "1")],
            "F": [("U2", "2"), ("U9", "1")],
            "G": [("K1", "1"), ("U10", "1")],
            "H": [("M1", "3"), ("U11", "1")],
            "I": [("P1", "2"), ("U12", "1")],
            "J": [("S1", "1"), ("U13", "1")],
            "K": [("T1", "2"), ("U14", "1")],
            "L": [("T1", "1"), ("U15", "1")],
        }
    )
    parts = [
        Component(ref="M1", pins=[Pin(num="9")]),
        Component(ref="P1", pins=[Pin(num="?1")]),
        Component(ref="S1", pins=[Pin(num="1")]),
        Component(ref="T1", pins=[Pin(num="1")]),
    ]
    predicted = design(
        {
            "A": [("U1", "1"), ("R1", "1"), ("J1", "1")],
            "B": [("U1", "2"), ("R1", "2"), ("J1", "2")],
            "B2": [("U1", "3")],
            "CD": [("U4", "1"), ("U5", "1"), ("U6", "1"), ("U7", "1")],
            "E": [("U2", "2"), ("U8", "1")],
            "F": [("U2", "1"), ("U9", "1")],
            "G": [("U10", "1")],
            "H": [("U11", "1"), ("M1", "9")],
            "I": [("U12", "1"), ("P1", "?1")],
            "J": [("U13", "1")],
            "K": [("U14", "1")],
            "L": [("T1", "1"), ("U15", "1")],
        },
        parts,
    )
    found = explain(predicted, truth).pins
    assert dict(found) == {
        "right": 17,
        "renumbered": 2,
        "merged": 2,
        "split": 1,
        "part missing": 1,
        "number differs": 1,
        "unnumbered": 1,
        "on no net": 1,
        "pin missing": 1,
    }


def test_auroc_ranks_doubt_against_wrongness():
    assert auroc([0.9, 0.8, 0.1, 0.0], [True, True, False, False]) == 1
    assert auroc([0.5, 0.5], [True, False]) == 0.5
    assert auroc([0.1, 0.2], [False, False]) is None
