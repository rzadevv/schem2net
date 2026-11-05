<p align="center"><img src="schem2net.png" alt="schem2net" width="800"></p>

Turn a schematic PDF into a netlist.

```sh
schem2net export board.pdf --to kicad-net    # writes board.net
```

Most schematic PDFs are plotted straight from an EDA tool, so every wire, pin and
label sits at an exact coordinate. schem2net reads that geometry, not pixels, and
works out what is connected to what. Each net comes with a confidence, and anything
doubtful is listed for you to check, with an HTML report that draws the nets over
the original pages.

It is early software: check what it gives you before you build a board from it.

## Supported tools

| Generator | Support |
|---|---|
| KiCad | End to end, including hierarchical sheets and buses. |
| Altium | Smart PDFs carry their netlist in the bookmarks, which is read as is. Reading the drawing works for most boards; hidden pin numbers are the main gap. |
| OrCAD Capture | Pages printed through a PDF printer, in Capture's default colours or in black. |
| Eagle | Stroke-font and outlined text, and sheets printed to fit the paper. Less accurate than KiCad and Altium. |
| EasyEDA | Std and Pro exports. Early work. |

PDFs that don't say which tool made them are recognised by their colours. Pages
printed in black or in a custom colour theme are read too, with roles learned
from colour pages, and lose some accuracy. A PDF whose tool can't be told is read
as each generator in turn and flagged as a guess.

## How well it works

Pin accuracy on each benchmark corpus's test split, boards the learned models
never saw:

| Corpus | Boards | Pins | Pin accuracy | Silent errors | Pins not found |
|---|---|---|---|---|---|
| A, KiCad | 6 | 1,154 | 0.93 | 0.2% | 1.6% |
| B, Altium (drawing only) | 12 | 3,887 | 0.86 | 2.2% | 9.4% |
| C, Eagle (SparkFun) | 39 | 2,824 | 0.81 | 0.7% | 15.7% |
| D, Olimex (KiCad and Eagle) | 20 | 6,057 | 0.86 | 0.3% | 10.6% |
| E, EasyEDA | 14 | 1,027 | 0.65 | 0.1% | 27.8% |
| F, OrCAD | 8 | 10,702 | 0.95 | 0.5% | 2.5% |

A silent error is a pin on the wrong net that nothing flags. A pin not found is on
no net at all: its part was missed, or its number is hidden in the drawing. These
figures were read once at commit 0cf46ce. Holdout results, intervals and review
figures are in [docs/benchmark.md](docs/benchmark.md#results).

These are historical measurements. The current scorer aligns issue references
with recovered names and equivalent passive ends; confidence and review figures
need rescoring before comparison. See the
[development audit](docs/audit-2026-11-02.md) for the initial correctness findings and
[continued development](docs/development-2026-11-02.md) for extraction improvements
measured after upstream reconciliation.

The [independent release evaluation](docs/release-2026-11-05.md) covers 63 new
designs from 40 source groups, mostly generated KiCad exports. Pin accuracy was
91.02%, but the silent-error gate remained inconclusive and a high-confidence
MCU pad error persisted. Generator coverage and learned-asset distribution
clearance are incomplete; the candidate is not ready for public release.

## Install

Not on PyPI yet:

```sh
uv tool install git+https://github.com/rzadevv/schem2net
```

In a checkout, run `uv sync`.

## Usage

```sh
schem2net extract board.pdf -o board.ir.json   # JSON netlist
schem2net export board.pdf --to kicad-net      # KiCad netlist (board.net)
schem2net export board.pdf --to bom            # parts grouped by value (board.bom.csv)
schem2net export board.pdf --to spice          # SPICE netlist to start a simulation (board.cir)
schem2net report board.pdf                     # nets drawn over the pages (board.html)
schem2net schematic board.pdf                  # editable KiCad project (board-kicad/)
schem2net diff old.pdf new.pdf                 # parts and connections that changed
schem2net extract board.pdf --region 2:10,20,150,100   # part of page 2, in mm
```

`export` also accepts the JSON from `extract`. The KiCad netlist imports into the
PCB editor; the PDF has no footprints, so assign them there.

`report` lists what is worth checking, likeliest wrong first: nets joined on weak
evidence, guessed pin numbers, pins on no net, labels on no wire. Click an entry to
zoom to it, or a net to highlight it. `--no-pdf` leaves out the page images for a
smaller file. The JSON carries the same information.

`schematic` writes one KiCad sheet per PDF page, with parts and wires where the PDF
drew them. KiCad reads back the same netlist that was extracted.

`diff` matches parts by designator and nets by the pins they share, so a renamed
net is not reported but a pin moving to another net is.

### Part libraries

ICs are often drawn with pin names only, or with many pins stacked under one. With
an indexed library, those pins are numbered from the matching library symbol:

```sh
schem2net index-library /usr/share/kicad/symbols -o ~/parts   # once
schem2net extract board.pdf --library ~/parts                 # or set SCHEM2NET_LIBRARY
```

Use KiCad's installed symbols or
[kicad-symbols](https://gitlab.com/kicad/libraries/kicad-symbols). For Eagle,
index the maker's `.lbr` files, such as
[SparkFun's](https://github.com/sparkfun/SparkFun-Eagle-Libraries); only pin names
are taken from them, since pad numbers depend on the package. Without `--library`,
no library is read, so a PDF reads the same on every machine.

### Exit codes and limits

| Code | Meaning |
|---|---|
| 2 | No supported tool drew the PDF. |
| 3 | No part was found on any page. With `--strict`, also when any page could not be read. |

Nothing is written in either case. Files over 1,000 pages are refused. A page with
more than 1.5 million visited drawing objects or excessive nested forms is reported
as failed and the rest are still read. Ingestion and drawing analysis each have a
twenty-minute budget on POSIX main threads. Native PDFium calls can delay timeout
handling; these are not hard process limits, and threads and Windows have no
interval timer.

## MCP server

```sh
uv tool install "schem2net[mcp] @ git+https://github.com/rzadevv/schem2net"
schem2net serve-mcp board.pdf
```

Serves one design over stdio with read-only tools: `list_components`, `get_net`
(by name or by pin, such as `U3.14`), `pins_of`, `trace` (through series
passives), `low_confidence`, `issues` and `bom`.

## Benchmark

Each corpus pairs published schematic PDFs with a true netlist: from the KiCad
project itself, the netlist an Altium PDF carries, the Eagle or EasyEDA source, or
the board file. Building corpora A, B, D and F runs KiCad in Docker.

```sh
make bench             # A: KiCad
make bench-b           # B: Altium, from the drawing only
make bench-c           # C: SparkFun, Eagle
make bench-d           # D: Olimex, KiCad and Eagle
make bench-e           # E: EasyEDA
make bench-f           # F: OrCAD
make bench-schematic   # round-trip corpus A through KiCad projects
```

Each target fetches its corpus on first use and scores the dev split. [docs/benchmark.md](docs/benchmark.md)
covers the corpora, splits and metrics, and [docs/pipeline.md](docs/pipeline.md)
explains how extraction works.

## Development

```sh
make test
make lint
```

## License

Apache-2.0, see [LICENSE](LICENSE).

The bundled learned assets still need a complete provenance and distribution
review. See [the asset inventory](docs/learned-assets.md) before publishing a
distribution containing them.
