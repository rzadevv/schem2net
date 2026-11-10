"""Read one design, or describe the reading environment, with any installed schem2net.

Run as a script by `evaluate`, with the interpreter of the extractor being read:
nothing here imports from the package at module level, so an older release that has
no evaluation tools of its own is read and probed exactly as the candidate is.

    python -P reader.py --environment [LIBRARY]
    python -P reader.py PDF PDF_SHA256 SEAL_SHA256 TARGET [LIBRARY]
"""

import hashlib
import json
import os
import platform
import re
import resource
import sys
import time
from importlib import metadata
from pathlib import Path

MEMORY = 4 * 1024**3  # bytes of address space a design may take
LEARNED = ("roles.npz", "designators.npz", "groups.npz", "eagle_font.json", "eagle_fills.json")
# Where PDFium looks for fonts to stand in for those a PDF does not embed, on Linux.
FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/X11/fonts")


def environment(library: str | None) -> dict:
    import schem2net
    from schem2net import profile

    profile.use_learned(None)
    package = Path(schem2net.__file__).parent
    code = hashlib.sha256()
    for f in sorted(package.rglob("*")):
        # The extractor's code: the bench tools that read and score it may change.
        parts = set(f.relative_to(package).parts)
        if f.suffix in (".py", ".toml") and not {"__pycache__", "bench"} & parts:
            code.update(f.relative_to(package).as_posix().encode() + f.read_bytes())
    files = {n: _digest(Path(str(profile.learned_file(n)))) for n in LEARNED}
    if library:
        files |= {f.name: _digest(f) for f in sorted(Path(library).glob("*")) if f.is_file()}
    # Text boxes of fonts a PDF does not embed depend on the stand-ins installed.
    fonts = sorted(
        f"{f} {f.stat().st_size}" for d in FONT_DIRS for f in Path(d).rglob("*") if f.is_file()
    )
    requires = [r for r in metadata.requires("schem2net") or [] if "extra ==" not in r]
    deps = sorted({re.match(r"[A-Za-z0-9_.-]+", r).group() for r in requires})
    import pypdfium2.version

    return {
        "schem2net": schem2net.__version__,
        "package": str(package),
        "code": code.hexdigest(),
        "embedded": False,
        "files": files,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "dependencies": {d: metadata.version(d) for d in deps},
        "pdfium": str(pypdfium2.version.PDFIUM_INFO),
        "fonts": {"count": len(fonts), "sha256": _hash("\n".join(fonts).encode())},
    }


def read(pdf: str, pdf_sha256: str, seal: str, target: str, library: str | None) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    from schem2net import pipeline, profile

    profile.use_learned(None)
    cpu, wall = time.process_time(), time.perf_counter()
    design = pipeline.extract(
        Path(pdf), embedded=False, library_dir=Path(library) if library else None
    )
    stats = {
        "seconds": round(time.perf_counter() - wall, 2),
        "cpu_seconds": round(time.process_time() - cpu, 2),
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
        "pages_failed": sum(i.kind == "page_failed" for i in design.issues),
    }
    prediction = design.model_dump(mode="json", by_alias=True)
    reading = {"pdf": pdf_sha256, "seal": seal, "stats": stats, "prediction": prediction}
    write(Path(target), reading)


def write(path: Path, value) -> None:
    """Write a file whole, once: a reading is never overwritten or left half written."""
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    part.write_text(json.dumps(value, indent=1) + "\n")
    try:
        os.link(part, path)  # fails if the file exists
    finally:
        part.unlink()


def _digest(path: Path) -> str:
    return _hash(path.read_bytes())


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    if sys.argv[1] == "--environment":
        print(json.dumps(environment(sys.argv[2] if len(sys.argv) > 2 else None)))
    else:
        read(*sys.argv[1:5], sys.argv[5] if len(sys.argv) > 5 else None)
