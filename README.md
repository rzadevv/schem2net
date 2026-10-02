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
- Other generators are not supported yet.

| Corpus | Split | Designs | Pins | Pin accuracy | Connection F1 |
|---|---|---|---|---|---|
| A, KiCad | Dev | 57 | 25,608 | 0.88 | 0.94 |
| A, KiCad | Test | 9 | 2,863 | 0.94 | 0.91 |
| B, Altium, drawing only | Dev | 30 | 6,677 | 0.87 | 0.88 |
| B, Altium, drawing only | Test | 13 | 3,819 | 0.86 | 0.84 |
| C, Eagle | Dev | 96 | 7,038 | 0.64 | 0.61 |
| C, Eagle | Test | 42 | 2,903 | 0.52 | 0.46 |

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
```

`export` also takes the JSON written by `extract`. The KiCad netlist imports
into the PCB editor; footprints are not in the PDF, so assign them in KiCad.

`schematic` writes a KiCad project with one sheet per PDF page. Parts and wires
sit where the PDF drew them; each part gets a symbol made from its own outline,
and named nets are carried by labels. KiCad reads back the same netlist that
was extracted.

`diff` matches parts by designator and nets by the pins they share, so a
renamed net is not reported, but a pin moving to another net is.

The report colours each net, circles pins of low-confidence nets in red and
marks problems the checks found in orange. Click a net in the list to highlight
it.

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
