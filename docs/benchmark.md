# Benchmark

## Corpora

| Corpus | Source | Ground truth |
|---|---|---|
| A | Open KiCad projects rendered with `kicad-cli` (KiCad 10) | Netlist exported by `kicad-cli` |
| B | Altium schematic PDFs published in open hardware repositories | The netlist the PDF carries, checked against the board file |
| C | SparkFun schematic PDFs drawn in Eagle | The Eagle `.sch` in the board's repository |

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
remain.

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
keep this share of their colour pin accuracy: Eagle 93%, KiCad 71%, Altium
42%. Before, a black page read as nothing.

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

Corpus totals are summed over pins, not averaged over designs.

Swapping the two pins of a resistor, non-polarised capacitor, inductor,
ferrite bead, fuse or crystal is not counted as an error. These parts are
recognised by their KiCad symbol, or by designator (R, C, L, FB, F) when the
symbol is named after a value or package. Symbols whose names mark them as
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
