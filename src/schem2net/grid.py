"""Find the scale a page was printed at, from the grid its wires were drawn on.

Schematic editors snap wire ends to a grid, so on a page printed 1:1 their
coordinates are multiples of it, give or take an offset. A sheet printed to fit the
paper keeps that pattern at another spacing; the spacing whose phase best agrees
across all wire ends gives the scale, and the page is scaled back before it is read.

A grid also fits at every spacing that divides it, so a page is taken as 1:1 when
its ends fit any of the generator's usual grids as printed. Otherwise the scale
nearest 1:1 at which the standard grid fits is taken.
"""

from dataclasses import replace

import numpy as np

from schem2net.primitives import Page
from schem2net.profile import Profile

SCALES = np.arange(0.4, 1.6, 0.0005)  # scales tried
MIN_ENDS = 8  # distinct wire-end coordinates per axis, on average, for an estimate
MIN_AGREEMENT = 0.5  # how well the phases must agree at the chosen spacing
COARSER_AGREEMENT = 0.35  # the same, for a coarser grid nearer 1:1
PEAK = 0.005  # a peak is searched for this far either side of a scale
SAME = 0.005  # scales this close to 1 are taken as 1


def scale(page: Page, profile: Profile) -> float:
    """The page's scale against the source drawing, 1.0 when unsure."""
    if profile.page_scale:
        return profile.page_scale
    if not profile.wire_grids:
        return 1.0
    ends = [
        point
        for path in page.paths
        if profile.is_("wire", path.stroke)
        for sub in path.subpaths
        if len(sub) == 2  # lines only; some PDFs give them a fill, which they cannot show
        for point in sub
    ]
    xs = np.unique(np.round([x for x, _ in ends], 2))
    ys = np.unique(np.round([y for _, y in ends], 2))
    count = (len(xs) + len(ys)) / 2
    if count < MIN_ENDS or min(len(xs), len(ys)) < MIN_ENDS / 2:
        return 1.0
    # Few points agree with some spacing by chance; many cannot.
    enough = max(MIN_AGREEMENT, 2.5 / np.sqrt(count))
    one = int(np.argmin(np.abs(SCALES - 1.0)))
    for grid in profile.wire_grids:
        near_one = _around(one, _agreement(xs, grid), _agreement(ys, grid))
        if near_one >= enough:
            return 1.0
    grid = profile.wire_grids[0]
    agreement = (_agreement(xs, grid) + _agreement(ys, grid)) / 2
    best = int(np.argmax(agreement))
    if agreement[best] < enough:
        return 1.0
    found = float(SCALES[best])
    # The grid fits at a half, a third or a quarter of the true scale as well as at it;
    # a coarser fit, nearer 1:1, is the true one.
    for times in (4, 3, 2):
        near = np.flatnonzero(np.abs(SCALES - times * found) <= PEAK * times * found)
        if not len(near) or abs(np.log(times * found)) >= abs(np.log(found)):
            continue
        peak = near[np.argmax(agreement[near])]
        if agreement[peak] >= max(COARSER_AGREEMENT, 2 / np.sqrt(count)):
            found = float(SCALES[peak])
            break
    return 1.0 if abs(found - 1) < SAME else found


def _around(k: int, ax: np.ndarray, ay: np.ndarray) -> float:
    """The best agreement of both axes within a hair of scale k."""
    lo, hi = max(k - 2, 0), k + 3
    return float(((ax[lo:hi] + ay[lo:hi]) / 2).max())


def rescale(page: Page, factor: float) -> Page:
    """The page with every coordinate and size multiplied by factor."""

    def box(b):
        return tuple(v * factor for v in b)

    paths = [
        replace(
            p,
            subpaths=[[(x * factor, y * factor) for x, y in sub] for sub in p.subpaths],
            width=p.width * factor,
        )
        for p in page.paths
    ]
    texts = [replace(t, bbox=box(t.bbox), size=t.size * factor) for t in page.texts]
    return replace(
        page, width=page.width * factor, height=page.height * factor, paths=paths, texts=texts
    )


def _agreement(values: np.ndarray, grid: float) -> np.ndarray:
    """For each scale, how closely the values fall on one grid of that spacing (0 to 1)."""
    if not len(values):
        return np.zeros(len(SCALES))
    phases = 2 * np.pi * values[None, :] / (grid * SCALES[:, None])
    return np.abs(np.exp(1j * phases).mean(axis=1))
