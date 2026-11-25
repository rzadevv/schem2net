# Usage

Install from Git as shown in the [README](../README.md). The CLI accepts a vector
schematic PDF; `export` also accepts JSON saved by `extract`.
Run `schem2net COMMAND --help` for all options.

Output paths must differ from the input file, including symlink and hard-link
aliases. The CLI and desktop exports refuse to replace the source. JSON, netlist,
HTML and SVG outputs use unique temporary files and atomic replacement; failed
writes preserve an existing output.

Loading JSON checks the schema version, confidence range, unique component and
net identifiers, and links from nets and issues. Every pin referenced by a net
must appear in that component's pin list, including placeholders such as `?1`.
Invalid input exits with code 1 and leaves an existing output unchanged. These
checks establish structural consistency; electrical connections and physical pin
identities still need review.

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
issues separately, with links to their positions on the drawing. Exported netlists
give guessed pad numbers as real pads; the command line names them when it writes one.

## Exports

```sh
schem2net export board.ir.json -o board.net
```

The KiCad netlist contains numbered terminals; placeholders do not become physical
pads. Assign footprints in KiCad.

## Optional part libraries

```sh
schem2net index-library /usr/share/kicad/symbols -o parts
schem2net extract board.pdf --library parts
```

KiCad `.kicad_sym`/`.kicad_symdir` libraries and Eagle `.lbr` libraries can be
indexed. `SCHEM2NET_LIBRARY` supplies the CLI default. Without an index, no part
library is read. The source record includes the index fingerprint when used.
Index files are replaced atomically, so a failed rebuild preserves the previous
index. Python callers refresh cached pins and fingerprints when an index changes.
Extraction reads pins and their recorded fingerprint from the same file snapshot,
so replacing an index during a reading cannot misidentify the library used.

KiCad library fits can recover hidden or stacked numbers when visible geometry
and known pins agree. Eagle library lookup supplies names, not package-dependent
pad numbers. Standalone hidden power pins and custom library variants remain
limitations. Review the [upstream library terms](learned-assets.md#external-library-indexes)
before redistributing an index.

## Python interface

```python
from schem2net.pipeline import extract

design = extract("board.pdf", embedded=False)
design.save("board.ir.json")
print([(part.ref, part.value) for part in design.components])
```

By default, `extract` uses a carried Altium netlist if present. `embedded=False`
forces geometry-based reconstruction, as the drawing-only benchmark does.
`pipeline.run` additionally returns per-page scenes for rendering. PDF processing should run in separate processes, not concurrent PDFium
threads. `profile.use_learned(None)` restores shipped models; it does not disable
them. Overrides are intended for benchmark training/evaluation processes.

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
- **File › Export** writes the KiCad netlist (Ctrl+S), JSON and the HTML report, as the CLI does.

Nets carried in an Altium PDF are listed but cannot be shown on the drawing, since
the drawing is not read. A component on several units is shown at its first. The report draws over a raster image of
each page, which softens at high zoom; **Original** stays sharp. The extractor reports no progress, so only a busy
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

`extract`, `export` and `report` accept `--strict`. Refusal leaves an
existing output unchanged. Partial readings otherwise retain failed-page issues;
board drawings, tables and raster pages are reported as skipped.

The reader refuses more than 1,000 pages and stops pages exceeding 1.5 million
visited drawing objects or 32 nested forms. Ingestion and analysis each have a
1,200-second page budget on POSIX main threads. After page analysis, library
matching and final netlist construction share a separate 1,200-second budget
across all pages. Expiry refuses the input with code 1 and preserves existing
output, including without `--strict`.
Drawing reconstruction refuses
vector bus ranges exceeding 10,000 members before expansion, including reversed
ranges and hierarchical sheet pins. This exits with code 1 and preserves existing
output, including without `--strict`; no partial design is returned for that input.
Native PDFium calls can delay
signal handling. Threads and platforms without interval timers have no such
budget; there is no hard in-process memory ceiling. Use an outer subprocess
limit for untrusted or unusually large documents. Native Windows/macOS resource
behaviour has not been validated by the recorded Linux release evaluation.
