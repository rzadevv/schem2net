"""Run the extraction stages on one PDF."""

import hashlib
from dataclasses import dataclass, field, replace
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
from schem2net.ir import Design, Issue, Source, unnumbered
from schem2net.nets import Netlister
from schem2net.primitives import Document, Page
from schem2net.scene import Scene, name_key
from schem2net.symbols import Symbol

PROFILES = {"kicad", "altium", "eagle", "easyeda", "orcad"}
BLACK, WHITE = (0, 0, 0), (255, 255, 255)


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
        if int(page) < 1:
            raise ValueError("pages are numbered from 1")
        return cls(int(page), (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def holds(self, box: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = self.box
        return x0 <= box[0] and y0 <= box[1] and box[2] <= x1 and box[3] <= y1


def extract(file: str | Path, embedded: bool = True, region: Region | None = None) -> Design:
    return run(file, embedded, region).design


def _sha256(file: Path) -> str:
    with file.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


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
        if region.page > len(doc.pages):
            raise pdf.InputError(f"{file}: no page {region.page}; it has {len(doc.pages)}")
        page = doc.pages[region.page - 1]
        page.paths = [p for p in page.paths if region.holds(p.bbox)]
        page.texts = [t for t in page.texts if region.holds(t.bbox)]
        doc.pages = [page]
        embedded = False
    generator = ingest.detect_generator(doc)
    printed = False  # through a browser or a PDF printer, which do not say who drew it
    if generator not in PROFILES:
        guessed = ingest.guess_by_colour(doc, {name: profile.load(name) for name in PROFILES})
        if guessed:
            generator, printed = guessed, True
    design = Design(
        source=Source(
            file=file.name,
            sha256=_sha256(file),
            generator=generator,
            pages=len(doc.pages),
        )
    )
    pages = [PageResult(page) for page in doc.pages]
    carried = bookmarks.read(file, design.source) if embedded else None
    if carried:
        return Extraction(carried, pages)
    if generator not in PROFILES:
        read = _read_as_any(doc, design, region)
        if read:
            return read
        made = generator if generator != "unknown" else _producer(doc) or "an unknown tool"
        design.issues.append(Issue(kind="no_profile", severity="error", detail=made))
        return Extraction(design, pages)
    return _extract(doc, design, generator, printed, region)


def _read_as_any(doc, design: Design, region: Region | None) -> Extraction | None:
    """A PDF that says nothing of what drew it, in colours no profile knows, such as one
    printed in black: its ink taken as black, read as each generator whose roles were
    learned, keeping the reading that joins the most pins. None if none joins any."""
    black = Document(pages=[_in_black(page) for page in doc.pages], metadata=doc.metadata)
    best, most = None, 0
    for generator in sorted(PROFILES):
        if not roles.learned(generator):
            continue
        trial = _extract(black, design.model_copy(deep=True), generator, True, region)
        # Pins known by their numbers: a wrong generator's reading finds few of those.
        known = [[p for p in net.pins if not unnumbered(p[1])] for net in trial.design.nets]
        joined = sum(len(pins) for pins in known if len(pins) >= 2)
        # It also leaves designators naming parts it did not find: each costs the pins
        # such a part has, on average, in that reading.
        parts = trial.design.components
        per_part = sum(len(c.pins) for c in parts) / max(len(parts), 1)
        lost = sum(i.kind == "designator_without_part" for i in trial.design.issues)
        joined -= per_part * lost
        if joined > most:
            best, most = trial, joined
    if best:
        best.design.issues.append(
            Issue(kind="generator_guessed", detail=best.design.source.generator)
        )
    return best


def _in_black(page: Page) -> Page:
    """The page with every ink but white made black, as a printer without colour would."""

    def ink(colour):
        return colour if colour in (None, WHITE) else BLACK

    paths = [replace(p, stroke=ink(p.stroke), fill=ink(p.fill)) for p in page.paths]
    texts = [replace(t, color=ink(t.color)) for t in page.texts]
    return replace(page, paths=paths, texts=texts)


def _extract(
    doc, design: Design, generator: str, printed: bool, region: Region | None
) -> Extraction:
    """Read every page with the generator's profile."""
    design.source.generator = generator
    pages = [PageResult(page) for page in doc.pages]
    rules = profile.load(generator)
    netlister = Netlister(rules.labels_span_pages, rules.colors.get("designator", frozenset()))
    for result in pages:
        try:
            _read_page(result, design, rules, printed, region, len(doc.pages))
        except Exception as e:  # one page the reader trips on: the others are still read
            result.scene, result.symbols = None, []
            detail = f"{type(e).__name__}: {e}"
            design.issues.append(
                Issue(kind="page_failed", severity="error", page=result.page.number, detail=detail)
            )

    read = [result for result in pages if result.scene is not None]
    _name_sheets([result.scene for result in read])
    fields.whole_names([result.symbols for result in read])
    if rules.pin_library:
        parts = library.load(rules.pin_library)
        design.source.library = library.fingerprint(rules.pin_library)
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


def _read_page(
    result: PageResult,
    design: Design,
    rules: profile.Profile,
    printed: bool,
    region: Region | None,
    pages: int,
) -> None:
    """One page's scene and symbols, read with the generator's profile."""
    if printed:
        result.page = ingest.snap_colours(result.page, rules)
    result.page = strokes.traced(result.page)
    # Text drawn as strokes leaves a page with almost no text objects, like a board.
    kind = ingest.page_kind(result.page, text_as_strokes=bool(region or rules.text_font))
    if kind == "board" and ingest.has_wires(result.page, rules):
        kind = "vector"  # a dense schematic, with few texts for its drawing
    if kind != "vector":
        design.issues.append(Issue(kind=f"{kind}_page", page=result.page.number))
        return
    page_rules = rules
    if roles.colourless(result.page):  # printed in black: roles from shapes
        result.page = roles.recolour(result.page, rules)
        # Designators and the texts beside them are told apart by colour no more.
        page_rules = replace(rules, colors={**rules.colors, "designator": frozenset()})
    else:  # texts in colours of the designer's own: roles from what they sit on
        result.page = roles.name_unknown_texts(result.page, rules)
    if rules.lines_in_pieces:  # once roles are known, as the models see lines apart
        result.page = ingest.joined_lines(result.page, rules)
    factor = grid.scale(result.page, rules, exported=not printed)
    if factor != 1.0:  # printed to fit the paper: read it at the size it was drawn
        result.page = grid.rescale(result.page, 1 / factor)
    _read(result, page_rules, pages)
    if printed and (pitch := grid.pitch_factor(result.symbols)) != 1.0:
        # A wire grid fits at half the true scale too; the pins' pitch tells which.
        result.page = grid.rescale(result.page, 1 / pitch)
        _read(result, page_rules, pages)


def _name_sheets(scenes: list[Scene]) -> None:
    """Name each sheet whose name is not printed after the child page it stands for:
    of the pages one level below its own, the one whose hierarchical labels share most
    names with its pins."""
    labels = {
        page.path: {name_key(lb.text) for lb in page.labels if lb.kind == "hier"}
        for page in scenes
        if page.path
    }
    for page in scenes:
        named = {name_key(sheet.name) for sheet in page.sheets if sheet.name}
        for sheet in page.sheets:
            if sheet.name or not page.path:
                continue
            pins = {name_key(pin.name) for pin in sheet.pins}
            children = [
                (len(pins & names), path[len(page.path) : -1])
                for path, names in labels.items()
                if path.startswith(page.path) and path.count("/") == page.path.count("/") + 1
            ]
            shared, child = max(children, default=(0, ""))
            if shared and name_key(child) not in named:
                sheet.name = child
                named.add(name_key(child))
