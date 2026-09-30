# schem2net

Recover netlists from vector schematic PDFs.

Most schematic PDFs from chip vendors and board makers were plotted by an EDA
tool, so every wire, pin and label sits at an exact coordinate. schem2net reads
that geometry and computes connectivity from it instead of guessing from
pixels. Every net gets a confidence score, and accuracy is measured against a
public benchmark.

## Status

Early development. KiCad PDFs work end to end, including hierarchical sheets
and buses. Other generators need their own profile and are not supported yet.

Corpus A:

| Split | Designs | Pins | Pin accuracy | Connection F1 |
|---|---|---|---|---|
| Dev | 57 | 25,608 | 0.82 | 0.92 |
| Dev, single page | 35 | 4,281 | 0.86 | 0.87 |
| Dev, multi-page | 22 | 21,327 | 0.81 | 0.92 |
| Test | 9 | 2,863 | 0.84 | 0.85 |

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
make corpus   # fetch and render corpus A
make bench    # score the extractor on the dev split
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
