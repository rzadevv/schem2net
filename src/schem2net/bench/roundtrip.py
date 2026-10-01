"""Check the KiCad schematic export: does KiCad read back the extracted netlist?

Each design is written as a KiCad project, then kicad-cli (in the corpus image)
exports its netlist and runs ERC. The netlist is scored against the extraction,
so 1.0 means the schematic connects exactly as extracted.
"""

import json
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from schem2net import kicad, kicad_sch, pipeline
from schem2net.bench.corpus import IMAGE
from schem2net.bench.score import score


@dataclass
class RoundTrip:
    pin_accuracy: float | None  # None when KiCad could not read the project
    erc_errors: Counter = field(default_factory=Counter)


def check(file: Path, work: Path, image: str = IMAGE) -> RoundTrip:
    extraction = pipeline.run(file, embedded=False)
    shutil.rmtree(work, ignore_errors=True)
    kicad_sch.write(extraction, work, "design")
    _kicad_cli(image, work, "sch", "export", "netlist", "-o", "/w/out.net", "/w/design.kicad_sch")
    if not (work / "out.net").exists():
        return RoundTrip(None)
    metrics = score(kicad.read_netlist(work / "out.net"), extraction.design).metrics()
    _kicad_cli(
        image, work, "sch", "erc", "--format", "json", "-o", "/w/erc.json", "/w/design.kicad_sch"
    )
    errors = Counter()
    if (work / "erc.json").exists():
        report = json.loads((work / "erc.json").read_text())
        errors.update(
            v["type"]
            for sheet in report["sheets"]
            for v in sheet["violations"]
            if v["severity"] == "error"
        )
    return RoundTrip(metrics["pin_accuracy"], errors)


def _kicad_cli(image: str, work: Path, *args: str) -> None:
    user = f"{os.getuid()}:{os.getgid()}"
    mount = f"{work.resolve()}:/w"
    cmd = ["docker", "run", "--rm", "--user", user, "-v", mount, image, *args]
    subprocess.run(cmd, capture_output=True, text=True)
