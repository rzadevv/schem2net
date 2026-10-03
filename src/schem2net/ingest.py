"""Stage 1: identify the generator and the kind of each page."""

from collections import Counter
from dataclasses import replace
from typing import Literal

from schem2net.primitives import Document, Page

# Matched against the PDF Creator and Producer fields, lower-cased.
SIGNATURES = {
    "kicad": ("kicad", "eeschema"),
    "altium": ("altium", "llpdflib"),  # llPDFLib is the PDF engine inside Altium
    "orcad": ("orcad", "capture cis", "cadence"),
    "eagle": ("eagle",),
    "easyeda": ("jspdf",),  # EasyEDA exports its schematics through jsPDF
}

SNAP = 3  # colour steps a printer may shift an ink by
PATH_ROLES = ("wire", "bus", "symbol", "pin", "hier_label", "sheet_pin", "note")
TEXT_ROLES = (
    "field", "pin_number", "designator", "local_label", "global_label", "hier_label", "bus", "note",
)  # fmt: skip
GUESS_SHARE = 0.6  # share of the ink a profile's colours must cover to be taken
GUESS_WIRES = 10  # paths in the wire colour needed besides
MIN_WIRES = 30  # wire-coloured lines that make a sparse page a schematic
MIN_TEXTS = 50  # with this many texts

PageKind = Literal["vector", "raster", "empty", "board", "table"]

# Schematic pages carry roughly one text per one to three paths. Board prints
# draw their lettering as strokes, so they have almost no text; parts lists and
# other tables are almost all text.
BOARD_TEXT_RATIO = 0.1
TABLE_TEXT_RATIO = 5.0


def detect_generator(doc: Document) -> str:
    producer = " ".join(doc.metadata.get(k, "") for k in ("Creator", "Producer")).lower()
    for name, needles in SIGNATURES.items():
        if any(needle in producer for needle in needles):
            return name
    # Eagle schematics printed through a PDF printer keep only the file name.
    if doc.metadata.get("Title", "").lower().endswith(".sch"):
        return "eagle"
    return "unknown"


def guess_by_colour(doc: Document, profiles: dict) -> str | None:
    """The generator whose colours the drawing is in, for a PDF that does not say who
    made it, such as one printed from a browser: the profile whose wire colour is
    there and whose colours, give or take a printer's rounding, cover most of the ink."""
    inks = Counter(
        p.stroke or p.fill for page in doc.pages for p in page.paths if p.stroke or p.fill
    )
    total = sum(inks.values())
    best, found = GUESS_SHARE, None
    for name, rules in profiles.items():
        known = set().union(*rules.colors.values())
        wires = sum(n for ink, n in inks.items() if _near(ink, rules.colors["wire"]))
        share = sum(n for ink, n in inks.items() if _near(ink, known)) / max(total, 1)
        if wires >= GUESS_WIRES and share > best:
            best, found = share, name
    return found


def snap_colours(page: Page, rules) -> Page:
    """The page with each ink a printer shifted a little set back to the profile's own:
    lines to the colours of drawn roles, text to those of text roles."""

    def palette(roles):
        return set().union(*(rules.colors.get(r, frozenset()) for r in roles))

    lines, words = palette(PATH_ROLES), palette(TEXT_ROLES)

    def snapped(colour, known):
        if colour is None or colour in known:
            return colour
        near = [k for k in known if _distance(colour, k) <= SNAP]
        return min(near, key=lambda k: _distance(colour, k)) if near else colour

    paths = [
        replace(p, stroke=snapped(p.stroke, lines), fill=snapped(p.fill, lines)) for p in page.paths
    ]
    texts = [replace(t, color=snapped(t.color, words)) for t in page.texts]
    return replace(page, paths=paths, texts=texts)


def _near(colour, colours) -> bool:
    return any(_distance(colour, c) <= SNAP for c in colours)


def _distance(a, b) -> int:
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def has_wires(page: Page, rules) -> bool:
    """True if the page has wires in the generator's colour and text besides: a schematic,
    however dense its drawing. Board prints have neither."""
    wires = sum(
        1
        for p in page.paths
        if rules.is_("wire", p.stroke) and not p.fill and len(p.subpaths[0]) == 2
    )
    return wires >= MIN_WIRES and sum(t.visible for t in page.texts) >= MIN_TEXTS


def page_kind(page: Page, text_as_strokes: bool = False) -> PageKind:
    """With text drawn as strokes, text counts say nothing, so only empty and scanned
    pages are told apart."""
    texts = sum(t.visible for t in page.texts)
    if len(page.paths) >= 20 and text_as_strokes:
        return "vector"
    if len(page.paths) >= 20:
        ratio = texts / len(page.paths)
        if ratio < BOARD_TEXT_RATIO:
            return "board"
        if ratio > TABLE_TEXT_RATIO:
            return "table"
        return "vector"
    if page.images:
        return "raster"
    return "vector" if page.paths or page.texts else "empty"
