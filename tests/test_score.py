import pytest
from hypothesis import given
from hypothesis import strategies as st

from schem2net.bench.score import Counts, score
from schem2net.ir import Component, Design, Net, Pin, Source


def design(nets, components=(), confidence=None):
    return Design(
        source=Source(file="x.pdf"),
        components=list(components),
        nets=[
            Net(id=f"n{i}", name=name, pins=pins, confidence=(confidence or {}).get(name, 1.0))
            for i, (name, pins) in enumerate(nets.items())
        ],
    )


def part(ref, symbol, value=None):
    return Component(ref=ref, symbol=symbol, value=value, pins=[Pin(num="1"), Pin(num="2")])


TRUTH = design(
    {
        "GND": [("U1", "1"), ("C1", "2"), ("R1", "2")],
        "SDA": [("U1", "2"), ("R1", "1"), ("J1", "1")],
        "SCL": [("U1", "3"), ("J1", "2")],
        "unconnected-(U1-Pad4)": [("U1", "4")],
    },
    [part("R1", "Device:R", "4k7"), part("C1", "Device:C_Polarized", "10u"), Component(ref="U1")],
)


def test_perfect_prediction():
    m = score(TRUTH, TRUTH).metrics()
    assert m["pin_accuracy"] == 1
    assert m["signal_pin_accuracy"] == 1
    assert m["net_exact"] == 1
    assert m["connection_f1"] == 1
    assert m["component_recall"] == 1
    assert m["value_accuracy"] == 1
    assert m["perfect_designs"] == 1


def test_empty_prediction_scores_zero():
    m = score(design({}), TRUTH).metrics()
    assert m["pin_accuracy"] == 0
    assert m["connection_f1"] == 0
    assert m["component_recall"] == 0
    assert m["perfect_designs"] == 0


def test_single_pin_nets_are_not_scored():
    assert score(TRUTH, TRUTH).pins == 8


def test_power_nets_are_scored_separately():
    c = score(TRUTH, TRUTH)
    assert c.signal_pins == 5
    assert c.pairs_true == 3 + 1  # SDA has three pairs, SCL one


def test_swapped_resistor_is_not_an_error():
    predicted = design(
        {
            "GND": [("U1", "1"), ("C1", "2"), ("R1", "1")],
            "SDA": [("U1", "2"), ("R1", "2"), ("J1", "1")],
            "SCL": [("U1", "3"), ("J1", "2")],
        }
    )
    assert score(predicted, TRUTH).metrics()["pin_accuracy"] == 1


def test_swapped_polarised_capacitor_is_an_error():
    truth = design(
        {"A": [("C1", "1"), ("U1", "1")], "B": [("C1", "2"), ("U1", "2")]},
        [part("C1", "Device:C_Polarized")],
    )
    predicted = design({"A": [("C1", "2"), ("U1", "1")], "B": [("C1", "1"), ("U1", "2")]})
    assert score(predicted, truth).metrics()["pin_accuracy"] == pytest.approx(0.5)


def test_swapped_pins_on_parts_named_by_value():
    truth = design(
        {"A": [("C7", "1"), ("U1", "1")], "B": [("C7", "2"), ("U1", "2")]},
        [part("C7", "Project:C_100n_0402")],
    )
    predicted = design({"A": [("C7", "2"), ("U1", "1")], "B": [("C7", "1"), ("U1", "2")]})
    assert score(predicted, truth).metrics()["pin_accuracy"] == 1

    truth.components = [part("C7", "Device:CP")]
    assert score(predicted, truth).metrics()["pin_accuracy"] == pytest.approx(0.5)


def test_pins_known_by_name_as_kicad_writes_it():
    """kicad-cli writes pin 1 named D as D_1; a pin read by its drawn name D is pin 1."""
    q = Component(ref="Q1", pins=[Pin(num="1", name="D_1"), Pin(num="2", name="G_2")])
    truth = design({"A": [("Q1", "1"), ("R1", "1")], "B": [("Q1", "2"), ("R2", "1")]}, [q])
    predicted = design({"A": [("Q1", "D"), ("R1", "1")], "B": [("Q1", "G_2"), ("R2", "1")]})
    assert score(predicted, truth).metrics()["pin_accuracy"] == 1


def test_pins_known_by_name_as_drawn_without_overbar_markup():
    """Eagle writes a barred CS as !CS and KiCad as ~{RST}; the PDF draws CS and RST."""
    u = Component(ref="U1", pins=[Pin(num="6", name="!CS"), Pin(num="7", name="~{RST}")])
    truth = design({"A": [("U1", "6"), ("R1", "1")], "B": [("U1", "7"), ("R2", "1")]}, [u])
    predicted = design({"A": [("U1", "CS"), ("R1", "1")], "B": [("U1", "RST"), ("R2", "1")]})
    assert score(predicted, truth).metrics()["pin_accuracy"] == 1


def test_many_swapped_decoupling_capacitors_are_not_errors():
    caps = [part(f"C{i}", "Device:C") for i in range(1, 6)]
    truth = design(
        {
            "GND": [("U1", "1")] + [(c.ref, "1") for c in caps],
            "VCC": [("U1", "2")] + [(c.ref, "2") for c in caps],
        },
        caps,
    )
    # With most capacitors turned round, VCC would look like the best match for GND.
    predicted = design(
        {
            "GND": [("U1", "1"), ("C1", "1")] + [(c.ref, "2") for c in caps[1:]],
            "VCC": [("U1", "2"), ("C1", "2")] + [(c.ref, "1") for c in caps[1:]],
        }
    )
    assert score(predicted, truth).metrics()["pin_accuracy"] == 1


def test_merged_nets():
    predicted = design(
        {
            "GND": [("U1", "1"), ("C1", "2"), ("R1", "2")],
            "BUS": [("U1", "2"), ("R1", "1"), ("J1", "1"), ("U1", "3"), ("J1", "2")],
        }
    )
    m = score(predicted, TRUTH).metrics()
    assert m["pin_accuracy"] == pytest.approx(6 / 8)
    assert m["net_exact"] == pytest.approx(1 / 3)
    assert m["connection_recall"] == 1
    assert m["connection_precision"] == pytest.approx(4 / 10)


def test_flags():
    predicted = design(
        {
            "GND": [("U1", "1"), ("C1", "2"), ("R1", "2")],
            "BUS": [("U1", "2"), ("R1", "1"), ("J1", "1"), ("U1", "3"), ("J1", "2")],
        },
        confidence={"GND": 0.5, "BUS": 0.5},
    )
    m = score(predicted, TRUTH).metrics()
    assert m["flag_recall"] == 1
    assert m["flag_precision"] == pytest.approx(0.5)


def test_counts_add_up():
    total = score(TRUTH, TRUTH) + score(design({}), TRUTH)
    assert total.designs == 2
    assert total.metrics()["pin_accuracy"] == pytest.approx(0.5)
    assert sum([score(TRUTH, TRUTH)], Counts()).pins == 8


pin_names = st.tuples(st.sampled_from("UJQ"), st.integers(1, 30).map(str))
partitions = st.lists(st.sets(pin_names, min_size=2, max_size=6), min_size=1, max_size=8)


@given(partitions, st.randoms())
def test_score_ignores_net_order_and_names(groups, rng):
    seen, nets = set(), []
    for group in groups:
        group -= seen
        seen |= group
        if len(group) >= 2:
            nets.append(sorted(group))
    truth = design({f"t{i}": pins for i, pins in enumerate(nets)})
    shuffled = nets[:]
    rng.shuffle(shuffled)
    predicted = design({f"p{i}": pins for i, pins in enumerate(shuffled)})

    c = score(predicted, truth)
    assert c.pins_correct == c.pins
    assert c.nets_exact == c.nets
