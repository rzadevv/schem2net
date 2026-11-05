"""Extraction for the desktop application, run in a process of its own so that it can be
stopped at any point. It writes only into the folder it is given:

    python -m schem2net.gui.worker FILE FOLDER

design.ir.json, report.html (as `schem2net report` writes it), review.json (the
report's review queue) and, when the drawing was read, kicad/ (as `schem2net
schematic` writes it). It imports no Qt.
"""

import json
import os
import sys
from pathlib import Path

from schem2net import kicad_sch, pdf, pipeline, report


def run(file: Path, folder: Path) -> None:
    library = os.environ.get("SCHEM2NET_LIBRARY")  # read as the command line reads it
    extraction = pipeline.run(file, library_dir=Path(library) if library else None)
    design = extraction.design
    (folder / "report.html").write_text(
        report.render(extraction, report.pictures(file, extraction))
    )
    (folder / "review.json").write_text(json.dumps(report.review(design, extraction)))
    if design.components and any(result.scene for result in extraction.pages):
        kicad_sch.write(extraction, folder / "kicad", file.stem)
    design.save(folder / "design.ir.json")  # last: its presence marks a finished run


def main() -> None:
    try:
        run(Path(sys.argv[1]), Path(sys.argv[2]))
    except pdf.InputError as e:
        sys.exit(str(e))
    except FileNotFoundError as e:
        sys.exit(f"{e.filename or e}: no such file")
    except OSError as e:
        sys.exit(f"{e.filename or sys.argv[1]}: {e.strerror or e}")


if __name__ == "__main__":
    main()
