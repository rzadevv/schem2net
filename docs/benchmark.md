# Benchmark

## Corpora

| Corpus | Source | Ground truth |
|---|---|---|
| A | Open KiCad projects rendered with `kicad-cli` (KiCad 10) | Netlist exported by `kicad-cli` |
| B | Altium schematic PDFs published in open hardware repositories | The netlist the PDF carries, checked against the board file |

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

## Splits

Each project is assigned to `dev` or `test` by a hash of its name, so the
split cannot drift. Corpus A holds out 10%, corpus B a third. Tune on `dev`.
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

## Known gaps in the ground truth

Some connections exist in the design but are not visible in the PDF:

- Hidden power pins that connect to a net by name.
- Label scope set in project settings. For example, Altium's net identifier
  scope decides whether same-named labels on different sheets connect.
- Parts that are not fitted in a variant.

These are not handled yet.
