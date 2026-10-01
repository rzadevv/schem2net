"""The scale a page was printed at, from its wire grid."""

import random

import pytest

from schem2net import grid, profile
from schem2net.primitives import Page, Path

WIRE = (13, 171, 118)


def _page(factor: float, steps: float = 1.0) -> Page:
    """Wires between random points of a 2.54 mm grid (or a finer one), printed at factor."""
    rng = random.Random(1)
    paths = []
    for k in range(60):
        x = rng.randrange(10, 120) * 2.54 * steps
        y = rng.randrange(10, 80) * 2.54 * steps
        end = (x + rng.randrange(1, 8) * 2.54, y) if k % 2 else (x, y + rng.randrange(1, 8) * 2.54)
        points = [(7 + x * factor, 5 + y * factor), (7 + end[0] * factor, 5 + end[1] * factor)]
        paths.append(Path(k, [points], 0.15 * factor, WIRE, None, seq=k))
    return Page(1, 279.4, 215.9, paths=paths)


@pytest.mark.parametrize("factor", [1.0, 0.63, 1.085])
def test_scale_is_found(factor):
    assert grid.scale(_page(factor), profile.load("eagle")) == pytest.approx(factor, abs=0.002)


def test_half_grid_is_not_half_scale():
    page = _page(1.0, steps=0.5)  # most ends on the 1.27 mm half grid
    page.paths += _page(1.0).paths
    assert grid.scale(page, profile.load("eagle")) == 1.0


def test_rescale():
    page = grid.rescale(_page(0.5), 2.0)
    assert page.width == pytest.approx(558.8)
    assert page.paths[0].width == pytest.approx(0.15)
