# Pipeline

Extraction runs in stages. Each stage only reads the output of the ones before
it, and the final result is a JSON document (`schem2net/ir.py`) that exporters
and the benchmark read.

| Stage | Work | Code | Status |
|---|---|---|---|
| 1 | Detect the generator and page kind | `ingest.py` | done |
| 2 | Read paths and text in millimetres, top-left origin | `pdf.py` | done |
| 3 | Drop duplicates, rejoin split text | `scene.py` | done |
| 4 | Sort primitives into wires, symbol graphics, labels and fields | `scene.py`, `strokes.py`, `fills.py`, `grid.py` | KiCad, Altium, Eagle |
| 5 | Join wires at shared ends and junction dots | `nets.py` | done |
| 6 | Find pins, group symbols, attach designators and pin numbers | `symbols.py`, `fields.py` | KiCad, Altium, Eagle |
| 7 | Attach labels and power symbols, follow sheets and buses | `nets.py`, `buses.py` | KiCad, Altium |
| 8 | Build nets, check them and score confidence | `nets.py` | done |
| 9 | KiCad netlist and schematic, BOM, HTML report, MCP server | `export.py`, `kicad_sch.py`, `report.py`, `mcp_server.py` | done |

Not handled yet: hidden power pins and pin numbers, which the PDF does not show.

## Pages that are not schematics

PDFs often bundle board prints, assembly drawings and parts lists with the
schematic. Schematic pages carry roughly one text object per one to three
paths. Board prints draw their lettering as strokes and have almost no text,
and tables are almost all text, so pages far outside that range are skipped
and reported as `board_page` or `table_page`.

## Netlists carried in the PDF

Altium's Smart PDF export can store the netlist in the bookmarks: every net
with its pins, written as `C1-2`. When a PDF has these, `bookmarks.py` reads
them and the drawing is not analysed. `schem2net bench --drawing-only` turns
this off to measure extraction from the drawing alone.

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
conventions.

KiCad draws each symbol's texts right after its graphics, reference first, so
drawing order ties designators and power names to their symbols and rejoins
symbols drawn in several pieces. Wires take their net class colour, but are
all drawn in one run.

Altium draws pins in their own colour, so a pin's inner end is the one that
meets body graphics. Some libraries draw pins in the body colour; those are
taken only where a wire meets them. When both ends look alike, drawing order
decides: graphics separated from the pin by a designator belong to another
symbol, such as a ground port placed over the pin's end.

Small parts often hide their pin numbers. KiCad parts then count from the top
and diodes from the cathode. Altium parts are placed horizontally with pin 1
on the left and usually turned counter-clockwise, so upright parts count from
the bottom, and most Altium diode libraries make the anode pin 1.

A net label text inside a small outline is a port. Unless the design nests
sheets, ports and net labels connect their name on every sheet.

Power port names use the net label colour. Ground ports usually have no name
and are recognised by their stacked bars or their triangle. Designers often
change the wire colour, so each page's wire colour is learned from the lines
that end on pin ends. Junctions may be drawn as rings, and wires crossing
without a connection may jump over each other with a small arc, which is read
as a straight wire. Pages are scaled to fit, so buses are told from wires by
relative thickness. Text drawn in invisible mode, such as the pin markers of a
Smart PDF, is not part of the drawing and is ignored.

Eagle writes most text with its vector font, as strokes, so `strokes.py` reads
it back: strokes drawn one after another in one style are cut into lines and
letters, and each letter is matched against a table of known shapes, in a frame
set by its line's baseline and height. A curve drawn as one polyline stays in
one letter. Eagle 9 has a second vector font with rounder letters; the table
holds both. Text in a proportional font, and all text from some PDF printers,
arrives as filled outlines instead, one path per string; `fills.py` splits each
into letters by where the outlines overlap and compares a coarse raster of each
letter, with its width and height against the baseline, to a second table.

Eagle snaps wires to a 2.54 mm grid. A sheet printed to fit the paper keeps that
pattern at another spacing, so `grid.py` finds the spacing all wire ends agree
on and scales the page back to the size it was drawn at before reading it; the
sizes the rest of the pipeline expects, pin lengths and text gaps, then hold.

Names, values, pin names and pad numbers
share one colour, so their roles come from where they sit. Net labels are the
names inside an outline that meets a wire. Many Eagle symbols draw no pin
lines: a wire ending on a part's outline is a pin there, numbered by the text
beside it. A connector's box and its pins are often drawn apart, and are
joined when drawn one right after the other, close together.

## Confidence

Every join is recorded with its kind. A net's confidence is the weight of its
weakest join: shared ends and junction dots are trusted fully, wire ends
landing on the middle of another wire without a dot less so. A net with a
single pin is flagged.

Checks then look for things that cannot be right, report them as issues, and
cap the confidence of the nets involved:

| Issue | Meaning | Net confidence |
|---|---|---|
| `power_nets_merged` | two power names on one net, such as GND and 3V3 | capped at 0.4 |
| `duplicate_pin` | a pin number used twice in one unit of a part | capped at 0.6 |
| `dangling_wire` | a wire end touching nothing and no no-connect flag | 0.6 |
| `unconnected_pin` | a pin on no net, without a no-connect flag | |
| `connected_no_connect` | a pin flagged no-connect that is connected | |
| `designator_without_part` | a designator that no part claimed | |
| `unattached_label` | a net label on no wire or pin | |
| `unnumbered_pin` | a pin whose number was not found | |

A pin drawn in several units of one part, such as a supply pin, is one pad, so
its units are joined.

## Checking extraction

`schem2net draw file.pdf --page N` writes the primitives of one page as SVG.
It should look the same as the PDF. If it doesn't, the bug is in stage 2.
