import pytest

from schem2net import ingest, pipeline, profile
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


def test_a_printed_page_is_known_by_its_colours():
    """A schematic printed from a browser says nothing of who drew it; its inks do."""
    from schem2net import ingest, profile
    from schem2net.primitives import Document, Page, Path

    shifted = [(0, 136, 0)] * 12 + [(136, 0, 0)] * 20 + [(1, 1, 1)] * 5  # off by a step
    page = Page(1, 210, 297)
    page.paths = [Path(k, [[(k, 0), (k, 5)]], 0.2, c, None, seq=k) for k, c in enumerate(shifted)]
    doc = Document([page], {"Producer": "Skia/PDF m152"})
    profiles = {name: profile.load(name) for name in ("kicad", "altium", "eagle", "easyeda")}
    assert ingest.detect_generator(doc) == "unknown"
    assert ingest.guess_by_colour(doc, profiles) == "easyeda"

    snapped = ingest.snap_colours(page, profiles["easyeda"])
    assert profiles["easyeda"].is_("wire", snapped.paths[0].stroke)
    assert profiles["easyeda"].is_("symbol", snapped.paths[12].stroke)


def test_a_dense_schematic_is_not_a_board():
    """Few texts for many paths looks like a board print, unless the page has wires."""
    from schem2net import ingest, profile
    from schem2net.primitives import Page, Path, Text

    kicad = profile.load("kicad")
    page = Page(1, 420, 297)
    page.paths = [Path(k, [[(k, 0), (k, 1)]], 0.15, (132, 0, 0), None, seq=k) for k in range(900)]
    page.texts = [Text(k, f"R{k}", (k, 5, k + 1, 6), 1.27, 0.0, (0, 100, 100)) for k in range(60)]
    assert ingest.page_kind(page) == "board"
    assert not ingest.has_wires(page, kicad)
    page.paths += [
        Path(k, [[(k, 20), (k + 5, 20)]], 0.15, (0, 150, 0), None, seq=k) for k in range(40)
    ]
    assert ingest.has_wires(page, kicad)


def test_outlines_printed_line_by_line_are_joined():
    """OrCAD prints every outline one line at a time. A pin, drawn after its part's
    texts, and wires stay apart."""
    red, maroon = (255, 0, 0), (128, 0, 64)
    sides = [((0, 0), (5, 0)), ((5, 0), (5, 3)), ((5, 3), (0, 3)), ((0, 3), (0, 0))]
    paths = [Path(k, [list(side)], 0.2, red, None, seq=k) for k, side in enumerate(sides)]
    paths.append(Path(4, [[(0, 0), (-3, 0)]], 0.2, red, None, seq=6))
    paths.append(Path(5, [[(10, 0), (15, 0)]], 0.2, maroon, None, seq=7))
    paths.append(Path(6, [[(15, 0), (20, 0)]], 0.2, maroon, None, seq=8))
    page = ingest.joined_lines(Page(1, 100, 100, paths=paths), profile.load("orcad"))
    assert [len(p.subpaths[0]) for p in page.paths] == [5, 2, 2, 2]
    assert page.paths[0].subpaths[0][-1] == (0, 0)
