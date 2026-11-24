"""Preserve source inputs and replace output files atomically."""

import os
from pathlib import Path
from uuid import uuid4


class OutputError(OSError):
    """An output path would replace its source input."""


def protect_source(source: str | Path, output: str | Path) -> None:
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or (
        source.exists() and output.exists() and source.samefile(output)
    ):
        raise OutputError(f"{output}: refusing to overwrite input {source}")


def write_text(path: str | Path, text: str) -> None:
    """Write a complete UTF-8 file, cleaning up only our own temporary file on failure."""
    _write(path, text)


def write_bytes(path: str | Path, data: bytes) -> None:
    """Replace a file atomically, cleaning up only this writer's temporary file."""
    _write(path, data)


def _write(path: str | Path, data: str | bytes) -> None:
    path = Path(path)
    part = path.with_name(f".schem2net-{uuid4().hex}.part")
    stream = part.open("x", encoding="utf-8") if isinstance(data, str) else part.open("xb")
    try:
        with stream:
            stream.write(data)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
