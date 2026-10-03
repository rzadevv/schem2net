"""Stage 1: identify the generator and the kind of each page."""

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
