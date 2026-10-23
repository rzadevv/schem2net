import pytest
from hypothesis import given
from hypothesis import strategies as st

from schem2net.bench.score import Counts, compare, intervals, score, summary
from schem2net.ir import Component, Design, Issue, Net, Pin, Source


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


def test_values_match_with_or_without_the_ohm_sign():
    from schem2net.bench.score import _same_value

    assert _same_value("10kΩ", "10k") and _same_value("100 ohms", "100")
    assert not _same_value("10k", "10") and not _same_value("4.7uF", "4.7u")


def test_parts_with_no_value_in_the_truth_are_not_scored_for_value():
    truth = design(
        {"A": [("R1", "1"), ("C1", "1")]}, [part("R1", "Device:R"), part("C1", "Device:C")]
    )
    truth.components[0].value, truth.components[1].value = "10k", "~"
    predicted = design({"A": [("R1", "1"), ("C1", "1")]})
    predicted.components = [Component(ref="R1", value="10k"), Component(ref="C1", value="100n")]
    assert score(predicted, truth).metrics()["value_accuracy"] == 1


def test_a_wrong_pin_no_flag_points_to_is_a_silent_error():
    truth = design({"A": [("U1", "1"), ("R1", "1")], "B": [("U1", "2"), ("R2", "1")]})
    swapped = {"A": [("U1", "2"), ("R1", "1")], "B": [("U1", "1"), ("R2", "1")]}
    silent = score(design(swapped), truth).metrics()
    assert silent["silent_error_rate"] == 0.5 and silent["designs_without_silent_errors"] == 0

    predicted = design(swapped)
    predicted.issues = [Issue(kind="pin_number_guessed", pins=[("U1", "1"), ("U1", "2")])]
    flagged = score(predicted, truth).metrics()
    assert flagged["silent_error_rate"] == 0 and flagged["pin_flag_recall"] == 1
    assert flagged["designs_without_silent_errors"] == 1


def test_swapped_ends_of_a_crystal_are_forgiven_but_not_of_a_connector():
    """Whatever its pads are called, a crystal's two ends are alike; a two-pin header's
    are not, as a battery's polarity depends on them."""
    xtal = Component(ref="Y1", symbol="lib:CRYSTAL-32MHZ", pins=[Pin(num="P$1"), Pin(num="P$2")])
    head = Component(ref="J1", symbol="lib:CONN_02", pins=[Pin(num="1"), Pin(num="2")])
    truth = design(
        {
            "A": [("Y1", "P$1"), ("U1", "1"), ("J1", "1"), ("U1", "3")],
            "B": [("Y1", "P$2"), ("U1", "2"), ("J1", "2"), ("U1", "4")],
        },
        [xtal, head],
    )
    predicted = design(
        {
            "A": [("Y1", "P$2"), ("U1", "1"), ("J1", "2"), ("U1", "3")],
            "B": [("Y1", "P$1"), ("U1", "2"), ("J1", "1"), ("U1", "4")],
        }
    )
    assert score(predicted, truth).metrics()["pin_accuracy"] == 6 / 8


def test_a_pin_left_out_of_every_net_is_counted_as_missed():
    truth = design({"A": [("U1", "1"), ("R1", "1")], "B": [("U1", "2"), ("R2", "1")]})
    found = score(design({"A": [("U1", "1"), ("R1", "1")]}), truth).metrics()
    assert found["missed_pin_rate"] == 0.5 and found["silent_error_rate"] == 0


def test_a_pin_number_the_truth_does_not_have_is_extra():
    """A sign read as a pad number is a pin the part does not have."""
    led = Component(ref="D1", pins=[Pin(num="1", name="K"), Pin(num="2", name="A")])
    truth = design({"A": [("D1", "1"), ("R1", "1")], "B": [("D1", "2"), ("R1", "2")]}, [led])
    predicted = design({"A": [("D1", "+"), ("R1", "1")], "B": [("D1", "A"), ("R1", "2")]})
    assert score(predicted, truth).pins_extra == 1


def test_macro_metrics_weigh_designs_alike():
    small = Counts(designs=1, pins=2, pins_correct=2)
    large = Counts(designs=1, pins=98, pins_correct=0)
    found = summary([small, large])
    assert found["pin_accuracy"] == 0.02 and found["macro_pin_accuracy"] == 0.5


def test_a_change_on_every_design_has_a_tight_interval():
    before = [Counts(designs=1, pins=100, pins_correct=80 + i) for i in range(10)]
    after = [Counts(designs=1, pins=100, pins_correct=85 + i) for i in range(10)]
    first, second, change, low, high = compare(before, after)["pin_accuracy"]
    assert change == pytest.approx(0.05) and low == pytest.approx(0.05)
    assert high == pytest.approx(0.05)
    _, _, change, low, high = compare(before, before)["pin_accuracy"]
    assert change == low == high == 0


def test_an_interval_holds_the_pooled_figure():
    designs = [Counts(designs=1, pins=100, pins_correct=70 + 3 * i) for i in range(10)]
    low, high = intervals(designs)["pin_accuracy"]
    assert low < summary(designs)["pin_accuracy"] < high


def test_a_group_is_drawn_whole():
    """Revisions of one board are not independent: the interval is as wide as their group
    being drawn, or not, together."""
    designs = [Counts(designs=1, pins=100, pins_correct=c) for c in (90, 90, 90, 50, 70, 80)]
    apart = intervals(designs)["pin_accuracy"]
    together = intervals(designs, ["a", "a", "a", "b", "c", "d"])["pin_accuracy"]
    assert together[1] - together[0] > apart[1] - apart[0]
    assert intervals(designs, list(range(6))) == intervals(designs)
