"""Run the extraction stages on one PDF."""

import hashlib
from pathlib import Path

from schem2net import ingest, pdf, profile, scene, symbols
from schem2net.ir import Design, Issue, Source
from schem2net.nets import Netlister

PROFILES = {"kicad"}


def extract(file: str | Path) -> Design:
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
    if generator not in PROFILES:
        design.issues.append(Issue(kind="no_profile", severity="error"))
        return design

    rules = profile.load(generator)
    netlister = Netlister()
    for page in doc.pages:
        kind = ingest.page_kind(page)
        if kind != "vector":
            design.issues.append(Issue(kind=f"{kind}_page", page=page.number))
            continue
        page_scene = scene.build(page, rules)
        netlister.add_page(page_scene, symbols.find(page_scene, rules))

    components, nets, issues = netlister.result()
    design.components = components
    design.nets = nets
    design.issues += issues
    return design
