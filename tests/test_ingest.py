import pytest

from schem2net import ingest
from schem2net.primitives import Document, Page


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
