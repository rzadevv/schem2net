# Usage

Install from Git as shown in the [README](../README.md). The CLI accepts a vector
schematic PDF; `export`, `diff` and `serve-mcp` also accept JSON saved by `extract`.
Run `schem2net COMMAND --help` for all options.

## Extraction and review

```sh
schem2net extract board.pdf -o board.ir.json
schem2net report board.pdf -o board.html
schem2net report board.pdf --no-pdf -o board-small.html
schem2net extract board.pdf --region 2:10,20,150,100
```

Regions use `PAGE:X0,Y0,X1,Y1` in millimetres from the displayed page's top-left
corner. A region always reads the drawing rather than a carried netlist.
`--no-pdf` omits background page images from the HTML report.

JSON uses schema `schem2net/ir@0.1`: source information, components, pins, nets,
connection evidence and issues. A pin with an unread number keeps a placeholder
such as `?1`; a known name can be retained separately. Confidence below 0.8 marks
weak net evidence. Confidence at or above 0.8 does not certify the net's physical
pin identities. The report lists guessed numbers, missing connections and other
issues separately, with links to their positions on the drawing.

## Exports and revisions

```sh
schem2net export board.ir.json --to kicad-net -o board.net
schem2net export board.ir.json --to bom -o board.bom.csv
schem2net export board.ir.json --to spice -o board.cir
schem2net schematic board.pdf -o board-kicad
schem2net diff old.ir.json new.ir.json
```

The KiCad netlist contains numbered terminals; placeholders do not become physical
pads. Assign footprints in KiCad. `schematic` reconstructs layout and symbol
shapes into an editable project, always from drawing geometry. It does not prove
ERC correctness or recover the original symbol libraries. SPICE output is a
starting point: device models and pin assignments need checking.

`diff` matches components by reference and compares connectivity by shared pins;
a net-name change alone is not a connection change.

## Optional part libraries

```sh
schem2net index-library /usr/share/kicad/symbols -o parts
schem2net extract board.pdf --library parts
```

KiCad `.kicad_sym`/`.kicad_symdir` libraries and Eagle `.lbr` libraries can be
indexed. `SCHEM2NET_LIBRARY` supplies the CLI default. Without an index, no part
library is read. The source record includes the index fingerprint when used.

KiCad library fits can recover hidden or stacked numbers when visible geometry
and known pins agree. Eagle library lookup supplies names, not package-dependent
pad numbers. Standalone hidden power pins and custom library variants remain
limitations. Review the [upstream library terms](learned-assets.md#external-library-indexes)
before redistributing an index.

## Python interface

```python
from schem2net.pipeline import extract
from schem2net.query import Query

design = extract("board.pdf", embedded=False)
design.save("board.ir.json")
print(Query(design).net("U3.14"))
```

By default, `extract` uses a carried Altium netlist if present. `embedded=False`
forces geometry-based reconstruction, as the drawing-only benchmark does.
`pipeline.run` additionally returns per-page scenes for rendering and schematic
export. PDF processing should run in separate processes, not concurrent PDFium
threads. `profile.use_learned(None)` restores shipped models; it does not disable
them. Overrides are intended for benchmark training/evaluation processes.

## MCP

```sh
uv tool install "schem2net[mcp] @ git+https://github.com/rzadevv/schem2net"
schem2net serve-mcp board.ir.json
```

The server exposes one design over stdio. Its read-only tools are
`list_components`, `get_net`, `pins_of`, `trace`, `low_confidence`, `issues` and
`bom`. `get_net` accepts a name or a pin such as `U3.14`; `trace` follows small
networks through series passives. MCP queries report the extracted design, not
independent verification of the original circuit.

## Desktop application

An optional Qt application shows a PDF, runs the same extraction, and lets you
review the result beside the drawing. Install it with the `gui` extra, which adds
PySide6 (about 700 MB with Qt WebEngine); the CLI does not need it.

```sh
uv tool install 'schem2net[gui] @ git+https://github.com/rzadevv/schem2net'
schem2net-gui board.pdf
```

From a checkout, `uv sync --extra gui` then `uv run schem2net-gui`.

- **Original** shows the PDF with zoom (Ctrl+Plus/Minus, Ctrl+wheel), fit
  (Ctrl+0) and page keys (Page Up/Down). Files can also be dropped on the window.
- **Extract** (Ctrl+E) runs extraction in a separate process. Stop ends that
  process and keeps nothing; no file is written until you export.
- **Extracted Nets** is the HTML report. Selecting a net, component or issue in
  the side panels highlights it or zooms to it there; Esc clears the selection.
  Properties lists each pin's number source: printed, part library, inferred,
  guessed or not shown. With nothing selected, it describes the document and how
  it was read.
- **File › Part Library** chooses an index made by `index-library`, as `--library`
  does; `SCHEM2NET_LIBRARY` is the default.
- **File › Export** writes the KiCad netlist (Ctrl+S), JSON, BOM, SPICE, HTML
  report or an editable KiCad project, as the CLI does.

Nets carried in an Altium PDF are listed but cannot be shown on the drawing, since
the drawing is not read; the editable KiCad project, which needs the drawing, is
then not offered (`schem2net schematic` reads the drawing instead). A component
on several units is shown at its first. The extractor reports no progress, so only a busy
indicator is shown. PyPI's Qt cannot load distribution theme plugins such as
KDE's; the application then follows the desktop's light or dark setting through
the XDG portal. Qt WebEngine needs NSS, ALSA, EGL and xkbcommon, which desktop
Linux installations provide.

## Failures and resource limits

| Exit | Meaning |
|---|---|
| 1 | Unreadable, missing, malformed or over-limit input. |
| 2 | No supported generator/profile could read the input. |
| 3 | No parts were found; with `--strict`, also when any page failed. |

`extract`, `export`, `report` and `schematic` accept `--strict`. Refusal leaves an
existing output unchanged. Partial readings otherwise retain failed-page issues;
board drawings, tables and raster pages are reported as skipped.

The reader refuses more than 1,000 pages and stops pages exceeding 1.5 million
visited drawing objects or 32 nested forms. Ingestion and analysis each have a
1,200-second page budget on POSIX main threads. Native PDFium calls can delay
signal handling. Threads and platforms without interval timers have no such
budget; there is no hard in-process memory ceiling. Use an outer subprocess
limit for untrusted or unusually large documents. Native Windows/macOS resource
behaviour has not been validated by the recorded Linux release evaluation.
