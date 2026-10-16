"""Geometry helpers and a uniform-grid spatial index."""

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator

from schem2net.primitives import BBox, Point

Segment = tuple[Point, Point]


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def distance_to_segment(p: Point, seg: Segment) -> float:
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return distance(p, seg[0])
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return distance(p, (ax + t * dx, ay + t * dy))


def is_interior(p: Point, seg: Segment, tol: float) -> bool:
    """True if p lies on the segment but not at either end."""
    return (
        distance_to_segment(p, seg) <= tol
        and distance(p, seg[0]) > tol
        and distance(p, seg[1]) > tol
    )


def in_polygon(p: Point, points: list[Point]) -> bool:
    inside = False
    for (ax, ay), (bx, by) in segments(points + points[:1]):
        if (ay > p[1]) != (by > p[1]) and p[0] < ax + (p[1] - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def unit(a: Point, b: Point) -> Point:
    length = distance(a, b)
    if length == 0:
        return 0.0, 0.0
    return (b[0] - a[0]) / length, (b[1] - a[1]) / length


def is_axis_aligned(seg: Segment, tol: float = 1e-3) -> bool:
    (ax, ay), (bx, by) = seg
    return abs(ax - bx) <= tol or abs(ay - by) <= tol


def is_horizontal(seg: Segment, tol: float = 1e-3) -> bool:
    return abs(seg[0][1] - seg[1][1]) <= tol


def segments(points: list[Point]) -> Iterator[Segment]:
    yield from zip(points, points[1:], strict=False)


def bbox_of(points: Iterable[Point]) -> BBox:
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def union_bbox(a: BBox, b: BBox) -> BBox:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def bbox_gap(a: BBox, b: BBox) -> float:
    """Distance between two boxes; 0 if they overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def center(box: BBox) -> Point:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


class GridIndex:
    """Buckets integer ids by the grid cells their boxes cover."""

    # Boxes over more cells than this, such as a line a broken file runs kilometres off
    # its page, are kept with their span of cells rather than in each cell.
    WIDE = 100_000

    def __init__(self, cell: float = 2.54):
        self.cell = cell
        self._cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        self._wide: list[tuple[int, tuple[int, int, int, int]]] = []

    def add(self, item: int, box: BBox) -> None:
        span = self._span(box)
        if _cells(span) > self.WIDE:
            self._wide.append((item, span))
            return
        for key in _keys(span):
            self._cells[key].append(item)

    def near(self, p: Point, radius: float) -> set[int]:
        box = (p[0] - radius, p[1] - radius, p[0] + radius, p[1] + radius)
        return self.within(box)

    def within(self, box: BBox) -> set[int]:
        x0, y0, x1, y1 = span = self._span(box)
        found = {
            item for item, (a, b, c, d) in self._wide if a <= x1 and x0 <= c and b <= y1 and y0 <= d
        }
        keys = _keys(span)
        if _cells(span) > max(self.WIDE, len(self._cells)):
            keys = [(i, j) for i, j in self._cells if x0 <= i <= x1 and y0 <= j <= y1]
        for key in keys:
            found.update(self._cells.get(key, ()))
        return found

    def _span(self, box: BBox) -> tuple[int, int, int, int]:
        return tuple(math.floor(v / self.cell) for v in box)


def _cells(span: tuple[int, int, int, int]) -> int:
    return max(span[2] - span[0] + 1, 0) * max(span[3] - span[1] + 1, 0)


def _keys(span: tuple[int, int, int, int]) -> Iterator[tuple[int, int]]:
    for i in range(span[0], span[2] + 1):
        for j in range(span[1], span[3] + 1):
            yield i, j


class UnionFind:
    def __init__(self):
        self._parent: dict = {}

    def find(self, x):
        root = x
        while (parent := self._parent.setdefault(root, root)) != root:
            root = parent
        while x != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> dict:
        out = defaultdict(list)
        for x in list(self._parent):
            out[self.find(x)].append(x)
        return out
