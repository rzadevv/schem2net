# Pipeline

Extraction runs in stages. Each stage only reads the output of the ones before
it, and the final result is a JSON document (`schem2net/ir.py`) that exporters
and the benchmark read.

| Stage | Work | Code | Status |
|---|---|---|---|
| 1 | Detect the generator (KiCad, Altium, OrCAD, Eagle) and page kind | `ingest.py` | done |
| 2 | Read paths and text in millimetres, top-left origin | `pdf.py` | done |
| 3 | Split, merge and snap segments to the grid | | |
| 4 | Separate wires from symbol bodies, pins and frames | | |
| 5 | Join wires at contacts and junction dots | | |
| 6 | Group symbols, attach reference designators and pin numbers | | |
| 7 | Attach net labels and power symbols, merge across pages | | |
| 8 | Build nets, score confidence, run consistency checks | | |
| 9 | Export KiCad netlist, BOM, overlay; MCP server | | |

## Coordinates

All primitives use millimetres with the origin at the top-left of the page as
displayed. Page rotation and nested form objects are resolved in stage 2, so
later stages never see PDF user space.

## Checking extraction

`schem2net draw file.pdf --page N` writes the primitives of one page as SVG.
It should look the same as the PDF. If it doesn't, the bug is in stage 2.
