"""Explicit numbers inside connector outlines precede hidden-number guesses."""

import math

import pytest

from schem2net import fields, geometry, profile
from schem2net.primitives import Text
from schem2net.scene import Scene
from schem2net.symbols import Pin, Symbol


def connector(ref="P1", count=2, angle=0, words=None):
    c, s = round(math.cos(math.radians(angle))), round(math.sin(math.radians(angle)))

    def turn(x, y):
        return (c * x + s * y, -s * x + c * y)

    def box(x0, y0, x1, y1):
        return geometry.bbox_of(turn(x, y) for x in (x0, x1) for y in (y0, y1))

    pins = [Pin(k, (turn(10, 7 + 2.54 * k), turn(7.46, 7 + 2.54 * k))) for k in range(count)]
    part = Symbol(
        [],
        box(7.46, 5, 16, 9 + 2.54 * (count - 1)),
        pins,
        body=box(10, 5, 16, 9 + 2.54 * (count - 1)),
        ref=ref,
    )
    scene = Scene(page=1)
    for k, word in enumerate(words if words is not None else map(str, range(1, count + 1))):
        y = 7 + 2.54 * k
        scene.pin_numbers.append(
            Text(k, word, box(11.8, y - 0.65, 12.6, y + 0.65), 1.27, angle, (0, 0, 0))
        )
    return part, scene


def number(part, scene):
    fields._number_pins([part], scene, profile.load("altium"), set())


@pytest.mark.parametrize("ref", ["J1", "P1", "CN1", "CON1"])
@pytest.mark.parametrize("count", [2, 4])
@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_complete_inside_connector_numbers_are_read(ref, count, angle):
    part, scene = connector(ref, count, angle)
    number(part, scene)
    assert [p.number for p in part.pins] == list(map(str, range(1, count + 1)))
    assert all(p.how == "read" for p in part.pins)


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_connector_numbers_follow_the_printed_labels_not_pin_order(angle):
    part, scene = connector(count=3, angle=angle, words=("1", "3", "2"))
    number(part, scene)
    assert [p.number for p in part.pins] == ["1", "3", "2"]
    assert all(p.how == "read" for p in part.pins)


@pytest.mark.parametrize("ref", ["U1", "IC1", "R1", "C1"])
def test_numeric_signal_names_and_values_do_not_number_nonconnectors(ref):
    part, scene = connector(ref)
    number(part, scene)
    assert all(p.how != "read" for p in part.pins)


@pytest.mark.parametrize("words", [("1",), ("1", "1"), ("2", "3"), ("1", "A2")])
def test_incomplete_duplicate_or_nonsequential_inside_labels_are_not_pad_numbers(words):
    part, scene = connector(words=words)
    number(part, scene)
    assert all(p.how != "read" for p in part.pins)


def test_ambiguous_inside_numbers_do_not_claim_pins():
    part, scene = connector()
    for text in scene.pin_numbers:
        text.bbox = (11.8, 6.5, 12.6, 10)
    number(part, scene)
    assert all(p.how != "read" for p in part.pins)


def test_inside_labels_do_not_override_external_pad_numbers():
    part, scene = connector()
    for k, word in enumerate(("7", "8")):
        y = 7 + 2.54 * k
        scene.pin_numbers.append(Text(k + 2, word, (8, y - 1.3, 9, y - 0.3), 1.0, 0, (0, 0, 0)))
    number(part, scene)
    assert [p.number for p in part.pins] == ["7", "8"]
    assert all(p.how == "read" for p in part.pins)
