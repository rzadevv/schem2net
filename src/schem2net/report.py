"""An HTML page that draws the extracted nets over the schematic.

Each net gets its own colour. Pins of low-confidence nets are circled in red;
problems found by the checks, such as wire ends touching nothing, and pin numbers
the drawing does not show, are marked in orange. Everything to check is listed in
one queue, most serious first; clicking an entry shows where it is, and clicking a
net in the list highlights the net.
"""

from html import escape

from schem2net.ir import LOW_CONFIDENCE, Net
from schem2net.pipeline import Extraction, PageResult

STYLE = """
:root { --bg: #fff; --fg: #1d2127; --muted: #6b7280; --line: #e5e7eb; --paper: #fff;
        --ink: #b8bcc4; --warn: #d97706; --bad: #dc2626; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #16181c; --fg: #e5e7eb; --muted: #9ca3af; --line: #2d3139; --paper: #202328;
          --ink: #555b66; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.4 system-ui, sans-serif; background: var(--bg); color: var(--fg);
       display: grid; grid-template-columns: 300px 1fr; height: 100vh; }
aside { border-right: 1px solid var(--line); overflow: auto; padding: 16px; }
main { overflow: auto; padding: 16px; }
h1 { font-size: 16px; margin: 0 0 4px; word-break: break-all; }
.meta { color: var(--muted); margin-bottom: 12px; }
.issues { color: var(--muted); margin-bottom: 12px; }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 4px 6px; border-radius: 4px; cursor: pointer; display: flex; gap: 8px; }
li:hover, li.on { background: var(--line); }
li .n { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
li .c { color: var(--muted); font-variant-numeric: tabular-nums; }
li.low .c { color: var(--bad); }
.swatch { width: 10px; height: 10px; border-radius: 2px; margin-top: 5px; flex: none; }
section { margin-bottom: 24px; }
h2 { font-size: 14px; color: var(--muted); font-weight: normal; }
svg { width: 100%; height: auto; background: var(--paper); border: 1px solid var(--line); }
.ink { stroke: var(--ink); fill: none; }
.txt { fill: var(--ink); font-family: sans-serif; }
.low { stroke: var(--bad); fill: none; }
.unnumbered { stroke: var(--warn); fill: none; }
.guess { stroke: var(--warn); fill: none; stroke-dasharray: 0.4 0.3; }
.mark.on { stroke: var(--fg); stroke-width: 0.6; }
.todo { max-height: 45vh; overflow: auto; margin-bottom: 12px; }
.todo h2 { color: var(--fg); font-weight: 600; margin: 0 0 6px; }
details { margin-bottom: 6px; }
summary { cursor: pointer; }
.todo ol { list-style: none; margin: 2px 0 0 14px; padding: 0; }
body.focus [data-net] { opacity: 0.12; }
body.focus [data-net].on { opacity: 1; }
@media (max-width: 700px) {
  body { grid-template-columns: 1fr; height: auto; }
  aside { border-right: 0; border-bottom: 1px solid var(--line); max-height: 40vh; }
}
"""

SCRIPT = """
for (const item of document.querySelectorAll('li[data-mark]')) {
  item.addEventListener('click', () => {
    document.querySelectorAll('.mark.on, li[data-mark].on').forEach(e => e.classList.remove('on'));
    const mark = document.getElementById(item.dataset.mark);
    item.classList.add('on');
    if (mark) {
      mark.classList.add('on');
      const svg = mark.ownerSVGElement;
      svg.dataset.full = svg.dataset.full || svg.getAttribute('viewBox');
      const x = +mark.getAttribute('cx'), y = +mark.getAttribute('cy');
      svg.setAttribute("viewBox", `${x - 40} ${y - 27} 80 55`);
      svg.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
  });
}
// Double-click a page to see all of it again.
for (const svg of document.querySelectorAll('main svg')) {
  svg.addEventListener('dblclick', () => {
    if (svg.dataset.full) svg.setAttribute('viewBox', svg.dataset.full);
  });
}
const items = document.querySelectorAll('li[data-net]');
let current = null;
for (const item of items) {
  item.addEventListener('click', () => {
    const net = item.dataset.net;
    const same = current === net;
    document.querySelectorAll('.on').forEach(e => e.classList.remove('on'));
    current = same ? null : net;
    document.body.classList.toggle('focus', !same);
    if (!same) {
      document.querySelectorAll(`[data-net="${net}"]`).forEach(e => e.classList.add('on'));
      const first = document.querySelector(`svg [data-net="${net}"]`);
      if (first) first.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
  });
}
"""


ISSUE_TEXT = {
    "dangling_wire": "wire end touching nothing",
    "unnumbered_pin": "pin without a number",
    "unattached_label": "label on no wire or pin",
    "designator_without_part": "designator with no part found",
    "duplicate_pin": "pin number used twice in one part",
    "power_nets_merged": "two power nets joined",
    "unconnected_pin": "pin on no net, without a no-connect flag",
    "connected_no_connect": "pin flagged no-connect but connected",
    "board_page": "board drawing, skipped",
    "table_page": "table, skipped",
    "raster_page": "scanned page, skipped",
    "pin_number_guessed": "pin numbers not shown, guessed",
    "low_confidence_net": "net joined on weak evidence",
}
# The review queue, grouped: first what most often means a wrong connection.
ORDER = [
    "power_nets_merged",
    "low_confidence_net",
    "pin_number_guessed",
    "duplicate_pin",
    "connected_no_connect",
    "unattached_label",
    "unnumbered_pin",
    "designator_without_part",
    "unconnected_pin",
    "dangling_wire",
]
OPEN_GROUPS = 3  # groups shown unfolded


def render(extraction: Extraction) -> str:
    design = extraction.design
    nets = {net.id: net for net in design.nets}
    net_of_pin = {pin: net.id for net in design.nets for pin in net.pins}
    low = [n for n in design.nets if n.confidence < LOW_CONFIDENCE]

    items = "\n".join(_net_item(net) for net in design.nets)
    todo = _review(design, extraction)
    pages = "\n".join(
        _page(result, extraction.wire_nets, net_of_pin, nets, todo)
        for result in extraction.pages
        if result.scene is not None
    )
    title = escape(design.source.file)
    meta = (
        f"{design.source.generator} · {design.source.pages} pages · "
        f"{len(design.components)} parts · {len(design.nets)} nets · "
        f"{len(low)} low confidence · {len(design.issues)} issues"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} nets</title>
<style>{STYLE}</style>
</head>
<body>
<aside>
<h1>{title}</h1>
<div class="meta">{meta}</div>
{_todo_list(todo)}
<ul>
{items}
</ul>
</aside>
<main>
{pages}
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


def _review(design, extraction: Extraction) -> list[dict]:
    """Everything a reviewer should look at, with where it is: issues, and nets joined
    on weak evidence at their first pin. Guessed pin numbers are marked at each pin."""
    where = {}
    for result in extraction.pages:
        for symbol in result.symbols:
            for pin in symbol.pins:
                if pin.number is not None:
                    where.setdefault((symbol.ref, pin.number), (result.page.number, pin.at))
    todo = []
    for issue in design.issues:
        if issue.pins:
            spots = [where[tuple(p)] for p in issue.pins if tuple(p) in where]
        elif issue.page is not None and issue.at:
            spots = [(issue.page, issue.at)]
        else:
            spots = []
        what = issue.detail or ", ".join(f"{r}.{n}" for r, n in issue.pins)
        if not what and issue.page is not None:
            what = f"page {issue.page}"
        todo.append({"kind": issue.kind, "severity": issue.severity, "what": what, "spots": spots})
    for net in design.nets:
        if net.confidence < LOW_CONFIDENCE and net.pins:
            spot = where.get(tuple(net.pins[0]))
            name = net.name or ", ".join(f"{r}.{n}" for r, n in net.pins[:3])
            todo.append(
                {
                    "kind": "low_confidence_net",
                    "severity": "warn",
                    "what": name,
                    "spots": [spot] if spot else [],
                }
            )
    rank = {kind: k for k, kind in enumerate(ORDER)}
    todo.sort(key=lambda t: rank.get(t["kind"], len(ORDER)))
    for k, item in enumerate(todo):
        item["id"] = f"m{k}"
    return todo


def _todo_list(todo: list[dict]) -> str:
    if not todo:
        return '<p class="meta">Nothing to check.</p>'
    groups: dict[str, list[dict]] = {}
    for item in todo:
        groups.setdefault(item["kind"], []).append(item)
    out = [
        f'<div class="todo"><h2>To check ({len(todo)})</h2>'
        '<p class="meta">Click an entry to zoom to it; double-click the page to zoom out.</p>'
    ]
    for k, (kind, items) in enumerate(groups.items()):
        rows = "".join(
            "<li" + (f' data-mark="{t["id"]}"' if t["spots"] else "") + ">"
            f'<span class="n" title="{escape(t["what"])}">{escape(t["what"])}</span></li>'
            for t in items
        )
        label = escape(ISSUE_TEXT.get(kind, kind))
        state = " open" if k < OPEN_GROUPS else ""
        out.append(
            f"<details{state}><summary>{label} ({len(items)})</summary><ol>{rows}</ol></details>"
        )
    out.append("</div>")
    return "".join(out)


def _net_item(net: Net) -> str:
    low = ' class="low"' if net.confidence < LOW_CONFIDENCE else ""
    name = escape(net.name or ", ".join(f"{r}.{p}" for r, p in net.pins[:3]))
    return (
        f'<li{low} data-net="{net.id}">'
        f'<span class="swatch" style="background:{_color(net.id)}"></span>'
        f'<span class="n" title="{name}">{name}</span>'
        f'<span class="c">{len(net.pins)} · {net.confidence:.2f}</span></li>'
    )


def _page(
    result: PageResult, wire_nets: dict, net_of_pin: dict, nets: dict[str, Net], todo: list
) -> str:
    page, scene = result.page, result.scene
    out = [
        f"<section><h2>Page {page.number}{' · ' + escape(scene.path) if scene.path else ''}</h2>",
        f'<svg viewBox="0 0 {page.width:.1f} {page.height:.1f}" role="img" '
        f'aria-label="Page {page.number}">',
    ]
    for shape in scene.shapes:
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in shape.points)
        out.append(f'<polyline class="ink" stroke-width="0.15" points="{points}"/>')
    for text in page.texts:
        x0, _, _, y1 = text.bbox
        rotate = f' transform="rotate({-text.angle:.0f} {x0:.2f} {y1:.2f})"' if text.angle else ""
        out.append(
            f'<text class="txt" x="{x0:.2f}" y="{y1:.2f}" font-size="{text.size:.2f}"{rotate}>'
            f"{escape(text.text)}</text>"
        )
    for i, ((ax, ay), (bx, by)) in enumerate(scene.wires):
        net = wire_nets.get((page.number, i))
        color = _color(net) if net else "var(--ink)"
        attr = f' data-net="{net}"' if net else ""
        title = f"<title>{escape(nets[net].name or net)}</title>" if net else ""
        out.append(
            f'<line{attr} x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
            f'stroke="{color}" stroke-width="0.35">{title}</line>'
        )
    for symbol in result.symbols:
        if symbol.power:
            continue
        for pin in symbol.pins:
            x, y = pin.at
            if pin.number is None:
                out.append(f'<circle class="unnumbered" cx="{x:.2f}" cy="{y:.2f}" r="1.2"/>')
                continue
            net = net_of_pin.get((symbol.ref, pin.number))
            if not net:
                continue
            out.append(
                f'<circle data-net="{net}" cx="{x:.2f}" cy="{y:.2f}" r="0.5" '
                f'fill="{_color(net)}"><title>{escape(symbol.ref)}.{escape(pin.number)}</title></circle>'
            )
            if nets[net].confidence < LOW_CONFIDENCE:
                out.append(
                    f'<circle class="low" data-net="{net}" cx="{x:.2f}" cy="{y:.2f}" r="1.2"/>'
                )
    for item in todo:
        text = escape(ISSUE_TEXT.get(item["kind"], item["kind"]))
        guess = item["kind"] == "pin_number_guessed"
        for k, (on, (x, y)) in enumerate(item["spots"]):
            if on != page.number:
                continue
            mark = f' id="{item["id"]}"' if k == 0 else ""
            out.append(
                f'<circle{mark} class="mark {"guess" if guess else "unnumbered"}" '
                f'cx="{x:.2f}" cy="{y:.2f}" r="{1.6 if guess else 0.8}">'
                f"<title>{text}</title></circle>"
            )
    out.append("</svg></section>")
    return "\n".join(out)


def _color(net_id: str) -> str:
    """A stable, well-spread colour for each net."""
    hue = (int(net_id[1:]) * 137.508) % 360
    return f"hsl({hue:.0f} 70% 42%)"
