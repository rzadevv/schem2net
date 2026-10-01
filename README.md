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
- Other generators are not supported yet.

| Corpus | Split | Designs | Pins | Pin accuracy | Connection F1 |
|---|---|---|---|---|---|
| A, KiCad | Dev | 57 | 25,608 | 0.88 | 0.94 |
| A, KiCad | Test | 9 | 2,863 | 0.93 | 0.91 |
| B, Altium, drawing only | Dev | 30 | 6,677 | 0.87 | 0.88 |
| B, Altium, drawing only | Test | 13 | 3,819 | 0.86 | 0.84 |

## Install

```sh
uv sync
```

## Usage

```sh
schem2net extract board.pdf -o board.ir.json   # PDF to JSON netlist
schem2net export board.pdf --to kicad-net      # KiCad netlist, board.net
schem2net export board.pdf --to bom            # parts grouped by value, board.bom.csv
schem2net report board.pdf                     # nets drawn over the schematic, board.html
```

`export` also takes the JSON written by `extract`. The KiCad netlist imports
into the PCB editor; footprints are not in the PDF, so assign them in KiCad.

The report colours each net, circles pins of low-confidence nets in red and
unnumbered pins in orange. Click a net in the list to highlight it.

## MCP server

```sh
pip install "schem2net[mcp]"
schem2net serve-mcp board.pdf
```

Serves one design over stdio with read-only tools: `list_components`,
`get_net` (by name or by pin, such as `U3.14`), `pins_of`, `trace` (through
series passives), `low_confidence` and `bom`.

## Benchmark

Ground truth comes from open KiCad projects: `kicad-cli` renders each one to a
PDF and exports its netlist, and the extractor is scored on the PDF. Building
the corpus needs Docker.

```sh
make corpus     # fetch and render corpus A (KiCad)
make bench      # score the extractor on its dev split
make corpus-b   # fetch corpus B (Altium PDFs and their boards)
make bench-b    # score extraction from the drawing on its dev split
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
