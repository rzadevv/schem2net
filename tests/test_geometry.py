import pytest
from hypothesis import given
from hypothesis import strategies as st

from schem2net import geometry
from schem2net.geometry import GridIndex, UnionFind


def test_distance_to_segment():
    seg = ((0, 0), (10, 0))
    assert geometry.distance_to_segment((5, 3), seg) == pytest.approx(3)
    assert geometry.distance_to_segment((-4, 3), seg) == pytest.approx(5)
    assert geometry.is_interior((5, 0), seg, 0.01)
    assert not geometry.is_interior((10, 0), seg, 0.01)


def test_bbox_gap():
    assert geometry.bbox_gap((0, 0, 1, 1), (2, 0, 3, 1)) == pytest.approx(1)
    assert geometry.bbox_gap((0, 0, 2, 2), (1, 1, 3, 3)) == 0


def test_grid_index_finds_boxes_across_cells():
    index = GridIndex(cell=1.0)
    index.add(7, (0.5, 0.5, 3.5, 0.6))
    assert 7 in index.near((3.0, 0.5), 0.1)
    assert 7 not in index.near((10, 10), 0.1)


@given(st.lists(st.tuples(st.integers(0, 30), st.integers(0, 30)), max_size=60))
def test_union_find_matches_components(edges):
    uf = UnionFind()
    for a, b in edges:
        uf.union(a, b)
    for a, b in edges:
        assert uf.find(a) == uf.find(b)
    members = [x for group in uf.groups().values() for x in group]
    assert len(members) == len(set(members))
