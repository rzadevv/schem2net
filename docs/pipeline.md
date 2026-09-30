# Pipeline

Extraction runs in stages. Each stage only reads the output of the ones before
it, and the final result is a JSON document (`schem2net/ir.py`) that exporters
and the benchmark read.

| Stage | Work | Code | Status |
|---|---|---|---|
| 1 | Detect the generator and page kind | `ingest.py` | done |
| 2 | Read paths and text in millimetres, top-left origin | `pdf.py` | done |
| 3 | Drop duplicates, rejoin split text | `scene.py` | done |
| 4 | Sort primitives into wires, symbol graphics, labels and fields | `scene.py` | KiCad |
| 5 | Join wires at shared ends and junction dots | `nets.py` | done |
| 6 | Find pins, group symbols, attach designators and pin numbers | `symbols.py`, `fields.py` | KiCad |
| 7 | Attach labels and power symbols, follow sheets and buses | `nets.py`, `buses.py` | KiCad |
| 8 | Build nets and score confidence | `nets.py` | partial |
| 9 | Export KiCad netlist, BOM, overlay; MCP server | | |

Not handled yet: hidden power pins, and consistency checks in stage 8.

## Coordinates

All primitives use millimetres with the origin at the top-left of the page as
displayed. Page rotation and nested form objects are resolved in stage 2, so
later stages never see PDF user space.

## Pins and symbols

A pin is a straight line with one end on its symbol's body and the other end
free. The free end is the connection point. An end is on the body if it lands
on the middle of a line, on a corner of a polyline or on a closed outline.
Meeting another line tip to tip is not enough, because that is also how a
power symbol sits on a pin.

Symbols are groups of graphics that touch, except through a pin's free end.
Two one-pin pieces facing each other on one axis are joined, which covers
capacitor plates.

## Sheets and buses

Each page's hierarchical path comes from its title block. A sheet box on a
parent page is found by its file name; the child page's path is the parent's
path plus the sheet name. A sheet pin joins the hierarchical label of the same
name on the child page.

Buses join their member nets. A vector bus `D[0..7]` is matched by position
where it crosses into a sheet, so `D[8..15]` on the parent can feed `D[0..7]`
on the child. A group bus `I2C{SCL SDA}` is matched by member name. When a
group names an alias defined outside the drawing, its members are taken from
the labels that use its prefix.

## Generator profiles

Everything specific to one EDA tool lives in `profiles/<name>.toml`: the
colours of each kind of primitive, pin line limits, and drawing order
conventions. KiCad draws each symbol's texts right after its graphics, so
drawing order ties designators and power names to their symbols and rejoins
symbols drawn in several pieces.

## Confidence

Every join is recorded with its kind. A net's confidence is the weight of its
weakest join: shared ends and junction dots are trusted fully, wire ends
landing on the middle of another wire without a dot less so. A net with a
single pin is flagged.

## Checking extraction

`schem2net draw file.pdf --page N` writes the primitives of one page as SVG.
It should look the same as the PDF. If it doesn't, the bug is in stage 2.
