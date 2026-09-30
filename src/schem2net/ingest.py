"""Stage 1: identify the generator and the kind of each page."""

from typing import Literal

from schem2net.primitives import Document, Page

# Matched against the PDF Creator and Producer fields, lower-cased.
SIGNATURES = {
    "kicad": ("kicad", "eeschema"),
    "altium": ("altium", "llpdflib"),  # llPDFLib is the PDF engine inside Altium
    "orcad": ("orcad", "capture cis", "cadence"),
    "eagle": ("eagle",),
}

PageKind = Literal["vector", "raster", "empty"]


def detect_generator(doc: Document) -> str:
    producer = " ".join(doc.metadata.get(k, "") for k in ("Creator", "Producer")).lower()
    for name, needles in SIGNATURES.items():
        if any(needle in producer for needle in needles):
            return name
    return "unknown"


def page_kind(page: Page) -> PageKind:
    if len(page.paths) >= 20:
        return "vector"
    if page.images:
        return "raster"
    return "vector" if page.paths or page.texts else "empty"
