"""Intermediate representation shared by extraction, export and scoring."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from schem2net.files import write_text

SCHEMA = "schem2net/ir@0.1"
LOW_CONFIDENCE = 0.8  # nets below this deserve a look
# A pin drawn with no number readable is kept under a number of this form, ?1, ?2 and so
# on within its part: the drawing shows what it connects to, though not which pad it is.
UNNUMBERED = "?"

PinRef = tuple[str, str]  # (refdes, pin number), the same key KiCad netlists use


class InputError(ValueError):
    """An external JSON design cannot be read or has inconsistent object links."""


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
    confidence: float = Field(1.0, ge=0.0, le=1.0)
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

    schema_: Literal["schem2net/ir@0.1"] = Field(SCHEMA, alias="schema")
    source: Source
    components: list[Component] = []
    nets: list[Net] = []
    issues: list[Issue] = []

    def save(self, path: str | Path) -> None:
        """Write the whole file or nothing: a failed run leaves an earlier one as it was."""
        write_text(path, self.model_dump_json(by_alias=True, exclude_none=True, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        """Read external IR, checking the links needed for review and export."""
        try:
            design = cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except ValidationError as exc:
            error = exc.errors(include_input=False)[0]
            field = ".".join(map(str, error["loc"])) or "JSON"
            raise InputError(f"{path}: invalid design JSON ({field}: {error['msg']})") from None
        except UnicodeError:
            raise InputError(f"{path}: invalid design JSON (expected UTF-8 text)") from None

        refs = {comp.ref for comp in design.components}
        if len(refs) != len(design.components) or any(not ref.strip() for ref in refs):
            raise InputError(f"{path}: component references must be nonempty and unique")
        ids = {net.id for net in design.nets}
        if len(ids) != len(design.nets) or any(not key.strip() for key in ids):
            raise InputError(f"{path}: net IDs must be nonempty and unique")
        missing = {ref for net in design.nets for ref, _ in net.pins} - refs
        if missing:
            raise InputError(
                f"{path}: nets reference unknown components: {', '.join(sorted(missing))}"
            )
        if any(issue.net is not None and issue.net not in ids for issue in design.issues):
            raise InputError(f"{path}: issues reference unknown nets")
        return design
