"""Part libraries: the pins of each symbol, read from KiCad's symbol libraries.

A PDF often leaves pin numbers out. ICs are drawn with pin names and hidden numbers, and
pins stacked on one another, such as an FPGA's hundred ground balls under one drawn
pin, show one number at most. The symbol library has them all. KiCad's libraries are
indexed once (`schem2net index-library DIR`) into a file in the user's cache; a part
whose value names a symbol there is checked against the pins drawn before any number
is taken from it (see `resolve`).
"""

from __future__ import annotations

import gzip
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from schem2net import sexpr

if TYPE_CHECKING:
    from schem2net.symbols import Symbol


@dataclass(frozen=True, slots=True)
class LibPin:
    number: str
    name: str
    unit: int  # 0: drawn in every unit
    at: tuple[float, float]
    hidden: bool


Library = dict[str, list[tuple[str, list[LibPin]]]]  # value -> (lib:symbol, pins)


def index(root: Path) -> Library:
    """Every symbol of the KiCad libraries under root, by its name in lower case.

    Reads both layouts: a .kicad_sym file holding a whole library, and a .kicad_symdir
    directory holding one file per symbol.
    """
    out: Library = defaultdict(list)
    libraries: dict[str, list[Path]] = defaultdict(list)
    found = [
        Path(folder) / name
        for folder, _, names in os.walk(root, followlinks=True)
        for name in names
        if name.endswith(".kicad_sym")
    ]
    for path in sorted(found):
        lib = path.parent.stem if path.parent.suffix == ".kicad_symdir" else path.stem
        libraries[lib].append(path)
    for lib, paths in libraries.items():
        symbols: dict[str, sexpr.Node] = {}
        for path in paths:
            try:
                tree = sexpr.parse(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            for node in sexpr.children(tree, "symbol"):
                symbols[node[1]] = node
        for name in symbols:
            pins = _pins(name, symbols)
            if pins:
                out[name.lower()].append((f"{lib}:{name}", pins))
    return dict(out)


def _pins(name: str, symbols: dict[str, sexpr.Node], depth: int = 0) -> list[LibPin]:
    node = symbols[name]
    parent = sexpr.value(node, "extends")
    if parent is not None:  # a derived symbol is drawn as its parent
        return _pins(parent, symbols, depth + 1) if parent in symbols and depth < 8 else []
    pins = []
    for unit in sexpr.children(node, "symbol"):
        number, style = _unit(unit[1])
        if style == 2:  # the alternate body style draws the same pins again
            continue
        for pin in sexpr.children(unit, "pin"):
            at = sexpr.child(pin, "at")
            hide = sexpr.child(pin, "hide")
            pins.append(
                LibPin(
                    number=_text(pin, "number"),
                    name=_text(pin, "name"),
                    unit=number,
                    at=(round(float(at[1]), 2), round(float(at[2]), 2)) if at else (0.0, 0.0),
                    hidden="hide" in pin[1:] or (hide is not None and hide[1:] != ["no"]),
                )
            )
    return pins


def _unit(name: str) -> tuple[int, int]:
    """The unit and body style of a unit's drawing, from its name: SYMBOL_unit_style."""
    *_, unit, style = name.rsplit("_", 2)
    try:
        return int(unit), int(style)
    except ValueError:
        return 0, 1


def _text(pin: sexpr.Node, head: str) -> str:
    node = sexpr.child(pin, head)
    return node[1] if node and len(node) > 1 and isinstance(node[1], str) else ""


def save(library: Library, path: Path) -> None:
    rows = {
        key: [
            [symbol, [[p.number, p.name, p.unit, *p.at, p.hidden] for p in pins]]
            for symbol, pins in entries
        ]
        for key, entries in library.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f, separators=(",", ":"))


def default_path(kind: str = "kicad") -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "schem2net" / f"{kind}-symbols.json.gz"


@cache
def load(kind: str = "kicad") -> Library:
    """The indexed library of a kind, or an empty one where none was indexed."""
    path = default_path(kind)
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = json.load(f)
    return {
        key: [
            (symbol, [LibPin(n, nm, u, (x, y), h) for n, nm, u, x, y, h in pins])
            for symbol, pins in entries
        ]
        for key, entries in rows.items()
    }


# The eight ways a symbol can be turned and mirrored, as (a, b, c, d) in
# x' = a x + b y, y' = c x + d y. Libraries count y upwards, pages downwards.
ORIENTATIONS = (
    (1, 0, 0, -1),
    (0, 1, 1, 0),
    (-1, 0, 0, 1),
    (0, -1, -1, 0),
    (-1, 0, 0, -1),
    (0, -1, 1, 0),
    (1, 0, 0, 1),
    (0, 1, -1, 0),
)
TOUCH = 0.05  # mm between a drawn pin end and the library's
CELL = 1.0  # mm, of the grid used to look pin ends up
COVER = 0.8  # share of a unit's shown pins that must be drawn
RENUMBERED = 0.1  # share of the numbers read that may differ from the library's


def resolve(symbols: list[Symbol], library: Library) -> int:
    """Number the pins of parts whose value names a library symbol, and add the pins
    stacked under them. Returns how many pins gained a number.

    The symbol is placed over the drawing: every drawn pin end must meet a library pin
    end, in one of the unit's eight orientations, and the numbers and names already read
    must agree, but for a few the designer renumbered, which keep their own. Only a fit
    that leaves no doubt is used. A symbol redrawn since the design no longer fits; if
    every number read is still its own, the hidden pins stacked under them are added.
    """
    gained = 0
    for symbol in symbols:
        if symbol.power or not symbol.value or not symbol.pins:
            continue
        entries = library.get(symbol.value.strip().lower())
        if not entries:
            continue
        unit = _unit_number(symbol.unit)
        fits = {_numbering(f) for entry in entries for f in _fits(symbol, entry[1], unit)}
        if not fits:
            fits = {_stacked(symbol, entry[1]) for entry in entries} - {None}
        if len(fits) != 1:
            continue
        numbering = fits.pop()
        for pin, numbers in zip(list(symbol.pins), numbering, strict=True):
            if not numbers:
                continue
            first = pin.number if pin.number in numbers else numbers[0]
            gained += pin.number != first
            pin.number = first
            for number in numbers:
                if number != first:
                    symbol.pins.append(type(pin)(pin.shape, pin.line, number))
                    gained += 1
    return gained


def _fits(symbol: Symbol, pins: list[LibPin], unit: int | None):
    """For each way a unit of the library symbol lies over the drawn one, the library
    pins under each drawn pin end; none under a pin whose number disagrees. A unit
    named on the drawing is the only one tried."""
    units = sorted({p.unit for p in pins} - {0}) or [0]
    if unit is not None and unit in units:
        units = [unit]
    tips = [p.at for p in symbol.pins]
    labels = [p.number for p in symbol.pins]
    labelled = [k for k, label in enumerate(labels) if label]
    allowed = int(RENUMBERED * len(labelled))
    for unit in units:
        mine = [p for p in pins if p.unit in (unit, 0)]
        for a, b, c, d in ORIENTATIONS:
            placed: dict[tuple[float, float], list[LibPin]] = defaultdict(list)
            for p in mine:
                x, y = p.at
                placed[(a * x + b * y, c * x + d * y)].append(p)
            shown = {spot for spot, ps in placed.items() if not all(p.hidden for p in ps)}
            if len(placed) < len(tips):
                continue
            index: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
            for spot in placed:
                index[_key(*spot)].append(spot)
            for anchor in labelled[: allowed + 1] or [0]:
                for spot, under in placed.items():
                    if labels[anchor] and not _agrees(labels[anchor], under):
                        continue
                    dx, dy = tips[anchor][0] - spot[0], tips[anchor][1] - spot[1]
                    found, wrong = [], 0
                    for (x, y), label in zip(tips, labels, strict=True):
                        at = _near(index, x - dx, y - dy)
                        if at is None:
                            break
                        if label and not _agrees(label, placed[at]):
                            wrong += 1
                            at = None
                        found.append(at)
                    else:
                        # The drawing shows the unit: most of its pins, none twice.
                        spots = [at for at in found if at is not None]
                        if (
                            wrong <= allowed
                            and len(set(spots)) == len(spots)
                            and len(found) >= COVER * len(shown)
                        ):
                            yield [placed[at] if at else [] for at in found]


def _stacked(symbol: Symbol, pins: list[LibPin]) -> tuple[tuple[str, ...], ...] | None:
    """For a symbol that no longer fits, the numbers of the hidden pins of the same name
    stacked under each drawn pin, when every drawn pin's number is the library's."""
    numbers = [p.number for p in symbol.pins]
    by_number = {p.number: p for p in pins}
    if not numbers or any(n not in by_number for n in numbers):
        return None
    out = []
    for number in numbers:
        pin = by_number[number]
        under = [
            p.number
            for p in pins
            if p.unit == pin.unit and p.at == pin.at and p.name == pin.name and p.hidden
        ]
        out.append(tuple(sorted({number, *under})))
    return tuple(out)


def _unit_number(unit: str | None) -> int | None:
    """KiCad's units are lettered A, B, C."""
    if unit and len(unit) == 1 and "A" <= unit <= "Z":
        return ord(unit) - ord("A") + 1
    return None


def _key(x: float, y: float) -> tuple[int, int]:
    return round(x / CELL), round(y / CELL)


def _near(index, x: float, y: float) -> tuple[float, float] | None:
    kx, ky = _key(x, y)
    for i in (kx - 1, kx, kx + 1):
        for j in (ky - 1, ky, ky + 1):
            for spot in index.get((i, j), ()):
                if abs(spot[0] - x) < TOUCH and abs(spot[1] - y) < TOUCH:
                    return spot
    return None


def _agrees(label: str, pins: list[LibPin]) -> bool:
    return any(label in (p.number, p.name) for p in pins)


def _numbering(under: list[list[LibPin]]) -> tuple[tuple[str, ...], ...]:
    """The numbers under each drawn pin; none where the drawing numbers it otherwise."""
    return tuple(tuple(sorted({p.number for p in ps})) for ps in under)
