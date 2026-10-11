"""Intermediate representation shared by extraction, export and scoring."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "schem2net/ir@0.1"
LOW_CONFIDENCE = 0.8  # nets below this deserve a look
# A pin drawn with no number readable is kept under a number of this form, ?1, ?2 and so
# on within its part: the drawing shows what it connects to, though not which pad it is.
UNNUMBERED = "?"

PinRef = tuple[str, str]  # (refdes, pin number), the same key KiCad netlists use


class Source(BaseModel):
    file: str
    sha256: str | None = None
    generator: str = "unknown"
    pages: int = 0
    library: str | None = None  # the indexed part library read with, if any


class Pin(BaseModel):
    num: str
    name: str | None = None
    at: tuple[float, float] | None = None
    how: str | None = None  # how the number was found, where it was not printed beside it


def unnumbered(num: str) -> bool:
    """Whether a pin number stands in for one the drawing does not show."""
    return num.startswith(UNNUMBERED)


class Component(BaseModel):
    ref: str
    value: str | None = None
    symbol: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    units: list[str] = []
    pins: list[Pin] = []


class Evidence(BaseModel):
    type: str
    count: int = 1
    label: str | None = None


class Net(BaseModel):
    id: str
    name: str | None = None
    names_seen: list[str] = []
    pins: list[PinRef] = []
    confidence: float = 1.0
    evidence: list[Evidence] = []
    pages: list[int] = []


class Issue(BaseModel):
    kind: str
    severity: Literal["info", "warn", "error"] = "warn"
    net: str | None = None
    page: int | None = None
    at: tuple[float, float] | None = None
    pins: list[PinRef] = []  # the pins it puts in doubt
    detail: str | None = None  # what it is about, as a reader names it: R12, UART_TX, U3.5


class Design(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(SCHEMA, alias="schema")
    source: Source
    components: list[Component] = []
    nets: list[Net] = []
    issues: list[Issue] = []

    def save(self, path: str | Path) -> None:
        """Write the whole file or nothing: a failed run leaves an earlier one as it was."""
        path = Path(path)
        part = path.with_name(f".{path.name}.part")
        part.write_text(self.model_dump_json(by_alias=True, exclude_none=True, indent=2))
        os.replace(part, path)

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        return cls.model_validate_json(Path(path).read_text())
