import pytest

from schem2net import ingest, pipeline
from schem2net.primitives import Document, Page, Path, Text


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"Creator": "Eeschema-PDF", "Producer": "KiCad PDF"}, "kicad"),
        ({"Creator": "Altium Designer"}, "altium"),
        ({"Creator": "OrCAD Capture CIS", "Producer": "Acrobat Distiller"}, "orcad"),
        ({"Producer": "Acrobat Distiller 10.0"}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_detect_generator(metadata, expected):
    assert ingest.detect_generator(Document(pages=[], metadata=metadata)) == expected


def test_page_kind():
    assert ingest.page_kind(Page(number=1, width=1, height=1)) == "empty"
    assert ingest.page_kind(Page(number=1, width=1, height=1, images=1)) == "raster"


def page_with(paths: int, texts: int) -> Page:
    page = Page(number=1, width=100, height=100)
    page.paths = [Path(i, [[(0, i), (10, i)]], 0.2, (0, 0, 0), None) for i in range(paths)]
    page.texts = [Text(i, "R1", (0, i, 2, i + 1), 1.0, 0.0, (0, 0, 0)) for i in range(texts)]
    return page


def test_board_prints_and_tables_are_not_schematics():
    assert ingest.page_kind(page_with(400, 200)) == "vector"
    assert ingest.page_kind(page_with(5000, 10)) == "board"
    assert ingest.page_kind(page_with(50, 1000)) == "table"


def test_region():
    region = pipeline.Region.parse("2:150,100,10,20")
    assert region.page == 2 and region.box == (10, 20, 150, 100)
    assert region.holds((15, 25, 40, 30))
    assert not region.holds((5, 25, 40, 30))
