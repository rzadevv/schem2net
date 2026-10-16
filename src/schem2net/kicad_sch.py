"""Write an extraction as an editable KiCad schematic.

Each PDF page becomes a sheet of its own, with parts and wires where the PDF
drew them. A part gets a symbol made from its own outline, with its pins where
they were found. Named nets are carried by a global label on each of their
pins, so the schematic connects the same way as the extracted netlist.
"""

import json
import uuid
from collections import defaultdict
from pathlib import Path

from schem2net import geometry
from schem2net.export import unique_names
from schem2net.geometry import GridIndex, UnionFind
from schem2net.ir import Component, Net, unnumbered
from schem2net.pipeline import Extraction, PageResult
from schem2net.scene import Scene
from schem2net.symbols import Symbol

VERSION = "20250114"
TOUCH = 0.01  # mm; generated points coincide exactly
MIN_WIRE = 0.05  # mm
SNAP = 0.05  # mm; as far as extraction lets two points count as one
FONT = ["effects", ["font", ["size", "1.27", "1.27"]]]
HIDDEN = ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]


class Q(str):
    """A string written in quotes."""


def write(extraction: Extraction, out_dir: Path, name: str) -> Path:
    """Write the root sheet and one sheet per page; return the root file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    root_id = _uuid()
    pages = [p for p in extraction.pages if p.scene is not None]
    nets = _pin_nets(extraction.design.nets, extraction.design.components)
    labels = _label_names(extraction.design.nets)
    drawn = _drawn(pages)

    sheets = []
    for k, page in enumerate(pages, 1):
        sheet_id = _uuid()
        file = f"{name}-page{page.page.number}.kicad_sch"
        path = f"/{root_id}/{sheet_id}"
        body = _page(page, name, path, nets, labels, drawn, extraction.wire_nets)
        (out_dir / file).write_text(_dump(body) + "\n")
        sheets.append(_sheet_symbol(k, sheet_id, file, name, root_id))

    root = [
        "kicad_sch",
        ["version", VERSION],
        ["generator", Q("schem2net")],
        ["uuid", Q(root_id)],
        ["paper", Q("A4")],
        ["lib_symbols"],
        *sheets,
        ["sheet_instances", ["path", Q("/"), ["page", Q("1")]]],
    ]
    root_file = out_dir / f"{name}.kicad_sch"
    root_file.write_text(_dump(root) + "\n")

    # The symbols also go in a project library, so KiCad can find and edit them.
    symbols = [_lib_symbol(ref, pieces, lib_name=ref) for ref, pieces in sorted(drawn.items())]
    library = ["kicad_symbol_lib", ["version", "20241209"], ["generator", Q("schem2net")], *symbols]
    (out_dir / f"{name}.kicad_sym").write_text(_dump(library) + "\n")
    table = [
        "sym_lib_table",
        ["version", "7"],
        [
            "lib",
            ["name", Q("schem2net")],
            ["type", Q("KiCad")],
            ["uri", Q(f"${{KIPRJMOD}}/{name}.kicad_sym")],
            ["options", Q("")],
            ["descr", Q("")],
        ],
    ]
    (out_dir / "sym-lib-table").write_text(_dump(table) + "\n")
    project = {"meta": {"filename": f"{name}.kicad_pro", "version": 3}}
    (out_dir / f"{name}.kicad_pro").write_text(json.dumps(project, indent=2) + "\n")
    return root_file


def _page(
    page: PageResult,
    project: str,
    path: str,
    nets: dict[tuple[str, str], Net],
    labels: dict[str, str],
    drawn: dict[str, list[tuple[Symbol, Scene]]],
    wire_nets: dict[tuple[int, int], str],
) -> list:
    scene = page.scene
    parts = _parts(page)
    lib = {}
    placed = []
    for symbol in parts:
        unit = next(u for u, (s, _) in enumerate(drawn[symbol.ref], 1) if s is symbol)
        lib.setdefault(symbol.ref, _lib_symbol(symbol.ref, drawn[symbol.ref]))
        placed.append(_placed(symbol, unit, project, path))

    net_of = {pin: net.id for pin, net in nets.items()}
    tips = [
        (p.at, net_of.get((symbol.ref, _shown(p))))
        for symbol in parts
        for p in symbol.pins
        if _shown(p)
    ]
    wire_net = [wire_nets.get((page.page.number, i)) for i in range(len(scene.wires))]
    snapped, tees = _snapped(scene.wires, wire_net, tips)
    wires, wire_net = _split_at_tips(snapped, wire_net, tips)
    ends = {_key(p) for w in wires for p in w}
    items: list = []
    for a, b in wires:
        items.append(["wire", ["pts", _xy(a), _xy(b)], _stroke(), ["uuid", Q(_uuid())]])
    for x, y in [*scene.junctions, *tees]:
        items.append(["junction", ["at", _n(x), _n(y)], ["diameter", "0"], ["uuid", Q(_uuid())]])
    for x, y in scene.no_connects:
        items.append(["no_connect", ["at", _n(x), _n(y)], ["uuid", Q(_uuid())]])
    carried = {net_id: name for net_id, (name, shown) in labels.items() if shown}
    items += _wire_labels(wires, wire_net, carried, {_key(t) for t, _ in tips})
    # A pin that no wire ends on is joined to its net by a label of its own, and so
    # is a pin drawn in several units, so that every unit shows the same net.
    for symbol in parts:
        for pin in symbol.pins:
            net = nets.get((symbol.ref, _shown(pin) or ""))
            if net is None or (net.id not in carried and len(net.pins) < 2):
                continue
            shared = symbol.unit and any(
                other is not symbol
                and other.unit
                and any(_shown(p) == _shown(pin) for p in other.pins)
                for other, _ in drawn[symbol.ref]
            )
            if _key(pin.at) not in ends or shared:
                inner, outer = pin.line
                items.append(_label(labels[net.id][0], outer, _angle(inner, outer)))

    width, height = page.page.width, page.page.height
    return [
        "kicad_sch",
        ["version", VERSION],
        ["generator", Q("schem2net")],
        ["uuid", Q(_uuid())],
        ["paper", Q("User"), _n(width), _n(height)],
        ["lib_symbols", *lib.values()],
        *items,
        *placed,
    ]


def _lib_symbol(ref: str, pieces: list[tuple[Symbol, Scene]], lib_name: str = "") -> list:
    """One symbol per part, with a unit for every place the part is drawn."""
    node = [
        "symbol",
        Q(lib_name or f"schem2net:{ref}"),
        ["pin_names", ["offset", "0"], ["hide", "yes"]],
        ["exclude_from_sim", "no"],
        ["in_bom", "yes"],
        ["on_board", "yes"],
        ["property", Q("Reference"), Q(_prefix(ref)), ["at", "0", "0", "0"], FONT],
        ["property", Q("Value"), Q(ref), ["at", "0", "0", "0"], HIDDEN],
        ["property", Q("Footprint"), Q(""), ["at", "0", "0", "0"], HIDDEN],
        ["property", Q("Datasheet"), Q(""), ["at", "0", "0", "0"], HIDDEN],
    ]
    for unit, (symbol, scene) in enumerate(pieces, 1):
        node.append(_unit_graphics(ref, unit, symbol, scene))
    return node


def _unit_graphics(ref: str, unit: int, symbol: Symbol, scene: Scene) -> list:
    origin = _origin(symbol)
    pin_shapes = {p.shape for p in symbol.pins}
    out = ["symbol", Q(f"{ref}_{unit}_1")]
    for i in symbol.shapes:
        shape = scene.shapes[i]
        if i in pin_shapes:
            continue
        pts = ["pts", *(_lib_xy(p, origin) for p in shape.points)]
        out.append(["polyline", pts, _stroke(), ["fill", ["type", "none"]]])
    for pin in symbol.pins:
        if not _shown(pin):
            continue
        inner, outer = pin.line
        length = ((inner[0] - outer[0]) ** 2 + (inner[1] - outer[1]) ** 2) ** 0.5
        _, x, y = _lib_xy(outer, origin)
        out.append(
            [
                "pin",
                "passive",
                "line",
                ["at", x, y, str(_angle(outer, inner))],
                ["length", _n(length)],
                ["name", Q("~"), FONT],
                ["number", Q(_shown(pin)), FONT],
            ]
        )
    return out


def _placed(symbol: Symbol, unit: int, project: str, path: str) -> list:
    x, y = _origin(symbol)
    x0, y0, x1, y1 = symbol.bbox
    pins = [["pin", Q(_shown(p)), ["uuid", Q(_uuid())]] for p in symbol.pins if _shown(p)]
    return [
        "symbol",
        ["lib_id", Q(f"schem2net:{symbol.ref}")],
        ["at", _n(x), _n(y), "0"],
        ["unit", str(unit)],
        ["exclude_from_sim", "no"],
        ["in_bom", "yes"],
        ["on_board", "yes"],
        ["dnp", "no"],
        ["uuid", Q(_uuid())],
        ["property", Q("Reference"), Q(symbol.ref), ["at", _n(x0), _n(y0 - 1.5), "0"], FONT],
        ["property", Q("Value"), Q(symbol.value or "~"), ["at", _n(x0), _n(y1 + 1.5), "0"], FONT],
        ["property", Q("Footprint"), Q(""), ["at", _n(x), _n(y), "0"], HIDDEN],
        ["property", Q("Datasheet"), Q(""), ["at", _n(x), _n(y), "0"], HIDDEN],
        *pins,
        [
            "instances",
            [
                "project",
                Q(project),
                ["path", Q(path), ["reference", Q(symbol.ref)], ["unit", str(unit)]],
            ],
        ],
    ]


def _sheet_symbol(k: int, sheet_id: str, file: str, project: str, root_id: str) -> list:
    x, y = 20 + 40 * ((k - 1) % 6), 20 + 30 * ((k - 1) // 6)
    return [
        "sheet",
        ["at", _n(x), _n(y)],
        ["size", "30", "20"],
        ["exclude_from_sim", "no"],
        ["in_bom", "yes"],
        ["on_board", "yes"],
        ["dnp", "no"],
        ["stroke", ["width", "0.1524"], ["type", "solid"]],
        ["fill", ["color", "0", "0", "0", "0.0000"]],
        ["uuid", Q(sheet_id)],
        ["property", Q("Sheetname"), Q(f"Page {k}"), ["at", _n(x), _n(y - 0.7), "0"], FONT],
        ["property", Q("Sheetfile"), Q(file), ["at", _n(x), _n(y + 20.7), "0"], FONT],
        ["instances", ["project", Q(project), ["path", Q(f"/{root_id}"), ["page", Q(str(k + 1))]]]],
    ]


def _wire_labels(
    wires: list, wire_net: list, labels: dict[str, str], tips: set[tuple[str, str]]
) -> list:
    """A label on each piece of wiring that belongs to a named net.

    Labels go where the wiring ends at nothing, which is where the PDF had labels
    and power symbols; otherwise at any end of the piece.
    """
    named = [i for i, net in enumerate(wire_net) if net in labels]
    pieces = UnionFind()
    for i in named:
        pieces.find(i)
        for j in named:
            if j > i and wire_net[i] == wire_net[j] and _touch(wires[i], wires[j]):
                pieces.union(i, j)
    out = []
    for group in pieces.groups().values():
        name = labels[wire_net[group[0]]]
        loose = [
            (end, other)
            for i in group
            for end, other in (wires[i], wires[i][::-1])
            if _key(end) not in tips
            and not any(j != i and _on(end, wires[j]) for j in range(len(wires)))
        ]
        for end, other in loose or [wires[group[0]]]:
            out.append(_label(name, end, _angle(other, end)))
    return out


def _split_at_tips(wires: list, wire_net: list, tips: list) -> tuple[list, list]:
    """Wires cut where a pin of their net ends partway along them, since KiCad joins a
    pin to a wire only at the wire's end. Specks left by curves are dropped."""
    out, nets = [], []
    for (a, b), net in zip(wires, wire_net, strict=True):
        cuts = sorted(
            (geometry.distance(a, t), t)
            for t, tip_net in tips
            if tip_net == net
            and geometry.distance_to_segment(t, (a, b)) <= TOUCH
            and _key(t) not in (_key(a), _key(b))
        )
        points = [a, *(t for _, t in cuts), b]
        for p, q in zip(points, points[1:], strict=False):
            if geometry.distance(p, q) >= MIN_WIRE:
                out.append((p, q))
                nets.append(net)
    return out, nets


def _label(name: str, at: tuple[float, float], angle: int) -> list:
    return [
        "global_label",
        Q(name),
        ["shape", "passive"],
        ["at", _n(at[0]), _n(at[1]), str(angle)],
        FONT,
        ["uuid", Q(_uuid())],
    ]


def _touch(a: tuple, b: tuple) -> bool:
    return any(_on(p, b) for p in a) or any(_on(p, a) for p in b)


def _on(p: tuple[float, float], seg: tuple) -> bool:
    return geometry.distance_to_segment(p, seg) <= TOUCH


def _parts(page: PageResult) -> list[Symbol]:
    return [s for s in page.symbols if s.ref and not s.power]


def _drawn(pages: list[PageResult]) -> dict[str, list[tuple[Symbol, Scene]]]:
    """Every drawn piece of each part, in page order: unit 1, unit 2 and so on."""
    drawn: dict[str, list[tuple[Symbol, Scene]]] = defaultdict(list)
    for page in pages:
        for symbol in _parts(page):
            drawn[symbol.ref].append((symbol, page.scene))
    return drawn


def _pin_nets(nets: list[Net], components: list[Component]) -> dict[tuple[str, str], Net]:
    """The net of each pin, by number, and of a pin with no number by its name."""
    out = {pin: net for net in nets for pin in net.pins}
    for comp in components:
        for pin in comp.pins:
            if pin.name and unnumbered(pin.num) and (comp.ref, pin.num) in out:
                out.setdefault((comp.ref, pin.name), out[comp.ref, pin.num])
    return out


def _shown(pin) -> str | None:
    """What a pin is known by on the drawing: its number, or its name where it has none."""
    return pin.number or pin.name


def _label_names(nets: list[Net]) -> dict[str, tuple[str, bool]]:
    """A unique label name for every net, and whether its wiring should show it:
    named nets and nets spanning pages do; others only label pins no wire reaches."""
    unique = unique_names(nets, lambda net: net.name or f"N{net.id[1:]}")
    return {net.id: (unique[net.id], bool(net.name) or len(net.pages) > 1) for net in nets}


def _snapped(wires: list, wire_net: list, tips: list) -> tuple[list, list]:
    """Wires moved onto the points they were read as touching, since KiCad joins only
    exact matches. Ends go onto pin tips, onto other ends, or onto the middle of
    another wire, where a junction is added; only ever within one net.

    `wire_net` gives each wire's net, `tips` each pin tip with its net.
    """
    points = GridIndex(cell=1.0)
    anchors: list[tuple[tuple[float, float], str | None]] = []
    for tip, net in tips:
        points.add(len(anchors), (*tip, *tip))
        anchors.append((tip, net))

    def snap(p, net):
        near = [
            k
            for k in points.near(p, SNAP)
            if anchors[k][1] == net and geometry.distance(p, anchors[k][0]) <= SNAP
        ]
        if near:
            return anchors[min(near, key=lambda k: geometry.distance(p, anchors[k][0]))][0]
        points.add(len(anchors), (*p, *p))
        anchors.append((p, net))
        return p

    out = [(snap(a, net), snap(b, net)) for (a, b), net in zip(wires, wire_net, strict=True)]
    index = GridIndex()
    for k, w in enumerate(out):
        index.add(k, geometry.bbox_of(w))
    tees = []
    for i, (a, b) in enumerate(out):
        moved = []
        for p in (a, b):
            for k in index.near(p, SNAP):
                w = out[k]
                if k == i or wire_net[k] != wire_net[i] or _key(p) in (_key(w[0]), _key(w[1])):
                    continue
                if geometry.distance_to_segment(p, w) <= SNAP:
                    p = _project(p, w)
                    tees.append(p)
                    break
            moved.append(p)
        out[i] = (moved[0], moved[1])
    return out, tees


def _project(p: tuple[float, float], seg: tuple) -> tuple[float, float]:
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    return ax + t * dx, ay + t * dy


def _key(p: tuple[float, float]) -> tuple[str, str]:
    """A point as written to the file."""
    return _n(p[0]), _n(p[1])


def _origin(symbol: Symbol) -> tuple[float, float]:
    x0, y0, x1, y1 = symbol.bbox
    return round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)


def _angle(frm: tuple[float, float], to: tuple[float, float]) -> int:
    """Direction from one point to another, in KiCad's degrees, y pointing up."""
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 270 if dy > 0 else 90


def _prefix(ref: str) -> str:
    return ref.rstrip("0123456789") or ref


def _xy(p: tuple[float, float]) -> list:
    return ["xy", _n(p[0]), _n(p[1])]


def _lib_xy(p: tuple[float, float], origin: tuple[float, float]) -> list:
    return ["xy", _n(p[0] - origin[0]), _n(origin[1] - p[1])]


def _stroke() -> list:
    return ["stroke", ["width", "0"], ["type", "default"]]


def _n(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _uuid() -> str:
    return str(uuid.uuid4())


def _dump(node: list, depth: int = 0) -> str:
    head, *rest = node
    atoms = [_atom(x) for x in rest if not isinstance(x, list)]
    lists = [x for x in rest if isinstance(x, list)]
    first = "(" + " ".join([head, *atoms])
    if not lists:
        return first + ")"
    pad = "\t" * (depth + 1)
    return "\n".join([first, *(pad + _dump(x, depth + 1) for x in lists)]) + ")"


def _atom(x: str) -> str:
    if isinstance(x, Q):
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return x
