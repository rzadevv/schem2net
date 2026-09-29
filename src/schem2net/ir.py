"""Intermediate representation shared by extraction, export and scoring."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "schem2net/ir@0.1"

PinRef = tuple[str, str]  # (refdes, pin number), the same key KiCad netlists use


class Source(BaseModel):
    file: str
    sha256: str | None = None
    generator: str = "unknown"
    pages: int = 0


class Pin(BaseModel):
    num: str
    name: str | None = None
    at: tuple[float, float] | None = None


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


class Design(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(SCHEMA, alias="schema")
    source: Source
    components: list[Component] = []
    nets: list[Net] = []
    issues: list[Issue] = []

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(by_alias=True, exclude_none=True, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        return cls.model_validate_json(Path(path).read_text())
