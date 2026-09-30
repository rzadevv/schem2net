"""Run the extraction stages on one PDF."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from schem2net import bookmarks, ingest, pdf, profile, scene, symbols
from schem2net.ir import Design, Issue, Source
from schem2net.nets import Netlister
from schem2net.primitives import Page
from schem2net.scene import Scene
from schem2net.symbols import Symbol

PROFILES = {"kicad", "altium"}


@dataclass
class PageResult:
    page: Page
    scene: Scene | None = None  # None for pages that were not read
    symbols: list[Symbol] = field(default_factory=list)


@dataclass
class Extraction:
    """The design, plus what each stage saw, for reports and debugging."""

    design: Design
    pages: list[PageResult]
    wire_nets: dict[tuple[int, int], str] = field(default_factory=dict)


def extract(file: str | Path, embedded: bool = True) -> Design:
    return run(file, embedded).design


def run(file: str | Path, embedded: bool = True) -> Extraction:
    """Extract a design. With `embedded`, a netlist carried in the file is used as is."""
    file = Path(file)
    doc = pdf.read(file)
    generator = ingest.detect_generator(doc)
    design = Design(
        source=Source(
            file=file.name,
            sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            generator=generator,
            pages=len(doc.pages),
        )
    )
    pages = [PageResult(page) for page in doc.pages]
    carried = bookmarks.read(file, design.source) if embedded else None
    if carried:
        return Extraction(carried, pages)
    if generator not in PROFILES:
        design.issues.append(Issue(kind="no_profile", severity="error"))
        return Extraction(design, pages)

    rules = profile.load(generator)
    netlister = Netlister()
    for result in pages:
        kind = ingest.page_kind(result.page)
        if kind != "vector":
            design.issues.append(Issue(kind=f"{kind}_page", page=result.page.number))
            continue
        result.scene = scene.build(result.page, rules)
        result.symbols = symbols.find(result.scene, rules)
        netlister.add_page(result.scene, result.symbols)

    found = netlister.result()
    design.components = found.components
    design.nets = found.nets
    design.issues += found.issues
    return Extraction(design, pages, found.wire_nets)
