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

Pin numbers the PDF does not show, and pins stacked under one drawn pin, are taken
from KiCad's symbol libraries, and the names of unnamed pins from Eagle's, once
they are indexed (see Part libraries). Hidden
power pins that stand apart from every drawn pin are not handled yet.

## Pages that are not schematics

PDFs often bundle board prints, assembly drawings and parts lists with the
schematic. Schematic pages carry roughly one text object per one to three
paths. Board prints draw their lettering as strokes and have almost no text,
and tables are almost all text, so pages far outside that range are skipped
and reported as `board_page` or `table_page`. A page that looks like a board but
has wires in the generator's colour and text besides is a dense schematic, and
is read.

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
power symbol sits on a pin. A line whose free end is inside the body's box is
drawing, except that a closed outline the line starts on counts by its shape: an
amplifier's supply pins leave the slanted sides of its triangle and end within
its box. The two strokes of a "+" mark cross at their middles; neither is a pin.
Capacitors set a grid step apart may have plates longer than the step, each plate's
end on the middle of its neighbour's, and a plate then looks like a pin. Where
drawing order keeps neighbouring symbols apart, as in KiCad and Altium, a line that
runs on from another and that a pin starts on square is taken for body.

Symbols are groups of graphics that touch, except through a pin's free end.
Two one-pin pieces facing each other on one axis are joined, which covers
capacitor plates. Where parts are drawn one at a time, as in EasyEDA, pieces drawn
interleaved and close together are one part: a MOSFET's gate stands apart from its
channel. Eagle draws by layer, so there neighbours' drawings interleave.

Designators are paired with symbols one to one, nearest first overall. A value
can look like a designator: "L298" by a driver's box. Resistors, capacitors,
inductors and fuses have few pins, so their prefixes cost more by a part of many.
Where the designator is drawn first, as in KiCad, the first text after a part names
it whatever its form, GPIO1-1 or USB-Serial/JTAG1: when it lies clear of the part,
when the part's own texts hold no usual designator, and never ahead of one at the
same distance, for a pin name may be drawn first too. A lone letter never names a
part.

A learned model also weighs every text (see the benchmark notes): how likely it is a
designator, from what it says, where it sits and what was drawn around it. A text
the model finds unlike a designator costs more, as a value such as A20 or Z80 does,
and a word of no usual form that it is sure of may name a part.

A part's value is the first text drawn after its designator where the generator
draws each part's texts in turn, as KiCad does, and the text drawn right before it
where values come first, as in EasyEDA; elsewhere values are paired with parts one
to one, nearest first overall, so a part does not take its neighbour's. Where
designators have a colour of their own, values share it, so a net name or pin text
in another colour is never one.
A pin's name or the number read for one of its pins is no value, nor is a single
sign beside a pin, as a diode's A and K, nor a note of more than four words. Two texts that are each a whole value with its unit, as 0.1uF
beside 2.2nF, are two parts' values however close they are drawn, and a line of
Eagle's stroke text that reads as such values side by side is split per part.

A pin number usually sits beside its pin; some libraries centre it on the pin's
line instead. Card sockets and headers may mark only the first pin of each row,
past its end or as pin 1 beside it, or the first and last: an evenly spaced row of
unnumbered pins is then numbered from its marks, counting up from a single one.
Transistors often hide their numbers, and their pins are then known by role: the
base or gate is the pin square to the other two, leading to the middle of a bar;
the emitter or source is the one nearer the arrowhead along the drawing, where a
body diode, which joins both, is not taken for the arrow; a bipolar transistor
leaves its bar on slants. A potentiometer or a three-way jumper with hidden numbers
has two ends facing apart and a wiper or common pad square to them: that is pin 2,
and a potentiometer's ends count as a two-pin part's do. A solder jumper's ends lie
in pads alike, and which is 1 depends on how it was turned. Read by position they
come out right only about three times in four, and a wrong end joins its nets
wrongly, which costs more than an end left unnumbered; so they stay unnumbered.
A pin may end inside a small filled pad,
as a solder jumper draws them, and belongs to it; so does a line from one such pad
into another, with any pad it crosses, as a jumper's bridge does. Running from pad
to pad, a bridge is no transistor's bar.

## Sheets and buses

Each page's hierarchical path comes from its title block. A sheet box on a
parent page is found by its file name, which sits just below the box; the top
of a text's box is the font's ascent, so it may cross the box's line. The child
page's path is the parent's path plus the sheet name. A sheet pin is named by
the text inside the box level with its flag, and joins the hierarchical label
of the same name on the child page. KiCad sets a name against its flag by its
width at full size, but draws subscripts small, so a name with a subscript ends
short of its flag by what the subscript lost; sheet pins and hierarchical
labels allow for that gap. A hierarchical label of a bus is written in the bus
colour, beside its flag.

Buses join their member nets. A vector bus `D[0..7]` is matched by position
where it crosses into a sheet, so `D[8..15]` on the parent can feed `D[0..7]`
on the child. A group bus `I2C{SCL SDA}` is matched by member name. When a
group names an alias defined outside the drawing, its members are taken from
the labels that use its prefix on any sheet: a sheet that only passes the bus on
to another names none of them itself.

## Part libraries

ICs are often drawn with pin names and hidden numbers, and pins of one name are
stacked: an FPGA's hundred ground balls lie under one drawn pin, which shows one
number at most. KiCad's own symbol libraries hold every pin. `schem2net
index-library DIR` reads them, as KiCad installs them or from their repository,
into a file in the user's cache; without it, nothing changes.

A KiCad part whose value names a library symbol, as values do by default, is
checked against it: the symbol, in each of its units and eight orientations, is
laid over the drawing so that every drawn pin end meets a library pin end, and
the numbers and names already read must agree, but for a tenth that the
designer renumbered, which keep their own. A unit named by the designator's
letter is the only one tried. The fit must also show most of the unit's visible
pins and must be the only one: a two-pin part that fits turned either way is left
alone. Each drawn pin then takes the numbers of every library pin under it. A
symbol redrawn in the library since the design no longer fits; if every number
read is still its own, the hidden pins of the same name stacked under each are
added. Libraries a project carries with it are not read.

A value may be read wrongly, a pad number taken for it say; a part of three pins
or more that fits nothing by its value is looked up by the texts printed around
it, and the fit decides. Two pins make too common a shape to go on.

Eagle libraries (.lbr) are indexed the same way: each device is found by the
values Eagle prints for it, its device set's name filled in with technology and
device, and each gate is a unit. An Eagle part's pads depend on its package,
which the drawing does not show and which libraries rename between versions, so
only the names of the library's pins are taken, for pins read with neither
number nor name. The same holds for any part whose packages number its pins
apart.

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
and diodes from the cathode; Eagle's diode packages name their pads C and A. A
printer may draw a diode's triangle as three lines. Altium parts are placed horizontally with pin 1
on the left and usually turned counter-clockwise, so upright parts count from
the bottom, and most Altium diode libraries make the anode pin 1.

A net label text inside a small outline is a port. Unless the design nests
sheets, ports and net labels connect their name on every sheet.

Power port names use the net label colour. Ground ports usually have no name
and are recognised by their stacked bars, centred one above another, or their
triangle. In Eagle and EasyEDA, whose pins and bodies share a colour, the stem
of the GND sign reads as a pin, and the shape still decides; in KiCad the same
sign is Earth, so there a pin keeps it a part. A ground drawn in pieces takes the
name another piece beside it took. A power symbol's name sits past its end away
from the wire, never beside its stem, where the number of the pin it sits on may
be. Designers often
change the wire colour, so each page's wire colour is learned from the lines
that end on pin ends. Junctions may be drawn as rings, and wires crossing
without a connection may jump over each other with a small arc, which is read
as a straight wire. Pages are scaled to fit, so buses are told from wires by
relative thickness. Text drawn in invisible mode, such as the pin markers of a
Smart PDF, is not part of the drawing and is ignored, with one exception: KiCad
7 and 8 draw each letter as strokes and lay an invisible copy of the text over
them for search. An invisible text with ink of its own colour under it, a
stroke or more per letter spread along it, is that copy: it is read as the
text, and the strokes under it are dropped as its letters.

Eagle writes most text with its vector font, as strokes, so `strokes.py` reads
it back: strokes drawn one after another in one style are cut into lines and
letters, and each letter is matched against a table of known shapes, in a frame
set by its line's baseline and height. A curve drawn as one polyline stays in
one letter. Eagle 9 has a second vector font with rounder letters; the table
holds both. Text in a proportional font, and all text from some PDF printers,
arrives as filled outlines instead, one path per string; `fills.py` splits each
into letters by where the outlines overlap and compares a coarse raster of each
letter, with its width and height against the baseline, to a second table.

Editors snap wires to a grid: Eagle to 2.54 mm, KiCad to 1.27 or 0.635 mm. A
sheet printed to fit the paper keeps that pattern at another spacing, so
`grid.py` finds the spacing all wire ends agree on and scales the page back to
the size it was drawn at before reading it; the sizes the rest of the pipeline
expects, pin lengths and text gaps, then hold. A grid also fits at every
spacing that divides it, so a page whose ends fit one of the usual grids as
printed is taken as 1:1; otherwise the fit nearest 1:1 is taken.

A PDF may split one string into pieces, at spaces, subscripts or overbars. Pieces
drawn in turn in one colour, side by side on one line, are joined; words of one
size on one line share their tops or their baseline. A pin's name centred on the
pin and its number set above it are drawn in turn too, but on two lines.
PDFium reads a dash that ends a line of text as a hyphen breaking a word and
returns a control character for it; it is read back as a dash, so `CLK-` keeps
its name.

Letters that only size tells from their capitals (c, o, s, v, w, x, z, and
in sans fonts I and l) take the case of the rest of their word, so one net name
is not read two ways. Cross-reference labels print the sheet a net goes on to
after its name, as in `MCLK/2`; that suffix is dropped when it names another
sheet of the document. A supply's name is anchored at one end and may overhang
its arrow; a name in line with the symbol is preferred, then one that runs
across the pin, past the end away from the wire.

Eagle's libraries place a part's name above its box, so a text inside the box,
however much it looks like a designator (A0, U3), is taken as a pin name first,
and one beside a pin outside it as a pad number. Eagle draws layer by layer,
values before names, so a text that looks like a designator but is drawn among
values (A20 among 10k and 3.3V, with no other designator around it) is taken for
a value when a name sits as near. Drawn among values, a long word laid along a
wire, such as a resistor array's value, is no net label either; one value written
for several parts in turn counts once. Eagle takes any name for a part, and designers
name jumpers and connectors by what they do: I2C, PWR, LCD_CON. A part left without
a designator takes the nearest unused word beside it that is not one of its pin
names, a value, a number or a note. A letter after a designator's number marks a
unit, as in U5A, but I2C is a name: a designator of no usual prefix keeps its
letter unless the document shows it in other units too, as CM1A and CM1B.

Names, values, pin names and pad numbers
share one colour, so their roles come from where they sit; a text in that colour
names one pin at most. A pin name is set a fixed distance in from the pin's end,
measured to where the text is placed, so a narrow last letter, as in INT1, leaves
a little more room to its ink. Net labels are the
names inside an outline that meets a wire, or, in older designs, names laid
along a wire just above it; a part value over a passing wire is not one. Many Eagle symbols draw no pin
lines: a wire ending on a part's outline is a pin there, numbered by the text
beside it. Eagle hides the pad numbers of small parts, so a designator or a
value such as 10k beside a pin is never taken for its number. A connector's box
and its pins are often drawn apart, and are joined when drawn one right after
the other, close together, or when the pins run in across the box's edge. The
sheet frame is set aside first, so nothing joins it.

EasyEDA exports through jsPDF, one unit of 10 mil to one PDF point, so its
pages are read at that fixed scale. Designators and values are navy; pin texts
take their part's colours, so their roles come from position, as in Eagle. A net
port flag set beside its name works like a power symbol: a small shape on a wire
that names the net, joined at the corner its wire ends on, or set straight on a
pin's tip with no wire, joined at the corner on the tip; flags stacked edge to edge stay apart, each naming its own net. A
flag's name may look like a designator, such as A15, but designators are navy and
the name is not. A net label may also be plain text set at a wire's open end,
level with the wire and running on past it; an end that meets a pin is no open end,
and the text there is the pin's number. Newer exports mark where a label meets
its wire with a grey dot; the name nearest the dot labels that wire, wherever it is
set beside it. A ground sign is a stem and separate
bars drawn in turn, joined into one symbol.

EasyEDA draws each part whole: its value, then its designator, then its drawing,
with each pin's name, number and line in turn; EasyEDA Pro writes the designator
after the drawing. So of two navy texts drawn back to back the first is the value,
however much it looks like a designator ("Z80" over "U1"), and a pin whose ends both
meet other lines tip to tip belongs to the part drawn with it. A part's units are
numbered after a dot, as in U3.1. A section frame drawn next to a part inside it
is not that part's box: a box's pins connect outside it, and a part whose pins all
end inside the frame is the frame's no more than any other. A net label is its
text and a small cross where it meets the wire, by the text's corner and so as
near the next label's text as its own; the cross takes the text drawn right
before it or right after it, whichever way round the page draws the labels whose
name is plain by distance.

A PDF printed from a browser or through a PDF printer does not say which tool drew
it. The drawing still does: the profile whose wire colour is there and whose
colours cover most of the ink is taken, and inks the printer shifted a step or two
are set back to the profile's own, lines to drawn roles' colours and text to text
roles'. Such a page has lost its exporter's scale, so its scale comes from its
wire grid. A grid fits a page at half its true scale as well as at it, when wires
keep to the half grid; rows of pins tell which, as nearly every library sets pins
2.54 mm apart, so a page whose pins step twice or half that is read again at the
pitch's scale.

## Pages printed without colour

The profiles read roles from colour, so a page printed in black or grey (every
ink a grey) is first given colours back. `roles.py` predicts the role of each
path, wire, bus, pin, symbol graphics and so on, from its shape, how its ends
meet other paths and the paths drawn just before and after it. A second pass
looks again with the first guesses at the roles of what each path touches: a
short line is a wire if wires carry on from it, a pin if it ends on a body. Then
the role of each text, label, field or pin number, is predicted from what it says
and what it sits on: a wire running along it, a symbol body around it, an
outline, the end of a pin. Each path and text takes its role's
colour and the page is read as usual. The models are gradient-boosted trees,
three per generator, learned from colour pages (see the benchmark notes) and
stored as node arrays in `profiles/roles.npz`; reading them needs only numpy.

Designers can change the colour theme, so a label may come in a colour the
profile does not know. Such texts get their role from the same text model, with
everything in a known colour kept as it is: a string the PDF splits into pieces
is judged whole, and every piece takes its role. A net label has no drawing of
its own, so a text with lines of its colour right by it, other than the wire it
lies along, is not taken for one: the net class name on a differential pair
directive sits beside the directive's mark, just above the wire.

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
