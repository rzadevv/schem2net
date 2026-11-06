"""Extraction for the desktop application, run in a process of its own so that it can be
stopped at any point. It writes only into the folder it is given:

    python -m schem2net.gui.worker FILE FOLDER [LIBRARY]

design.ir.json, report.html (as `schem2net report` writes it), review.json (the
report's review queue) and, when the drawing was read, kicad/ (as `schem2net
schematic` writes it). LIBRARY is a folder written by `schem2net index-library`. It
imports no Qt.
"""

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from schem2net import kicad_sch, pdf, pipeline, report


def run(file: Path, folder: Path, library: Path | None = None) -> None:
    extraction = pipeline.run(file, library_dir=library)
    design = extraction.design
    (folder / "report.html").write_text(
        report.render(extraction, report.pictures(file, extraction))
    )
    (folder / "review.json").write_text(json.dumps(report.review(design, extraction)))
    if design.components and any(result.scene for result in extraction.pages):
        kicad_sch.write(extraction, folder / "kicad", file.stem)
    design.save(folder / "design.ir.json")  # last: its presence marks a finished run


def _orphaned(parent: int, folder: Path) -> None:
    """Stop, removing what was written, once the application that started this has gone
    without stopping it, as when it is killed."""
    while os.getppid() == parent:
        time.sleep(1)
    shutil.rmtree(folder, ignore_errors=True)
    os._exit(1)


def main() -> None:
    file, folder = Path(sys.argv[1]), Path(sys.argv[2])
    library = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    threading.Thread(target=_orphaned, args=(os.getppid(), folder), daemon=True).start()
    try:
        run(file, folder, library)
    except pdf.InputError as e:
        sys.exit(str(e))
    except FileNotFoundError as e:
        sys.exit(f"{e.filename or e}: no such file")
    except OSError as e:
        sys.exit(f"{e.filename or file}: {e.strerror or e}")


if __name__ == "__main__":
    main()
