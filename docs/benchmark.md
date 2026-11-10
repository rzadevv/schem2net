# Benchmark

## Evidence and current status

The [independent evaluation](release-2026-11-05.md) is the current frozen result:
63 new designs / 40 groups, predominantly generated KiCad PDFs, 91.02% drawing-only
pin accuracy. It did not meet all release gates. The [development guide](development.md#engineering-history)
summarizes the separate, repeatedly optimized 198-design development corpus.
The historical test/holdout tables below are preserved as originally reported;
they are not fresh results for the current extractor.

<a id="results"></a>

## Historical test and holdout results

Figures are for each corpus's test split, whose boards the learned models never
saw, and its holdout, read once at commit 0cf46ce; both with KiCad's and
SparkFun's part libraries indexed (see Part library below). In brackets, a 95%
interval from a bootstrap over groups of boards, revisions of one board counted as
one: with three to forty a split, a few points either way is noise. The holdout
intervals of A, D and F, read before groups were drawn whole, are over boards and
run narrow.

| Corpus | Split | Designs | Pins | Pin accuracy | Connection F1 |
|---|---|---|---|---|---|
| A, KiCad | Test | 6 | 1,154 | 0.93 (0.87–1.00) | 0.90 (0.85–1.00) |
| A, KiCad | Holdout | 11 | 3,924 | 0.86 (0.83–0.94) | 0.88 (0.69–0.94) |
| B, Altium, drawing only | Test | 12 | 3,887 | 0.86 (0.76–0.90) | 0.91 (0.86–0.94) |
| B, Altium, drawing only | Holdout | 6 | 1,646 | 0.84 (0.78–0.90) | 0.82 (0.79–0.88) |
| C, Eagle | Test | 39 | 2,824 | 0.81 (0.77–0.85) | 0.77 (0.71–0.82) |
| C, Eagle | Holdout | 21 | 1,185 | 0.81 (0.78–0.85) | 0.81 (0.77–0.87) |
| D, Olimex | Test | 20 | 6,057 | 0.86 (0.82–0.90) | 0.82 (0.75–0.89) |
| D, Olimex | Holdout | 7 | 1,911 | 0.86 (0.74–0.91) | 0.88 (0.69–0.94) |
| E, EasyEDA | Test | 14 | 1,027 | 0.65 (0.48–0.81) | 0.51 (0.29–0.89) |
| E, EasyEDA | Holdout | 3 | 193 | 0.78 (0.61–0.86) | 0.78 (0.00–0.87) |
| F, OrCAD | Test | 8 | 10,702 | 0.95 (0.90–0.96) | 0.97 (0.94–0.98) |
| F, OrCAD | Holdout | 5 | 434 | 0.97 (0.96–1.00) | 0.92 (0.89–1.00) |

Accuracy says how much is right; what a user also needs is to know where the rest
is. Silent errors are pins on a wrong net that nothing flags. Pins not found are on
no net at all: a part left out, a pin read with another number, or one the drawing
hides; most of the accuracy lost on corpora C to E is here. Review items are the
doubtful nets and the issues naming pins, each one thing to check; precision is the
share of them that point at something wrong.

| Corpus | Split | Silent errors | Pins not found | Wrong pins flagged | Review items per 100 pins | Review precision | Boards with no silent error |
|---|---|---|---|---|---|---|---|
| A, KiCad | Test | 0.2% (0.0–0.4) | 1.6% | 0.97 | 9.4 | 0.68 | 0.83 |
| A, KiCad | Holdout | 0.4% (0.0–0.7) | 10.8% | 0.87 | 6.9 | 0.72 | 0.82 |
| B, Altium, drawing only | Test | 2.2% (0.0–3.4) | 9.4% | 0.54 | 7.9 | 0.70 | 0.75 |
| B, Altium, drawing only | Holdout | 0.4% (0.0–1.2) | 6.7% | 0.96 | 17.9 | 0.64 | 0.67 |
| C, Eagle | Test | 0.7% (0.2–1.4) | 15.7% | 0.75 | 14.3 | 0.58 | 0.87 |
| C, Eagle | Holdout | 0.8% (0.4–1.5) | 16.3% | 0.69 | 14.3 | 0.51 | 0.71 |
| D, Olimex | Test | 0.3% (0.1–0.7) | 10.6% | 0.91 | 12.0 | 0.78 | 0.80 |
| D, Olimex | Holdout | 0.1% (0.0–0.2) | 13.0% | 0.95 | 7.5 | 0.76 | 0.86 |
| E, EasyEDA | Test | 0.1% (0.0–0.3) | 27.8% | 0.99 | 14.2 | 0.69 | 0.93 |
| E, EasyEDA | Holdout | 1.0% (0.0–11.1) | 13.5% | 0.88 | 16.6 | 0.88 | 0.67 |
| F, OrCAD | Test | 0.5% (0.1–1.0) | 2.5% | 0.78 | 5.1 | 0.65 | 0.38 |
| F, OrCAD | Holdout | 0.0% (0.0–0.0) | 2.8% | 1.00 | 5.8 | 0.32 | 1.00 |

## Corpora

| Corpus | Source | Ground truth |
|---|---|---|
| A | Open KiCad projects rendered with `kicad-cli` (KiCad 10) | Netlist exported by `kicad-cli` |
| B | Altium schematic PDFs published in open hardware repositories | The netlist the PDF carries, checked against the board file |
| C | SparkFun schematic PDFs drawn in Eagle | The Eagle `.sch` in the board's repository |
| D | Olimex schematic PDFs, KiCad and Eagle | The schematic the PDF sits beside |
| E | EasyEDA schematic PDFs, Std and Pro | The EasyEDA source the PDF sits beside |
| F | OrCAD Capture schematic PDFs | The Cadence Allegro board the PDF sits beside |
| G | Newer Olimex and SparkFun boards, KiCad and Eagle, held out whole | The schematic the PDF sits beside |

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
designators appear in the PDF's text. One revision per board.

Because the truth comes from the PDF, reading it back scores 1.0. Corpus B is
meant for `--drawing-only`, which ignores the embedded netlist and measures
extraction from the drawing.

Corpus C pairs the schematic PDF on a SparkFun product page with the `.sch`
in the board's repository, taken at the last commit before the PDF was made.
No commit pins a product page's PDF, so the manifest keeps its sha256 and a build
fails when a download differs.
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

Corpus D measures how results carry over to another maker's boards. No rule was
tuned on it, but it is not held out: its first run found a bug, below, and its dev
split is among those the designator model learns from. Olimex keeps each board's
published schematic PDF in its repository, beside the schematic it was printed
from, KiCad or Eagle; one revision of each board is used. Boards in KiCad's old
`.sch` format are left out, since current kicad-cli cannot read them for the
truth. Its first run found that KiCad 7 and 8 PDFs, which draw text as strokes,
were taken for board prints and skipped; they are read now. One pair was dropped
later: the PDF beside its `.sch` is a parts list, not the drawing.

Corpus E pairs EasyEDA schematic PDFs, as EasyEDA names its exports
(`Schematic_<project>.pdf`, `SCH_<sheet>.pdf`), with the source kept in the same
GitHub repository: a Std `.json` or a Pro `.epro`. A pair is kept when at least
90% of the source's designators are in the PDF's text, and copies of one PDF
count once; 30 designs remain. `easyeda.py` reads the netlist. A Std source
stores drawing, not nets, so wires, pins, net flags and labels that share a point
are joined, as EasyEDA does, on the file's exact coordinates. A Pro project names
the net of every wire; its parts' pins are placed from their symbols.

Corpus F pairs OrCAD Capture schematic PDFs from open hardware repositories
(BeagleBoard.org boards, ROHM evaluation kits, CutiePi, a LaunchPad derived board,
a Cadence tutorial) with the Allegro board (`.brd`) in the same repository. KiCad
10 imports Allegro boards; the benchmark Docker image reads the board's pads into
`truth.net`, as it does corpus B's boards. Each pair was checked by designators:
every designator on the board is printed in the PDF, but for eight of 439 on the
BeagleBoard-xM and one on the CutiePi. A board keeps few values, so values are
scored on few parts. Capture prints to PDF through a printer driver (Ghostscript,
Acrobat Distiller, Foxit, Microsoft's), so the PDF does not say what drew it and
its colours decide. One design, the tutorial, is drawn in colours of its own; its
ink is taken as black and read with the learned roles.

Corpus G is the holdout read after October 2026: boards of the makers above whose
repositories none of the other corpora use, each a schematic with the PDF printed from
it in the same commit, one design per repository. SparkFun's newer boards are drawn in
KiCad, so G also measures KiCad from a maker that A and D lack. None shares a fifth of
its true nets with a design of another corpus. The whole corpus is the holdout
(`holdout_share = 1.0`); no model learns from it and no rule is judged on it.

Eagle draws most text with its own stroke font, and some PDFs carry text as
filled outlines. `schem2net build-models font` learns the shapes of both kinds of
letters from the corpus C dev split: the `.sch` sheet is laid over the page by
the wires both share, each line of text is paired with the `.sch` text of the
same length placed at that spot (net labels, names and values, symbol text,
pin names and pad numbers), and the tables are written to
`profiles/eagle_font.json` and `profiles/eagle_fills.json`. Test boards are
never used.

## Roles for pages printed in black

`schem2net build-models roles` learns what each path and text is from the colour pages
of every corpus's dev split. The colours are the labels: a path in the wire
colour is a wire, a text in the label colour a label. No truth netlist is used,
and test boards are never read. It needs scikit-learn, one of the dev
dependencies; the trees are written to `profiles/roles.npz`.

To see how pages printed in black fare, recolour a dev PDF's ink to black and
read it again. With models learned without the board in question, dev pages
keep this share of their colour pin accuracy: Eagle 98%, KiCad 78%, Altium
50%, OrCAD 48%. Before, a black page read as nothing. Altium loses most on text:
net labels and pin names look much alike without their colours. An OrCAD PDF does
not say what drew it, so in black it is read as each generator in turn; two of
corpus F's 30 designs are then taken for another one.

## Designator model

`schem2net build-models designators` learns which texts name parts, from every corpus's
dev split. Each design is read as usual up to the point where designators are given
out; there each text's features are taken (what it says, where it sits against the
nearest part and the wires, what was drawn just before and after it) and the truth
netlist gives the label: a text that is a part's reference, or one with a unit
letter, is a designator. A string written more than once in a design, such as C1
naming both a capacitor and a transistor's pin, is left out, as its label is not
known. The truth is used for nothing else, and test boards are never read. One
model is learned per generator and written to `profiles/designators.npz`.

The stored models have seen the dev designs, so dev figures read with them run
high. `schem2net build-models --folds -o bench/out/folds` learns every file once for
each of four folds of the dev groups, without that fold's designs, and `bench
--folds bench/out/folds` reads each dev design with the models learned without it.
Each design is read once for all four folds, with the stored models, so a fold's
models never see its designs, though the rows they learn from were read with models
that had. Test figures are not affected: test designs are never learned from.

## Learned files

Five files in `profiles/` are learned from the dev splits, never from test:

| File | Learned from | Made by |
|---|---|---|
| `roles.npz` | colour pages of A, B, C, E and F | `schem2net build-models roles` |
| `designators.npz` | A to E, with their truth netlists | `schem2net build-models designators` |
| `eagle_font.json`, `eagle_fills.json` | C, with its `.sch` files | `schem2net build-models font` |
| `groups.npz` | the Eagle designs of C and D and the EasyEDA ones of E, with their sources | `schem2net build-models groups` |

They hold tree thresholds, leaf values and glyph strokes measured from those
designs, not the designs. The designs are under their makers' licences, listed in
the manifests: mostly CC BY-SA 4.0 (SparkFun, most of corpus B), GPL-3.0 (most
of Olimex), MIT, Apache-2.0 and CERN-OHL; some list none. Whether such
measurements fall under those licences is not settled here.

## Part library

Results are read with part libraries indexed (`schem2net index-library`, then
`bench --library`): KiCad's,
from the kicad-symbols repository at commit e1bb0a65 (2026-10-04), and
SparkFun's Eagle libraries, from SparkFun-Eagle-Libraries at commit 2354dae
(2024-08-23). Libraries carried by the corpus projects are never read: a part from
one of them keeps what its drawing shows. Olimex's own libraries are not indexed,
so corpus D shows what is read without the maker's library.

## Splits

Projects are split by group, so that revisions and sibling boards of one design
cannot sit on both sides. A project's group is its repository, a KiCad demo's its
folder, unless the manifest names one: corpus B's two team repositories hold a
board per folder, each a group of its own, and boards of one family kept in
repositories of their own (ROHM's BU9000x kits, SparkFun's two Qwiic shields for
Teensy) share one. Two built designs that share nine tenths of their true nets are
put in one group too. A design whose true nets an earlier one has already, such as
a revision whose drawing did not change, is a copy and scored nowhere.

Groups are taken in the order of a hash of their names. The first 15% of a
corpus's groups, or two where it has fewer than 14, are the `holdout`; the next
fill `test` to the corpus's share of designs (a tenth for A, a third for B, C and
F, half for D and E); the rest are `dev`, dealt into four folds by group in the same
order. Tune on `dev`. Report `test`. The holdout
is read once, with the final code, and only with `SCHEM2NET_HOLDOUT=1` set; `all`
means dev and test. The holdout was first read on 2026-10-16, at commit 0cf46ce.

Before October 2026 projects were split by a hash of their names. That put
revisions of one board on both sides (corpus D's A20-OLinuXino-MICRO rev D and
rev E2 have the same nets), and test was benched after many changes. Figures
from before then are not comparable with these.

```sh
schem2net bench a --split dev
schem2net bench a --split test --json results.json
```

`bench --json` writes each design's raw counts, so any figure can be computed again.
Revisions of one board are not independent, so intervals come from a bootstrap over
groups: 2,000 draws of the groups with replacement, each design counted as often as
its group is drawn. `bench` says how many groups its designs are in, and `bench --json`
keeps each design's group. `bench-compare` requires identical design sets and gives
for each metric the change and a 95% interval of it, the same draws
for both runs. A run fails when the interval of the pin accuracy change lies wholly
below -0.002, silent errors rise by more than 0.001, or more pages fail to be read.

A change is kept when, on dev read with folds, the interval of the pin accuracy change
lies above -0.002 on every corpus and does not reach below 0 on the corpus the change
was made for, and silent errors do not rise. A corpus of a dozen groups has draws
holding none of the designs a change reaches, so even a change that only gains can
show no gain in some. A change that falls short is taken out, not tuned
until it passes.

```sh
schem2net bench d --split dev --json before.json
schem2net bench d --split dev --json after.json
schem2net bench-compare before.json after.json
```

`bench --explain` shows where each true pin went: right, renumbered (on the net
where another pin of its part belongs), merged, split, or on no net because its
part is missing, its number differs, it is kept unnumbered, it is listed on no net
or not found at all. It then gives the share of wrong nets and pins by confidence,
and how well doubt ranks wrong pins above right ones (AUROC).

CI builds corpora A and E and compares their dev splits with
`bench/baseline_a_dev.json` and `bench/baseline_e_dev.json`.
CI has no part library, so the baselines are read without one, and no folds, so with
the stored models: they guard against regressions, not for judging a change. A change
meant to move these figures writes the baseline again:

```sh
schem2net bench a --split dev --json bench/baseline_a_dev.json
schem2net bench e --split dev --json bench/baseline_e_dev.json
```

## Verifying a corpus

A PDF beside a schematic in one folder does not show they are one design. Before a
corpus is read, `verify-corpus` checks each built design without the extractor, so
admission cannot favour designs it reads well, and writes the evidence and file
hashes to `bench/verified_<corpus>.json`:

- How the PDF is known to show the truth: exported from the source with it, carrying
  the schematic's own netlist (Altium; read drawing-only), agreeing in printed text,
  or, where its text cannot be read (outlined, or drawn as strokes), its revision
  alone: committed with or after the source's last change. A PDF that is hard to read
  is not turned away for it; evaluations report results by this evidence.
- That nothing shows a mismatch. A published PDF may leave out no more than 5% of the
  truth's designators and 20% of its chosen net names (bus members count when their
  bus is printed), print no more than three, or 5%, designators the truth lacks, not
  predate the source's last change and have no fewer pages than the source has sheets.
  Not counted as left out: designators the source hides (EasyEDA, KiCad), printed run
  into their own value (`R100100.0`), and instances of a repeated channel drawn once
  (`1U3` where `U3` is printed); they are listed, and the truth keeps them. Printed
  words are rebuilt from pdfium's letter boxes, a word to each run of letters along
  one line; pin numbers and names are not taken for designators, nor are a ball
  grid's rows.
- Where it comes from: repository, commit, git blobs of the source, PDF and board,
  licence and licence file, source format version, PDF producer, export image and
  options. A licence must be determined: an SPDX id, or `none` where the source grants
  none; `none` and non-commercial designs are scored locally only, never redistributed.
- That it is new: not a repository, owner or fork parent of another corpus manifest
  or the November 5 panel, and sharing less than nine tenths of its true nets with
  any built design (`--against` adds folders, such as the November 5 pairs).

Each reason for keeping a design out names its kind: `mismatch` (the PDF, source and
truth disagree), `provenance` (used before, a copy, no licence), `scope` (not built,
unreadable, an image rather than a vector drawing) or `rendering`.

The record is the corpus's seal: its settings (tier, shares, the checks' thresholds)
and, for every design of the manifest, its manifest entry, group, input hashes and
decision. Hashes leave out the export time KiCad writes, so a design rebuilt from its
source hashes alike. A rerun that finds any difference, a design added or removed
included, fails until resealed with `--seal`, and `evaluate` refuses to read or score
a corpus that differs from its seal.
A corpus's `tier` is `exploratory` (inspected while choosing algorithms),
`development` (the default) or `independent`, which must be held out whole
(`holdout_share = 1.0`) so it is read only with `SCHEM2NET_HOLDOUT=1`.

A KiCad design may be rendered other ways, as projects naming its `variant_of`, the
`image` and PDF `export` options, or a `pdf` the authors published: each is admitted
only if its own netlist equals the design's, shares its group and is reported beside
it (`renderings`, `rendering_counts`), never among the designs.

```sh
schem2net build-corpus p
schem2net verify-corpus p --against bench/out/release-2026-11-05/pairs-v2
schem2net evaluate p bench/out/eval-p      # reads once, then writes report.json
```

`evaluate` reads each admitted design in a process of its own, with the shipped
models, drawing only, under 4 GiB, and writes each prediction once; scoring reads
only saved predictions. Its report gives the bench figures by generator and group,
with grouped intervals, in the form `bench-compare` reads, and per design the
seconds, peak memory, pages failed, wiring mistakes, evidence, and the parts the
source does not print with the pins they hold, also totalled by evidence. Scoring is
strict, every true pin counting; `observable` gives the same figures without the
parts the source does not print and the instances of a channel drawn once. A design
that fails whole scores no pins.

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
| `missed_pin_rate` | Share of pins on no net at all: a part left out, a pin read with another number, a pin the drawing hides. The netlist is short of them rather than wrong about them, so they are not counted as silent errors. |
| `extra_pin_rate` | Numbered pins on true parts that the truth has no pin of, such as a sign read as a pad number, against the true pins. |
| `pin_flag_recall` | Share of wrong pins that something flags. |
| `review_items_per_100_pins` | Things a reviewer is handed: each doubtful net and each issue naming pins counts once, per 100 pins. |
| `review_precision` | Share of those that point at something wrong: a doubtful net that is wrong, an issue one of whose pins is wrong. |
| `designs_without_silent_errors` | Share of designs whose every wrong pin is flagged. |

Corpus totals are summed over pins, not averaged over designs. Connection F1
counts pairs of pins, so one large net merged by mistake can set a corpus's figure
alone; `macro_pin_accuracy` and `macro_connection_f1` give the mean over designs
beside the pooled figures.

Wiring mistakes (`wiring_mistakes`) count each join or cut a reviewer would make, apart
from pins whose only fault is their number (a pin on the net where another pin of its
own part belongs, that pin not being there): a predicted net holding pins of k true
nets is k − 1 false merges, a true net spread over m predicted nets m − 1 false
splits. One is silent when every net it involves has confidence of at least 0.8 and no
issue names its pins.

Accuracy alone says little about whether a netlist can be used: a board 95% right
whose errors no one can find is worse than one 90% right whose doubtful pins are
all marked. So each wrong pin is also asked whether anything flags it: a net of
low confidence, or an issue naming the pin, such as a pin number the drawing does
not show and the extraction guessed.

Issue pin references undergo the same recovered-name mapping and symmetric-end
alignment as predicted nets. Before the 2026-11-02 correction, named `?N` pins could
escape issue accounting, and a warning could follow the opposite end of a swapped
passive. Historical confidence, silent-error and review figures therefore require
rescoring. Preserve original reports and rescore both sets of saved predictions with
the same scorer; electrical pin/net/pair counts are unaffected by this correction.
The [development history](development.md#engineering-history) summarizes the
reconciled audit and later extraction comparisons. Historical test and holdout
figures above have not been reevaluated. The [OpenLog pairing review](openlog-provenance-2026-11-02.md)
proposes a separate input correction; the original case remains in every reported
comparison.

A pin kept without a number (`?1`) cannot be told from the truth's pins, so it is
left out before nets are compared; the true pin counts as not found. One kept with
the name drawn beside it, because its number is hidden, counts as the pin of that
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
way. Each such part is turned round where that puts more pairs of pins on a net
together as the truth has them: first judged by the pins of other parts only, so a
board full of decoupling capacitors turned the other way round cannot outvote its
supply pins, then by its turned neighbours too, so a chain of resistors and
capacitors all turned comes right.

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
