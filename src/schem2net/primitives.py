"""Vector primitives read from a PDF page.

Coordinates are millimetres with the origin at the top-left corner of the page
as it is displayed, y pointing down.
"""

from dataclasses import dataclass, field

Point = tuple[float, float]
BBox = tuple[float, float, float, float]
Color = tuple[int, int, int]


@dataclass(slots=True)
class Path:
    id: int
    subpaths: list[list[Point]]
    width: float
    stroke: Color | None
    fill: Color | None
    curved: bool = False
    seq: int = 0  # position in the page's drawing order
    dashed: bool = False  # stroked with a dash pattern, as notes and frames are

    @property
    def bbox(self) -> BBox:
        xs = [x for sub in self.subpaths for x, _ in sub]
        ys = [y for sub in self.subpaths for _, y in sub]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(slots=True)
class Text:
    id: int
    text: str
    bbox: BBox
    size: float
    angle: float
    color: Color | None
    seq: int = 0
    visible: bool = True  # False for text drawn in invisible mode, such as search layers
    # How much shorter the text is drawn than it would be at full size: subscripts are
    # drawn small, but a generator places text by its width at full size.
    shrink: float = 0.0


@dataclass(slots=True)
class Page:
    number: int
    width: float
    height: float
    paths: list[Path] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    images: int = 0


@dataclass(slots=True)
class Document:
    pages: list[Page]
    metadata: dict[str, str]
