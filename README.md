# schem2net

Recover netlists from vector schematic PDFs.

Most schematic PDFs from chip vendors and board makers were plotted by an EDA
tool, so every wire, pin and label sits at an exact coordinate. schem2net reads
that geometry and computes connectivity from it instead of guessing from
pixels. Every net gets a confidence score, and accuracy is measured against a
public benchmark.

## Status

Early development.

- KiCad PDFs work end to end, including hierarchical sheets and buses.
- Altium PDFs exported as Smart PDF carry their netlist in the bookmarks,
  which is read directly. Extraction from the Altium drawing itself works
  for most boards; hidden pin numbers are the main gap.
- Eagle PDFs are read too: text drawn with Eagle's stroke fonts or printed as
  filled outlines, and sheets printed to fit the paper. Accuracy is lower
  than for KiCad and Altium.
- Pages printed in black or grey are read too, with roles learned from colour
  pages; they keep most, not all, of the accuracy of colour pages.
- EasyEDA PDFs, from Std or Pro, are read too. This is early work.
- OrCAD Capture PDFs, printed through a PDF printer, are read in Capture's
  default colours.
- PDFs printed from a browser or a PDF printer, which do not say what drew them,
  are recognised by their colours.
- Other generators are not supported yet.

Dev figures are read with learned models that never saw the design in question,
and KiCad's and SparkFun's part libraries indexed (see `docs/benchmark.md`).

| Corpus | Split | Designs | Pins | Pin accuracy | Connection F1 |
|---|---|---|---|---|---|
| A, KiCad | Dev | 57 | 25,608 | 0.92 | 0.96 |
| A, KiCad | Test | 9 | 2,863 | 0.94 | 0.92 |
| B, Altium, drawing only | Dev | 30 | 6,677 | 0.88 | 0.90 |
| B, Altium, drawing only | Test | 13 | 3,819 | 0.88 | 0.89 |
| C, Eagle | Dev | 96 | 7,038 | 0.76 | 0.72 |
| C, Eagle | Test | 42 | 2,903 | 0.66 | 0.61 |
| D, Olimex, held out | Dev | 24 | 11,745 | 0.78 | 0.73 |
| D, Olimex, held out | Test | 24 | 9,286 | 0.75 | 0.65 |
| E, EasyEDA | Dev | 18 | 2,487 | 0.73 | 0.72 |
| E, EasyEDA | Test | 12 | 1,669 | 0.51 | 0.10 |
| F, OrCAD | Dev | 18 | 13,444 | 0.92 | 0.97 |
| F, OrCAD | Test | 12 | 5,680 | 0.89 | 0.92 |

Accuracy says how much is right; what a user also needs is to know where the rest
is. Silent errors are wrong pins that nothing flags. Review items are the doubtful
nets and the issues naming pins, each one thing to check; precision is the share of
them that point at something wrong.

| Corpus | Split | Silent errors | Wrong pins flagged | Review items per 100 pins | Review precision | Boards with no silent error |
|---|---|---|---|---|---|---|
| A, KiCad | Dev | 0.4% | 0.84 | 4.4 | 0.61 | 0.74 |
| A, KiCad | Test | 1.1% | 0.58 | 3.7 | 0.71 | 0.56 |
| B, Altium, drawing only | Dev | 0.3% | 0.92 | 12.5 | 0.48 | 0.83 |
| B, Altium, drawing only | Test | 2.8% | 0.57 | 6.4 | 0.58 | 0.46 |
| C, Eagle | Dev | 1.0% | 0.70 | 12.7 | 0.77 | 0.67 |
| C, Eagle | Test | 1.0% | 0.70 | 14.4 | 0.81 | 0.71 |
| D, Olimex, held out | Dev | 0.8% | 0.84 | 12.5 | 0.83 | 0.50 |
| D, Olimex, held out | Test | 1.0% | 0.79 | 13.1 | 0.88 | 0.46 |
| E, EasyEDA | Dev | 2.7% | 0.73 | 11.9 | 0.88 | 0.56 |
| E, EasyEDA | Test | 1.5% | 0.77 | 11.8 | 0.87 | 0.58 |
| F, OrCAD | Dev | 0.9% | 0.81 | 8.9 | 0.75 | 0.61 |
| F, OrCAD | Test | 0.8% | 0.89 | 12.3 | 0.86 | 0.58 |

## Install

```sh
uv sync
```

## Usage

```sh
schem2net extract board.pdf -o board.ir.json   # PDF to JSON netlist
schem2net export board.pdf --to kicad-net      # KiCad netlist, board.net
schem2net export board.pdf --to bom            # parts grouped by value, board.bom.csv
schem2net export board.pdf --to spice          # SPICE netlist to start a simulation, board.cir
schem2net report board.pdf                     # nets drawn over the schematic, board.html
schem2net schematic board.pdf                  # editable KiCad project, board-kicad/
schem2net diff old.pdf new.pdf                 # parts and connections that changed
schem2net extract board.pdf --region 2:10,20,150,100   # only part of page 2, in mm
schem2net index-library /usr/share/kicad/symbols      # once: KiCad's symbol libraries
```

`index-library` lets PDFs be read with the pin numbers they hide: an IC drawn
with pin names only, or many pins stacked under one drawn pin, is numbered from
its library symbol when its value names one. Point it at KiCad's installed
symbols or at a copy of https://gitlab.com/kicad/libraries/kicad-symbols. For
Eagle PDFs, point it at the maker's .lbr files, such as
https://github.com/sparkfun/SparkFun-Eagle-Libraries; Eagle parts take only pin
names from them, as their pads depend on the package.

`export` also takes the JSON written by `extract`. The KiCad netlist imports
into the PCB editor; footprints are not in the PDF, so assign them in KiCad.

`schematic` writes a KiCad project with one sheet per PDF page. Parts and wires
sit where the PDF drew them; each part gets a symbol made from its own outline,
and named nets are carried by labels. KiCad reads back the same netlist that
was extracted.

`diff` matches parts by designator and nets by the pins they share, so a
renamed net is not reported, but a pin moving to another net is.

The report draws each net in its own colour over the pages as printed
(`--no-pdf` leaves the pictures out for a lighter file), so what was read can be
checked against the drawing. It lists everything worth checking, grouped, the
likeliest wrong connections first: nets joined on weak evidence, pin numbers the
drawing does not show and that were guessed, pins on no net, labels on no wire.
Click an entry to zoom to it; click a net to highlight it. The JSON says the same:
each issue names the pins it puts in doubt, and each pin says how its number was
found when it was not printed beside it.

## MCP server

```sh
pip install "schem2net[mcp]"
schem2net serve-mcp board.pdf
```

Serves one design over stdio with read-only tools: `list_components`,
`get_net` (by name or by pin, such as `U3.14`), `pins_of`, `trace` (through
series passives), `low_confidence`, `issues` and `bom`.

## Benchmark

Ground truth comes from open KiCad projects: `kicad-cli` renders each one to a
PDF and exports its netlist, and the extractor is scored on the PDF. Building
the corpus needs Docker.

```sh
make corpus     # fetch and render corpus A (KiCad)
make bench      # score the extractor on its dev split
make corpus-b   # fetch corpus B (Altium PDFs and their boards)
make bench-b    # score extraction from the drawing on its dev split
make bench-schematic  # write corpus A as KiCad projects and check them with kicad-cli
make corpus-c   # fetch corpus C (SparkFun Eagle PDFs and their .sch)
make bench-c    # score extraction on its dev split
make corpus-d   # fetch corpus D (Olimex PDFs and their schematics, held out)
make bench-d    # score it
make corpus-e   # fetch corpus E (EasyEDA PDFs and their sources)
make bench-e    # score it
make corpus-f   # fetch corpus F (OrCAD PDFs and their Allegro boards)
make bench-f    # score it
```

See [docs/benchmark.md](docs/benchmark.md) for the corpora and metrics, and
[docs/pipeline.md](docs/pipeline.md) for how extraction works.

## Development

```sh
make test
make lint
```

## License

Apache-2.0
