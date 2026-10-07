"""Run the extraction stages on one PDF."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from schem2net import (
    bookmarks,
    fields,
    grid,
    ingest,
    library,
    pdf,
    profile,
    roles,
    scene,
    strokes,
    symbols,
)
from schem2net.ir import Design, Issue, Source
from schem2net.nets import Netlister
from schem2net.primitives import Page
from schem2net.scene import Scene
from schem2net.symbols import Symbol

PROFILES = {"kicad", "altium", "eagle", "easyeda", "orcad"}


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


@dataclass(frozen=True)
class Region:
    """Part of one page, in millimetres from its top-left corner."""

    page: int
    box: tuple[float, float, float, float]

    @classmethod
    def parse(cls, text: str) -> "Region":
        """From "PAGE:X0,Y0,X1,Y1", for example "2:10,20,150,100"."""
        page, _, box = text.partition(":")
        x0, y0, x1, y1 = (float(v) for v in box.split(","))
        return cls(int(page), (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def holds(self, box: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = self.box
        return x0 <= box[0] and y0 <= box[1] and box[2] <= x1 and box[3] <= y1


def extract(file: str | Path, embedded: bool = True, region: Region | None = None) -> Design:
    return run(file, embedded, region).design


def _producer(doc) -> str:
    """What the PDF says made it, for a message: its creator or producer."""
    return " / ".join(v for k in ("Creator", "Producer") if (v := doc.metadata.get(k, "").strip()))


def _read(result: PageResult, rules: profile.Profile, pages: int) -> None:
    """The page's scene and symbols."""
    result.scene = scene.build(result.page, rules)
    if rules.labels_show_sheet:
        scene.drop_sheet_references(result.scene, pages)
    result.symbols = symbols.find(result.scene, rules)


def run(file: str | Path, embedded: bool = True, region: Region | None = None) -> Extraction:
    """Extract a design. With `embedded`, a netlist carried in the file is used as is.

    With a region, only what lies wholly inside it is read, from the drawing.
    """
    file = Path(file)
    doc = pdf.read(file)
    if region:
        page = doc.pages[region.page - 1]
        page.paths = [p for p in page.paths if region.holds(p.bbox)]
        page.texts = [t for t in page.texts if region.holds(t.bbox)]
        doc.pages = [page]
        embedded = False
    generator = ingest.detect_generator(doc)
    printed = False  # through a browser or a PDF printer, which do not say who drew it
    if generator not in PROFILES and generator != "orcad":
        guessed = ingest.guess_by_colour(doc, {name: profile.load(name) for name in PROFILES})
        if guessed:
            generator, printed = guessed, True
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
        made = generator if generator != "unknown" else _producer(doc) or "an unknown tool"
        design.issues.append(Issue(kind="no_profile", severity="error", detail=made))
        return Extraction(design, pages)

    rules = profile.load(generator)
    netlister = Netlister(rules.labels_span_pages, rules.colors.get("designator", frozenset()))
    for result in pages:
        if printed:
            result.page = ingest.snap_colours(result.page, rules)
        if rules.lines_in_pieces:
            result.page = ingest.joined_lines(result.page, rules)
        result.page = strokes.traced(result.page)
        # Text drawn as strokes leaves a page with almost no text objects, like a board.
        kind = ingest.page_kind(result.page, text_as_strokes=bool(region or rules.text_font))
        if kind == "board" and ingest.has_wires(result.page, rules):
            kind = "vector"  # a dense schematic, with few texts for its drawing
        if kind != "vector":
            design.issues.append(Issue(kind=f"{kind}_page", page=result.page.number))
            continue
        if roles.colourless(result.page):  # printed in black: roles from shapes
            result.page = roles.recolour(result.page, rules)
        else:  # texts in colours of the designer's own: roles from what they sit on
            result.page = roles.name_unknown_texts(result.page, rules)
        factor = grid.scale(result.page, rules, exported=not printed)
        if factor != 1.0:  # printed to fit the paper: read it at the size it was drawn
            result.page = grid.rescale(result.page, 1 / factor)
        _read(result, rules, len(doc.pages))
        if printed and (pitch := grid.pitch_factor(result.symbols)) != 1.0:
            # A wire grid fits at half the true scale too; the pins' pitch tells which.
            result.page = grid.rescale(result.page, 1 / pitch)
            _read(result, rules, len(doc.pages))

    read = [result for result in pages if result.scene is not None]
    fields.whole_names([result.symbols for result in read])
    if rules.pin_library:
        parts = library.load(rules.pin_library)
        for result in read:
            by_name = rules.pin_library in library.BY_NAME
            library.resolve(result.symbols, parts, by_name, result.scene.fields)
    for result in read:
        netlister.add_page(result.scene, result.symbols)
    found = netlister.result()
    design.components = found.components
    design.nets = found.nets
    design.issues += found.issues
    return Extraction(design, pages, found.wire_nets)
