"""Run the extraction stages on one PDF."""

import hashlib
from pathlib import Path

from schem2net import ingest, pdf
from schem2net.ir import Design, Issue, Source


def extract(file: str | Path) -> Design:
    file = Path(file)
    doc = pdf.read(file)
    design = Design(
        source=Source(
            file=file.name,
            sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            generator=ingest.detect_generator(doc),
            pages=len(doc.pages),
        )
    )
    for page in doc.pages:
        kind = ingest.page_kind(page)
        if kind != "vector":
            design.issues.append(Issue(kind=f"{kind}_page", page=page.number))

    # Stages 3-8 (geometry, wires, symbols, labels, nets) are not implemented yet.
    return design
