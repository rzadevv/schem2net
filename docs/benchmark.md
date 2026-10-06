# Benchmark

## Corpora

| Corpus | Source | Ground truth |
|---|---|---|
| A | Open KiCad projects rendered with `kicad-cli` (KiCad 10) | Netlist exported by `kicad-cli` |
| B | Altium schematic PDFs published in open hardware repositories | The netlist the PDF carries, checked against the board file |
| C | SparkFun schematic PDFs drawn in Eagle | The Eagle `.sch` in the board's repository |
| D | Olimex schematic PDFs, KiCad and Eagle, held out | The schematic the PDF sits beside |
| E | EasyEDA schematic PDFs, Std and Pro | The EasyEDA source the PDF sits beside |

Manifests (`bench/corpus_*.toml`) store references only: a repository URL and
commit, or a demo that ships with KiCad.

Corpus A PDFs are rendered without property popups and hierarchy links, so the
extractor sees only the drawing.

Corpus B PDFs are used as published. Altium's Smart PDF export stores the
schematic's own netlist in the bookmarks, and every PDF in the corpus has one;
it is the ground truth. The board file (`.PcbDoc`) from the same folder is
read with KiCad's Python inside the benchmark Docker image as a cross-check,
written to `board.net`. The two agree on at least 95% of pins for most
boards. Where they do not, the board has usually moved on or is unfinished,
so the board is only used when a PDF carries no netlist.

A PDF and a board were kept as a pair only when at least 95% of the board's
designators appear in the PDF's text. One board per project, so revisions of
one design do not end up on both sides of the split.

Because the truth comes from the PDF, reading it back scores 1.0. Corpus B is
meant for `--drawing-only`, which ignores the embedded netlist and measures
extraction from the drawing.

Corpus C pairs the schematic PDF on a SparkFun product page with the `.sch`
in the board's repository, taken at the last commit before the PDF was made.
`eagle.py` reads the netlist from the `.sch`, mapping each pin to the pad of
its package, which is what the PDF numbers. A pin on several pads is printed
with its first pad and a count, as in `1*56`, so the truth holds it as that
one pad. Pin names are kept too, so a pin drawn with its name and no number
still scores. A product page sometimes links
the schematic of a related board, so each pair was checked: the `.sch` wires
must land on the PDF's when the sheet is laid over the page, and a PDF linked
from several projects stays only with the board it was made from. 138 pairs
remain. Each part also keeps its device set's name (JUMPER-SMT_2_NO,
CRYSTAL-32MHZ), so the scorer knows what kind of part it is. Fifteen corpus C truth
files written before the one-pad rule listed every pad of such pins; they were
written again from their `.sch` files.

Corpus D is held out: nothing was tuned on it, and it only measures how
results carry over to another maker's boards. Olimex keeps each board's
published schematic PDF in its repository, beside the schematic it was printed
from, KiCad or Eagle; one revision of each board is used. Boards in KiCad's old
`.sch` format are left out, since current kicad-cli cannot read them for the
truth. Its first run found that KiCad 7 and 8 PDFs, which draw text as strokes,
were taken for board prints and skipped; they are read now.

Corpus E pairs EasyEDA schematic PDFs, as EasyEDA names its exports
(`Schematic_<project>.pdf`, `SCH_<sheet>.pdf`), with the source kept in the same
GitHub repository: a Std `.json` or a Pro `.epro`. A pair is kept when at least
90% of the source's designators are in the PDF's text, and copies of one PDF
count once; 30 designs remain. `easyeda.py` reads the netlist. A Std source
stores drawing, not nets, so wires, pins, net flags and labels that share a point
are joined, as EasyEDA does, on the file's exact coordinates. A Pro project names
the net of every wire; its parts' pins are placed from their symbols.

Eagle draws most text with its own stroke font, and some PDFs carry text as
filled outlines. `schem2net build-font c` learns the shapes of both kinds of
letters from the corpus C dev split: the `.sch` sheet is laid over the page by
the wires both share, each line of text is paired with the `.sch` text of the
same length placed at that spot (net labels, names and values, symbol text,
pin names and pad numbers), and the tables are written to
`profiles/eagle_font.json` and `profiles/eagle_fills.json`. Test boards are
never used.

## Roles for pages printed in black

`schem2net build-roles` learns what each path and text is from the colour pages
of every corpus's dev split. The colours are the labels: a path in the wire
colour is a wire, a text in the label colour a label. No truth netlist is used,
and test boards are never read. It needs scikit-learn, one of the dev
dependencies; the trees are written to `profiles/roles.npz`.

To see how pages printed in black fare, recolour a dev PDF's ink to black and
read it again. With models learned without the board in question, dev pages
keep this share of their colour pin accuracy: Eagle 98%, KiCad 78%, Altium
50%. Before, a black page read as nothing. Altium loses most on text: net labels
and pin names look much alike without their colours.

## Designator model

`schem2net build-designators` learns which texts name parts, from every corpus's
dev split. Each design is read as usual up to the point where designators are given
out; there each text's features are taken (what it says, where it sits against the
nearest part and the wires, what was drawn just before and after it) and the truth
netlist gives the label: a text that is a part's reference, or one with a unit
letter, is a designator. A string written more than once in a design, such as C1
naming both a capacitor and a transistor's pin, is left out, as its label is not
known. The truth is used for nothing else, and test boards are never read. One
model is learned per generator and written to `profiles/designators.npz`.

Dev results in the README are measured with models learned without the board being
read: the dev designs are split in four by a hash of their names, and each quarter is
read with the model learned from the other three. `schem2net bench` on the dev split
reads with the stored model, which has seen those designs, so its dev figures run a
little high; test figures are not affected.

## Part library

Results are read with part libraries indexed (`schem2net index-library`): KiCad's,
from the kicad-symbols repository at commit e1bb0a65 (2026-10-04), and
SparkFun's Eagle libraries, from SparkFun-Eagle-Libraries at commit 2354dae
(2024-08-23). Libraries carried by the corpus projects are never read: a part from
one of them keeps what its drawing shows. Olimex's own libraries are not indexed,
so corpus D shows what is read without the maker's library.

## Splits

Each project is assigned to `dev` or `test` by a hash of its name, so the
split cannot drift. Corpus A holds out 10%, corpora B and C a third. Tune on
`dev`.
Report `test`.

```sh
schem2net bench a --split dev
schem2net bench a --split test --json results.json
```

## Metrics

Nets are sets of `(refdes, pin)` pairs. Predicted nets are matched one-to-one
to true nets by maximising Jaccard overlap (Hungarian algorithm). Nets with a
single pin in the ground truth are not scored.

| Metric | Meaning |
|---|---|
| `pin_accuracy` | Share of pins placed in the matched net. Primary metric. |
| `signal_pin_accuracy` | The same, excluding power and ground nets. |
| `net_exact` | Share of true nets reproduced exactly. |
| `connection_precision`, `connection_recall`, `connection_f1` | Over pairs of pins that share a net, excluding power nets. |
| `component_precision`, `component_recall` | By reference designator. |
| `value_accuracy` | Component values, ignoring case and spaces. |
| `flag_recall` | Share of wrong nets that were flagged low-confidence (below 0.8). |
| `flag_precision` | Share of flagged nets that were actually wrong. |
| `perfect_designs` | Share of designs with every net correct. |
| `silent_error_rate` | Share of pins that are wrong with nothing flagging them: on a net of full confidence and named by no issue. What a user cannot catch. |
| `pin_flag_recall` | Share of wrong pins that something flags. |
| `review_items_per_100_pins` | Things a reviewer is handed: each doubtful net and each issue naming pins counts once, per 100 pins. |
| `review_precision` | Share of those that point at something wrong: a doubtful net that is wrong, an issue one of whose pins is wrong. |
| `designs_without_silent_errors` | Share of designs whose every wrong pin is flagged. |

Corpus totals are summed over pins, not averaged over designs.

Accuracy alone says little about whether a netlist can be used: a board 95% right
whose errors no one can find is worse than one 90% right whose doubtful pins are
all marked. So each wrong pin is also asked whether anything flags it: a net of
low confidence, or an issue naming the pin, such as a pin number the drawing does
not show and the extraction guessed.

A pin read by its name, because its number is hidden, counts as the pin of that
name when the name is unique on its part. kicad-cli writes a pin's function as its
name and number, as in `D_1` for pin 1 named D, so the name alone counts as well.
A name is also taken as it is drawn, without the markup that puts a bar over it:
KiCad's `~{CS}`, Eagle's `!CS` and Altium's `C\S\` are all drawn CS.

Values match ignoring spaces, case and an ohm sign, which a drawing often leaves
off (10kΩ drawn 10k). Some designs keep a library name in the value field, such as
R_2k_0402 drawn as 2k, or leave the value unprinted; those count as misses. A part
whose truth gives no value ("~", as every part of corpus B and many Eagle parts
have) is not scored for its value.

Swapping the two pins of a resistor, non-polarised capacitor, inductor,
ferrite bead, fuse, crystal, solder jumper or two-pin push switch is not counted
as an error: the circuit is the same either way, and a drawing with hidden numbers
cannot tell its ends apart. These parts are recognised by their library symbol or
Eagle device set (a name with jumper, crystal, resonator, fuse, ferrite or a
momentary switch in it), or by designator (R, C, L, FB, F) when the symbol is
named after a value or package; their two pins may be numbered anyhow (1 and 3,
P$1 and P$2). A two-pin connector is not among them: which end is which matters. Symbols whose names mark them as
polarised (`CP`, `C_Polarized`, electrolytic, tantalum) are not treated this
way. Nets are first paired without the pins of these parts, so a board full of
decoupling capacitors turned the other way round cannot pair its supply nets
the wrong way.

Power nets are recognised by name: names starting with `+` or `-`, voltages
such as `3V3`, `VCC`, `VDD`, `VSS`, `VBUS` and anything containing `GND`.

## Schematic export

`schem2net bench-schematic a --split all` writes every design as a KiCad
project, has kicad-cli read its netlist back and run ERC, and scores that
netlist against the extraction. A score of 1.0 means the schematic connects
exactly as extracted.

| Corpus | Designs | Read back exactly | No ERC errors |
|---|---|---|---|
| A, KiCad | 66 | 64 | 38 |
| B, Altium | 43 | 41 | 6 |

The designs not read back exactly have two parts with the same designator,
which KiCad joins pin by pin. Most ERC errors are pins the extraction left
unconnected (651 in corpus A), then wires that end at nothing (188). For
comparison, ERC ran on 31 of the original corpus A projects and passed on 16.

## Known gaps in the ground truth

Some connections exist in the design but are not visible in the PDF:

- Hidden power pins that connect to a net by name.
- Label scope set in project settings. For example, Altium's net identifier
  scope decides whether same-named labels on different sheets connect; the
  Altium profile assumes they do unless sheets are nested.
- Parts that are not fitted in a variant.
- Pin numbers that the library hides, and stacked pins that print one number.

Apart from the Altium label scope, these are not handled.
