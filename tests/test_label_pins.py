"""Bare labels may attach at a pin tip without a parallel wire."""

import math

import pytest

from schem2net import geometry
from schem2net.nets import Netlister, _under_label
from schem2net.scene import Label, Scene
from schem2net.symbols import Pin, Symbol


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
@pytest.mark.parametrize("end", [10, 20])
@pytest.mark.parametrize("body_side", [-1, 1])
def test_a_label_can_name_a_perpendicular_pin_tip(angle, end, body_side):
    c, s = round(math.cos(math.radians(angle))), round(math.sin(math.radians(angle)))

    def turn(x, y):
        return (c * x + s * y, -s * x + c * y)

    scene, parts = Scene(page=1), []
    for k in range(2):
        x = 40 * k
        box = geometry.bbox_of([turn(x + a, b) for a in (10, 20) for b in (10, 11.27)])
        scene.labels.append(Label("SDA", "local", box, angle))
        line = (turn(x + end, 11.5 + 2 * body_side), turn(x + end, 11.5))
        parts.append(
            Symbol([], geometry.bbox_of(line), [Pin(k, line, "1", "read")], ref=f"J{k + 1}")
        )
    reader = Netlister()
    reader.add_page(scene, parts)
    result = reader.result()
    assert [net.pins for net in result.nets] == [[("J1", "1"), ("J2", "1")]]
    assert not any(issue.kind == "unattached_label" for issue in result.issues)


def _target(lines, wires=()):
    label = Label("SDA", "local", (10, 10, 20, 11.27), 0)
    pin_index, wire_index = geometry.GridIndex(), geometry.GridIndex()
    pins = [(line, ("p", 1, k)) for k, line in enumerate(lines)]
    for k, line in enumerate(lines):
        pin_index.add(k, geometry.bbox_of(line))
    for k, wire in enumerate(wires):
        wire_index.add(k, geometry.bbox_of(wire))
    return _under_label(label, wires, wire_index, pins, pin_index, ("w", 1))


@pytest.mark.parametrize(
    "lines",
    [
        [((10, 11.5), (10, 14))],  # the body end sits by the label, not the tip
        [((10, 9), (10, 14))],  # a pin crosses the label baseline
        [((15, 14), (15, 11.5))],  # under the middle of the text
        [((10, 14), (10, 12))],  # too far below the baseline
        [((10, 8), (10, 10.9))],  # on the other side of the baseline
        [((8, 9.5), (10, 11.5))],  # a slanted stroke, not a perpendicular pin
        [((10, 14), (10, 11.5)), ((10.3, 14), (10.3, 11.5))],  # ambiguous tips
    ],
)
def test_a_nearby_pin_does_not_establish_an_ambiguous_or_interior_connection(lines):
    assert _target(lines) is None


def test_an_existing_parallel_wire_match_keeps_priority():
    pins = [((10, 14), (10, 11.5))]
    assert _target(pins, [((9, 11.8), (21, 11.8))]) == ("w", 1, 0)
