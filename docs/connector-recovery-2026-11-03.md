# Connector recovery — 2026-11-03

This phase starts at `6111d64ec954dbcf2db4aacd78e015823c71c3d1`, preserving the
previous accuracy improvements. It changes component ownership and grouping in
`symbols.py`. Inputs, truth, splits, scorer, confidence rules, models, dependencies
and public interfaces remain unchanged.

## Priorities and confirmed causes

The repeated-connector evidence offered the largest immediate recovery with
independent drawing evidence. The first two cases contain complete detected
connectors under missing alternative references. A20 contains six detected
sections under one reference. Both are upstream ownership failures, rather than
reasons to infer numbers from the benchmark truth.

The [separate dataset review](dataset-review-2026-11-03.md) checks the pinned source
meaning. LCD_CON, LCD_LIME and LCD_LIME2 are distinct alternative connectors at the
same location, connected alike, with different packages and separate printed
names. A20-SOM-EVB_PLATFORM is one component containing six connector sections.
These cases require different ownership decisions.

### Overlaid connector names

The LCD drawings repeat every connector shape and pin line three times. PDF
classification deduplicates that geometry and preserves its copy count. The three
reference texts occupy a column in the same style, size and colour. Drawing by
layer prevents their sequence positions alone from establishing ownership.

Field assignment selects LCD_LIME2. The existing alternate-name recovery rejects
LCD_LIME because the designator model scores it below its word threshold;
LCD_CON has already been consumed as a value. Neither finding means the geometry
or name is absent.

Recovery now also accepts a complete column of related names when its distinct
texts account for every geometry copy. Names must share the stem before an
underscore and lie outside the body. A reference already owned by another part
cannot be copied, nor can a value owned by another part. An own value consumed as
an alternate name is cleared. Each restored component gets independent pin
objects at the original locations and numbers. The existing model-based recovery
continues to handle other names; its threshold is unchanged.

This deliberately does not accept arbitrary adjacent words as references. Tests
cover absent/insufficient copies, incomplete columns, scalar values, unrelated
names, another part's reference, and independent copied pins. The positive case
fails at the starting source. LCD 4.3TS independently exercises the same rule.

### Sections joined by dashed body edges

A20's six 40-pin sections are linked by matching dashed vertical sides. The dashes
are individual solid PDF paths, rather than paths marked with a dash style.
Ordinary touching groups and the learned splitter leave the sections apart.
Only the first inherits the external platform reference; four remain unnamed and
the last takes a printed pad label, LCD-15, as its reference. All 240 pin geometries
already exist.

After ordinary field annotation, matching dashed sides can reunite sections.
Both body edges must align, with at least three regularly spaced dashes per side,
matching positions, lengths, gaps, colour and width. Dashes must belong to pinless,
non-power graphics. Discarded frames cannot participate. A lone annotation or an
electrical pin cannot bridge the sections.

The combined outline must have exactly one previously assigned reference beyond
its end in the joining direction. A second section's independently printed
reference prevents recovery. Side labels along pins do not name the whole part.
The existing numbering function then reads the combined part's printed labels;
it does not generate a sequence or translate compound pad names. Of the 240
platform pins, 208 retain numbers read from text and 32 remain known only by their
printed names. The unchanged scorer can align some of those names to source pads;
no hidden package numbering is claimed for them. Both orientations
are tested, with incomplete, uneven, independently named, unnamed and electrical
bridge controls. The fixed native before/after extraction supplies the positive
regression case.

A geometry-only trial before annotation joined the sections but let field
assignment choose LCD-15 for the entire drawing. It reduced A20's correct count
from 648 to 613 and was rejected. Keeping the existing external reference as
independent ownership evidence raises it to 834. Only that constrained version
is retained.

## Development evaluation

All 198 development designs (55,853 pins) use the identical grouped out-of-fold
models, fixed scorer and original truth, with embedded recovery disabled. The final
source was extracted afresh across all six corpora. No protected test or holdout
evaluation was run. All six paired comparison gates pass; no page fails.

| Corpus | Correct | Missing | Wrong | Silent wrong | Exact nets |
|---|---:|---:|---:|---:|---:|
| A | 21,504 → 21,504 | 1,614 → 1,614 | 275 → 275 | 64 → 64 | 4,509 → 4,509 |
| B | 4,527 → 4,527 | 296 → 296 | 140 → 140 | 25 → 25 | 762 → 762 |
| C | 4,984 → 4,984 | 840 → 840 | 108 → 108 | 11 → 11 | 1,038 → 1,038 |
| D | 8,387 → 8,725 | 1,965 → 1,616 | 367 → 378 | 70 → 70 | 1,353 → 1,556 |
| E | 2,320 → 2,320 | 410 → 410 | 206 → 206 | 33 → 33 | 401 → 401 |
| F | 7,341 → 7,341 | 319 → 319 | 250 → 250 | 42 → 42 | 1,507 → 1,507 |

Across the full cohort: **49,063 → 49,401 correct (+338)**, **5,444 → 5,095
missing (−349)**, **1,346 → 1,357 wrong (+11)**, **245 → 245 silent wrong**,
and **9,570 → 9,773 exact nets (+203)**. Matched references rise 14,823 → 14,827.
Olimex missing pins fall by 17.76%; Eagle remains unchanged.

| Corpus | Pin accuracy | Missing rate | Silent rate | Pair F1 | Macro F1 | Exact-net rate |
|---|---:|---:|---:|---:|---:|---:|
| A | 91.92493% → 91.92493% | 6.89950% → 6.89950% | 0.27359% → 0.27359% | 94.54896% → 94.54896% | 91.28978% → 91.28978% | 88.82979% → 88.82979% |
| B | 91.21499% → 91.21499% | 5.96413% → 5.96413% | 0.50373% → 0.50373% | 90.33833% → 90.33833% | 86.07996% → 86.07996% | 74.12451% → 74.12451% |
| C | 84.01888% → 84.01888% | 14.16049% → 14.16049% | 0.18543% → 0.18543% | 83.21980% → 83.21980% | 83.44292% → 83.44292% | 62.79492% → 62.79492% |
| D | 78.24424% → 81.39752% | 18.33193% → 15.07603% | 0.65305% → 0.65305% | 75.54848% → 77.97821% | 78.03236% → 84.23934% | 51.72018% → 59.48012% |
| E | 79.01907% → 79.01907% | 13.96458% → 13.96458% | 1.12398% → 1.12398% | 67.24955% → 67.24955% | 77.92486% → 77.92486% | 58.71157% → 58.71157% |
| F | 92.80657% → 92.80657% | 4.03287% → 4.03287% | 0.53097% → 0.53097% | 96.93114% → 96.93114% | 89.10260% → 89.10260% | 83.12190% → 83.12190% |

Overall pin accuracy is 87.84309% → 88.44825%;
pair-weighted connection F1 is 92.34428% → 92.45167%,
and macro connection F1 is 85.24557% → 85.84421%.

| Changed design | Correct | Missing | Wrong | Silent | Exact nets |
|---|---:|---:|---:|---:|---:|
| LCD 7TS | 206 → 286 | 126 → 46 | 17 → 17 | 8 → 8 | 9 → 42 |
| LCD 4.3TS | 116 → 188 | 115 → 43 | 2 → 2 | 0 → 0 | 4 → 33 |
| A20 SOM EVB | 648 → 834 | 404 → 207 | 24 → 35 | 1 → 1 | 48 → 189 |

The name-only change adds 152 correct pins and 62 exact nets in the two LCD
designs. Dashed-body recovery adds 186 correct pins and 141 exact nets in A20.

| Olimex metric | Change, pp | Paired 95% interval, pp |
|---|---:|---:|
| pin_accuracy | +3.15328 | +0.00000 to +7.90063 |
| missed_pin_rate | -3.25590 | -8.36788 to +0.00000 |
| silent_error_rate | +0.00000 | +0.00000 to +0.00000 |
| connection_f1 | +2.42974 | +0.00000 to +7.47788 |
| macro_connection_f1 | +6.20698 | +0.00000 to +10.27787 |
| net_exact | +7.75994 | +0.00000 to +22.11771 |

Intervals use 2,000 paired group-bootstrap draws with seed 0. The other five
corpora have zero metric changes and zero change intervals. All gain intervals
include zero; results are concentrated in three development designs and do not
establish independent generalization. All 198 per-design counts and every metric
interval are in `final-*.json` and `final-paired-results.json`.

## Every changed pin and regression

All before/after predictions and aligned pin transitions are retained. The two LCD
cases contain exactly 80 and 72 missing-to-correct transitions, respectively,
with no newly missing or wrong pins.

A20 has 189 missing-to-correct, two flagged-wrong-to-correct, eight
missing-to-flagged-wrong and five correct-to-flagged-wrong transitions. No pin
becomes newly missing or newly scored silent wrong. Its aggregate gain is 186
correct pins and 197 fewer missing pins; total wrong pins increase by 11.

The five previously correct pins are R58.1, LDO3_2.8V_E.1, GPIO-2.22, GPIO-2.6 and
GPIO-2.24. Each retains exactly the same raw predicted net, including its members.
Recovery changes the fragment selected by the scorer's one-to-one net matching.
These remain counted as regressions. No matching or normalization rule was changed.

The eight newly recovered pins scored wrong are platform 2-1, 4-1, 4-21, 4-22,
4-40, LCD-3, LCD-8 and LCD-9. Their raw nets are incomplete fragments: all scored
members on each fragment belong to the same true net. In particular, LCD-8 and
LCD-9 connect to the correctly numbered LCD_CON terminals but remain separated
from other fragments. The 4-21/4-22 fragments also contain an existing unscored
BSS138 reference. Recovery exposes incomplete connectivity; it does not introduce
new physical shorts in these transitions. Confidence and warning policies are
unchanged. A20's total flagged-net count falls from 218 to 116, despite more
pin-addressed issues becoming possible as numbers are recovered.

### Earlier Nolman transitions reviewed

The preceding phase's saved physical geometry and raw nets were compared again.
R6/R7 keep their positions and correct two-pin nets. Their other terminal's old
association was to `R14.?3`/`R15.?3`; R8 similarly had an association to `R2.?3`.
These were extra unnamed neighboring pins. Losing those associations changes
passive-end normalization and which end the scorer calls missing; restoring them
would recreate erroneous ownership.

C12 and R83 previously had unnamed pins and now expose numbers on already
imperfect nets. C50 keeps both pin positions and its correct two-pin fragment;
its other pin remains on the pre-existing merged ground/power-label net. Removing
false aliases changes that net's membership without establishing a new short.
C12's upper terminal now stays with C13.1 and U2.5; its former +3.3V membership
passed through an extra unnamed pin. No general physical regression fix was
justified by these cases, and no scorer change was made. Nolman's current extraction counts remain at the starting
baseline for this phase.

## Library-enabled evaluation

The unchanged indexed KiCad/Eagle folder was supplied in separate full runs for
all 78 Eagle and 19 Olimex development designs, under the same fold models. Both
library-enabled paired gates pass. EasyEDA has no active pin-library matcher;
the other formats have no extraction changes in this phase.

| Corpus / pins | Correct | Missing | Wrong | Silent | Exact nets |
|---|---:|---:|---:|---:|---:|
| C / 5,932 | 5,009 → 5,009 | 815 → 815 | 108 → 108 | 11 → 11 | 1,043 → 1,043 |
| D / 10,719 | 8,387 → 8,725 | 1,965 → 1,616 | 367 → 378 | 70 → 70 | 1,353 → 1,556 |

| Corpus | Pin accuracy | Pair F1 | Macro F1 |
|---|---:|---:|---:|
| C | 84.44032% → 84.44032% | 84.28158% → 84.28158% | 84.18881% → 84.18881% |
| D | 78.24424% → 81.39752% | 75.54848% → 77.97821% | 78.03236% → 84.23934% |

`library-paired-results.json` contains the full per-design changes and paired
intervals. Library benefits relative to drawing-only extraction are not counted
as gains of these algorithms. The library runs use the dashed-body snapshot;
the final snapshot adds only defensive handling of discarded/power graphics.
Final-source drawing-only counts match that snapshot in all six corpora.
Library lookup follows symbol recovery; it does not alter that body-grouping stage.

## Other investigations and rejected changes

The MDBT50Q glyph failure was traced beyond the library rejection. Each problematic
8 has 22 extracted segments, while the saved font candidate has 32. The matcher's
segment-count filter permits a difference of only four and therefore excludes the
correct candidate before its geometric distance is measured. Candidate 8 distances
are approximately 0.057–0.058 text heights; the chosen o distances are about
0.114–0.116. The same mismatch repeats in three independently placed tokens.
The source module agrees with the printed numbering; this is decoding evidence,
not a newly established dataset mismatch.

No global character replacement, sequential numbering, model change, weaker
library disagreement allowance or Eagle library-policy change is retained.
A follow-up should preserve alternative glyph evidence and require unique
geometric/library agreement while retaining intentional alphanumeric pads.
The diagnostic masking experiment from the preceding phase is not an accepted
numbering rule.

For Nolman U10.12, the original red segment is PDF path id 1551, drawing sequence
2478. In the selected black reading its learned role scores are approximately
0.557 wire and 0.443 symbol, with no pin-class probability. It becomes scene wire
431 from `(340.63667, 171.95662)` to `(345.71663, 171.95662)`. One end contacts the
amplifier outline; the other contacts shape 1426, a separate continuation to
`(338.09669, 171.95662)`. The printed 12 lies beside the missing root.

A narrow numbered-edge trial required two neighboring printed pin numbers and
an unbranched body-to-wire connection. It recovered nothing: the outer end meets
a shape-classified continuation, rather than another wire. The trial was removed.
A future correction must reconcile both roles and retain fragment ownership,
rather than broadly treating body-boundary wires as pins. No production code or
accuracy gain is claimed for this experiment.

## Validation and performance

The final suite passes **315 tests**, **82.56% coverage**, meeting the 80% gate.
Ruff lint, formatting, diff checks and CI-style A/E development benchmark gates
pass. CI uses shipped models and historical baselines; the scientific comparisons
above use fixed grouped out-of-fold models.

Three interleaved fresh-process trials per source used identical fold models,
no library and no embedded recovery:

| Case | Before median | After median |
|---|---:|---:|
| LCD 7TS | 4.943 s | 4.964 s |
| A20 SOM EVB | 21.105 s | 21.908 s |

Concurrent load and three trials do not establish a general performance change.
The observed medians are about +0.4% and +3.8%; the full samples are saved in
`extraction-timing.json`. No distribution build or Windows run was performed.

## Provenance, commits and repository state

Evidence is under ignored `bench/out/units-2026-11-03/`. Baseline reports copy the
completed `coherent-pins` results for source `6111d64`; those original reports and
predictions are preserved. Separate source snapshots and phase names distinguish
the name-only, dashed-body and final runs. No prediction cache is shared between
source versions.

`provenance.json` records hashes of every development PDF/truth pair, source
snapshots, benchmark configuration, fold model and indexed library. All 198 input
pairs, models, libraries and benchmark source were verified unchanged. Full
per-design counts, pin transitions, bootstrap comparisons, source excerpts,
rejected experiments, timing and check logs remain available there.

For reproduction, run `run.py` with a fresh phase name, the desired snapshot
`src` on `PYTHONPATH`, and corpus arguments `a b c d e f`. Set `AUDIT_LIBRARY`
to `bench/out/audit-2026-11-02/libraries` for the separate library runs. Existing
phase reports are refused rather than overwritten.

The implementation ends at `cd99e86ac2116c8445893d676b9a51ecbb274c9f`. Local commits before this reporting
commit are:

```text
52538a6 Recover names on overlaid connector drawings
b7f7614 Check connector benchmark sources
cd99e86 Join connector sections across dashed borders
```

The reporting commit changes documentation only; final HEAD is recorded in
`bench/out/units-2026-11-03/commits.json`. All work remains local. No push,
publication or history rewrite occurred. The original safety stash
`3c4c65e32bb1224cc4411da57667e3ca72d420de` and user PDF are preserved;
the PDF remains byte-identical. After the reporting commit the tracked tree is
clean and `git status --short` contains only:

```text
?? schem2net_build_plan.pdf
```

## Three most valuable remaining improvements

1. Recover other missing connector/component references using actual unit and
   field ownership, especially long functional names and split drawings without
   matching dashed borders. Do not assume another case has the LCD or A20 mechanism.
2. Preserve glyph alternatives across segmentation differences and resolve printed
   pad numbers with unique library/geometry agreement. MDBT50Q provides a concrete
   test; legitimate alphanumeric and ambiguous pads must remain unchanged.
3. Reconcile wire-classified pin roots with shape-classified continuations using
   printed number and boundary topology. U10.12 requires both stages, and remaining
   A20 power/GPIO fragments need physical joining rather than scorer changes.
