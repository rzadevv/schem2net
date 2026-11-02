# Extraction development — 2026-11-02

This continues the [engineering audit](audit-2026-11-02.md). That report remains a
record of the older baseline and its zero extraction gain. The comparisons here
start **after** integrating upstream and preserving the audit fixes.

## Repository reconciliation

The original HEAD was `152c85a229be37fba9822fc2bbb6ee163b596749`. Fetching origin
confirmed nine missing commits through `19d02f61211f89bb79357bdd2fb316cefce89550`.
The working changes were archived, hashed and stashed, main was fast-forwarded,
and the stash was reapplied. The safety stash is retained at
`3c4c65e32bb1224cc4411da57667e3ca72d420de`.

README conflicts were resolved against upstream's rewritten usage guide, retaining
the audit's ingestion limits and historical-score notice. The scorer conflict
retains upstream's iterative normalization of passive chains and applies the
audit's issue-reference correction to its final permutation. A second turn of a
passive undoes the alias swap; extra predicted pads are filtered before aliasing.
The reconciled suite passed 280 tests. Its source was frozen before extraction
development began.

Upstream already fixes several electrical/name errors: same-page local/power-name
joining, names placed over passing wires, PWR_FLAG handling, hierarchical-label
alignment and theme text roles. Its scorer also forgives entire passive chains.
In particular, upstream already separates the audit's original 57-pin Cyborg
`+5V`/`GND`/`/IORQ` example. None of those gains is attributed to this phase.

The reconciled base and fetched origin/main are
`19d02f61211f89bb79357bdd2fb316cefce89550`. Development commits now sit above
that base; none was pushed. The original audit changes and the user's
`schem2net_build_plan.pdf` are preserved.

## Confirmed failures and retained changes

### Fragmented crossings falsely treated as T contacts

Cyborg's reconciled prediction still joins `+12V`, `5VSB` and `/PS_ON` in an
11-pin net. On page 3, the traced union-find path runs from 5VSB's symbol 54 at
`(55.87955, 132.56155)` through wire 126 to vertical wire 125, then through a
false `t_contact` with horizontal wire 138 at `(43.17965, 135.10153)` to +12V's
symbol 56. Wire 125 runs from `(43.17965, 151.61139)` to
`(43.17965, 132.56155)`; wire 138 ends at `(55.87955, 135.10153)`.
A collinear horizontal segment continues on the other side of the crossing.
There is no junction dot. The endpoint is a PDF drawing fragment, so the
endpoint-to-interior join incorrectly connects two independent axes.

`Netlister.add_page` now recognizes four axial arms at an undotted crossing,
using the existing spatial index and contact tolerance. It skips the inferred
perpendicular endpoint-to-interior join. Collinear segments still join;
T contacts, dotted crossings and explicit shared endpoints retain their behavior.
No tolerance, confidence weight or diagnostic threshold changed.

Cyborg improves from 701 to 708 correct pins, 27 to 20 wrong pins, 4 to 3 silent
wrong pins, and 103 to 106 exact nets. Missing pins remain 113. The Eagle LTE Cat
M1 Shield independently gains three correct pins and one exact net from this rule.

### Section borders absorbing unrelated component graphics

In `paralelahardware-schematic-nolman-2x2-rusefi-2023-03-16`, a supposed C11 spans
156 × 69 mm, contains 32 shapes and has seven pins. Its section header is drawn
first (shape 0, sequence 1) and its adjoining border last (shape 469, sequence
947). This broad drawing-order interval contains several separate components.
The small-decoration grouping stage sees zero bounding-box distance between a
containing frame and every internal mark. It consequently joins capacitor polarity
marks and ground bars to the frame, which then bridges unrelated parts.

`symbols._without_frames` now rejects a pinless outline that completely contains
at least the existing `FRAME_HOLDS` count of independent groups with multiple pins. Single-pin fragments do not establish
separate parts: transistor outlines can enclose several of those.
The existing minimum box size excludes bare lines. This evidence applies to both
small sections and large borders that contain only a minority of the page's parts;
the original page-frame rule remains. Frame rejection happens before decoration
grouping. No new threshold or board-specific exception is introduced.

With the crossing correction, Nolman improves from 352 to 383 correct pins,
190 to 183 missing pins, 85 to 61 wrong pins, 25 to 15 silent wrong pins,
44 to 46 exact nets, and 201 to 204 matched component references. C11 and C13
are no longer parts of the same giant drawing. C10, C13 and U9 are recovered
as named components. Its error
ledger's merged-pin bucket falls from 36 to 14.

There are individual losses: relative to the small-section variant, two D18 pins
become unnumbered when a second nearby symbol also receives D18. The original
diode geometry remains intact. The final development comparison records this
naming/numbering regression along with the larger recovery; no design is excluded.


## Evaluation protocol

Every main comparison uses all six existing **development** splits: 198 designs
and 55,853 true pins. Drawing-only extraction disables embedded netlist recovery.
Each design uses the existing models from `bench/out/folds/fold-K`, excluding its
grouped fold under the existing training workflow. These cached models were not
retrained or independently rebuilt. Before and after use identical scorer
source, libraries, ground truth, design sets and groups. No test or protected
holdout extraction/evaluation was performed, including corpus G.

The new baseline is the reconciled source, not the original audit's baseline.
Reports retain raw per-design counts, group membership, error ledgers and saved
predictions. Comparisons use 2,000 paired bootstrap draws over design groups with
seed 0. Confidence intervals describe development resampling; they do not
establish generalization to unseen generators or boards.

| Corpus | Designs / pins | Pin accuracy | Missing pins | Silent wrong pins | Connection F1 | Exact nets |
|---|---:|---:|---:|---:|---:|---:|
| A, KiCad | 49 / 23,393 | 91.92493% → 91.92493% | 6.89950% → 6.89950% | 0.27359% → 0.27359% | 94.54896% → 94.54896% | 88.82979% → 88.82979% |
| B, Altium | 25 / 4,963 | 91.21499% → 91.21499% | 5.96413% → 5.96413% | 0.50373% → 0.50373% | 90.33833% → 90.33833% | 74.12451% → 74.12451% |
| C, Eagle | 78 / 5,932 | 83.90088% → 83.95145% | 14.22792% → 14.22792% | 0.18543% → 0.18543% | 83.01625% → 83.15482% | 62.61343% → 62.67393% |
| D, Olimex | 19 / 10,719 | 78.22558% → 78.22558% | 18.34126% → 18.34126% | 0.66238% → 0.66238% | 75.53967% → 75.53967% | 51.72018% → 51.72018% |
| E, EasyEDA | 13 / 2,936 | 76.83924% → 78.13351% | 15.08856% → 14.85014% | 1.53270% → 1.15804% | 48.46452% → 62.26760% | 55.63690% → 56.36896% |
| F, OrCAD | 14 / 7,910 | 92.80657% → 92.80657% | 4.03287% → 4.03287% | 0.53097% → 0.53097% | 96.93114% → 96.93114% | 83.12190% → 83.12190% |

Across 55,853 pins, correct recovery rises **48,990 → 49,031** (+41), missing
pins fall **5,482 → 5,475** (−7), and silent wrong pins fall **258 → 247** (−11).
Six additional true nets are recovered exactly. Every paired corpus comparison
passes the existing gate; no pages fail. A, B, D and F have identical per-design
raw counts. Changes are concentrated in three designs:

| Design | Correct pins | Missing pins | Silent wrong pins | Exact nets |
|---|---:|---:|---:|---:|
| Cyborg | 701 → 708 | 113 → 113 | 4 → 3 | 103 → 106 |
| Nolman | 352 → 383 | 190 → 183 | 25 → 15 | 44 → 46 |
| LTE Cat M1 Shield | 167 → 170 | 43 → 43 | 0 → 0 | 32 → 33 |

EasyEDA's paired 95% intervals for changes are 0 to +2.79216 percentage points
for pin accuracy, 0 to +16.99413 points for connection F1, and −0.89041 to 0
points for silent-error rate. Eagle's pin-accuracy change interval is 0 to
+0.15736 points. The intervals include zero because improvements touch few groups;
these results do not establish broad statistical generalization. EasyEDA's macro
F1 rises 76.03071% → 77.44863%, a smaller gain than its pair-weighted F1.

Review burden is not increased to obtain the gains. EasyEDA review items per
100 pins fall 16.75749 → 16.38283, but review precision declines
0.51220 → 0.49688. D18's two unnumbered pins are a genuine local regression,
described above. The still-large missing-pin rates on Eagle and Olimex are
unchanged; this phase does not solve hidden-pin recovery in general.


## Separate library evaluation

Indexed KiCad and SparkFun/Eagle libraries from the audit were reused unchanged.
All 13 EasyEDA development designs and the deterministic eight-design development
sample from each of Eagle and Olimex were evaluated separately with these indexes.
The sample is selected by the existing runner with seed 0; it is not a full
library-enabled evaluation of C or D. These runs also use the grouped fold models.

| Corpus / sample | Pins | Pin accuracy | Missing pins | Silent errors | Connection F1 | Exact nets |
|---|---:|---:|---:|---:|---:|---:|
| E / 13 designs | 2936 | 76.83924% → 78.13351% | 15.08856% → 14.85014% | 1.53270% → 1.15804% | 48.46452% → 62.26760% | 55.63690% → 56.36896% |
| C / 8 designs | 475 | 90.94737% → 90.94737% | 7.78947% → 7.78947% | 0.00000% → 0.00000% | 92.25473% → 92.25473% | 70.63492% → 70.63492% |
| D / 8 designs | 3696 | 80.03247% → 80.03247% | 17.31602% → 17.31602% | 1.05519% → 1.05519% | 87.89913% → 87.89913% | 56.48038% → 56.48038% |

The library-enabled EasyEDA run has the same electrical counts and gains as the
no-library run. Both eight-design C/D samples have unchanged raw counts. These
samples establish no additional recovery attributable to library matching.

## Rejected experiments and unresolved roots

- Skipping every perpendicular join at a four-arm undotted crossing disconnects
  legitimate explicit endpoint joins. In Cyborg it loses the shared H1/M1
  connection and produces five silent wrong pins instead of the reconciled
  baseline's four. The retained rule skips only endpoint-to-interior inference.
- A containment guard in the strict interleaving branch of decoration grouping
  changes no measured counts. The actual frame leak is in the separate small-bit
  branch, so the ineffective guard was removed.
- An initially broader frame rule counts single-pin fragments as whole parts.
  In Olimex A13 LCD10TS it removes the transistor's circular outline, changes
  FET2's name/value assignment and exposes a new silent wrong connection.
  This is not a valid frame removal. The retained rule requires groups with
  multiple pins, preserving the outline. A realistic body-stroke regression fails
  against that broader rule and passes with the guard. The broader run's larger
  diagnostic gain is not retained or attributed to correct electrical recovery.
  That rejected variant reports 26 EasyEDA silent errors, while Olimex gains 11
  correct pins and loses 12 missing pins but adds one silent wrong pin. Those
  Olimex changes arise with the invalid outline removal and are not accepted gains.
- Nolman's U10 input pin 5 is printed beside shape 1370, which runs from
  `(340.63667, 248.15601)` to the amplifier body at `(345.71663, 248.15601)`.
  Late shape 1503 continues its tip to `(338.09669, 248.15601)`. Both become
  candidate pins; `_group` mistakes the real input for a body stub. Learned
  splitting later removes the continuation without restoring the lost pin.
  Similar losses affect inputs 10 and 12. Supply numbers absent from the drawing
  were not invented.
- A broad collinear-stub exception reads the input but breaks legitimate capacitor
  construction (including an existing regression). EasyEDA accuracy falls to
  63.9986%, with 29.0872% missing pins. Restricting the exception by reference
  drawing order passes the focused suite but still yields only 76.7711% accuracy
  and 15.7698% missing pins. Two input numbers are read yet remain off their nets;
  other capacitors lose pins. Both variants were removed, with source snapshots,
  reports and the diagnostic fixture preserved outside the production tree.
- `sparkfun-qwiic_openlog` has 58 missing pins out of 80 in the initial probe.
  The PDF names its ATmega U1 and shows a MIC5205 regulator U2, while the paired
  schematic names the ATmega U2 and includes Qwiic headers absent from the PDF.
  This appears to be a revision mismatch, requiring a separate provenance review.
  Ground truth, split membership and scoring were left unchanged.

## Validation and timing

The plain-crossing and section-frame failure cases fail against the frozen
reconciled source. The transistor-outline case fails against the broader frame
variant. All regression cases and positive controls pass with the retained fixes.
They cover fragmentation in either axis, with and without
junction dots, genuine T contacts, explicit common endpoints, and both small and
large section frames containing a minority of the page's parts. Frame regressions
disable learned grouping so that geometric correctness cannot be masked by a model.

The final suite passes **289 tests**, with **82.25% line coverage**, in **38.55 s**
on Python 3.13.15. `ruff check .`, `ruff format --check .`, and `git diff --check`
pass. There is no new dependency, model, framework, IR schema or public API change.

CI-style runs with shipped models pass the existing A and E benchmark gates.
They are separate from the out-of-fold comparisons above. Historical CI review
figures use older issue accounting; those differences do not measure the new
algorithms' review burden. The main comparison holds the scorer fixed.

Three interleaved fresh-process trials per version used the same fold models,
drawing-only extraction and no library. Median extraction times were:

| Case | Before | After |
|---|---:|---:|
| cyborg-sch-cyborg | 2.517 s | 2.459 s |
| paralelahardware-schematic-nolman-2x2-rusefi-2023-03-16 | 4.872 s | 4.627 s |

The small sample ran under concurrent benchmark load; it supports no throughput
claim. Each trial and its component/net counts are saved in
`accepted-extraction-timing.json`.

Elapsed extraction/scoring times are recorded per corpus in the JSON reports.
Jobs overlap and were interrupted during the requested pause. Baseline C and the
intermediate section-frame run reuse already saved predictions when resumed;
their resumed times omit that cached extraction. These wall times are unsuitable
for a before/after throughput claim. The initial audit's independently measured
schematic-label speedup remains documented there; it is not attributed to the new
extraction changes. Distribution building, optional MCP transport, Windows and
independent holdout generalization were not newly validated in this phase.

## Reproduction and evidence

Local evidence is under ignored `bench/out/development-2026-11-02/`:

- `audit-worktree.tar.gz`, `audit.patch`, `audit-files.json`, `audit-status.txt`,
  `reconciled.patch` and `reconciliation.json` preserve synchronization evidence.
- `reconciled-source/src` and `multi-parts-source/src` freeze the compared implementations;
  `provenance.json` records their file hashes, fold-model hashes and library hashes.
- `baseline-*.json` and `multi-parts-*.json` are the full no-library results;
  `baseline-lib*` and `multi-parts-lib*` are the separate library results. Failed and
  intermediate phases have distinct names and are retained.
- Case pickles, IR JSON, symbol lists and union-find graph captures retain the
  inspected primitives and joins. `forensics.py` reproduces development-only cases.
- `run.py` saves each prediction and refuses to overwrite a completed report.
  `AUDIT_RESUME=1` reuses a phase's saved predictions and skips completed corpora;
  use it only with that phase's frozen source, library settings and model hashes.

For a fresh phase name, run from the repository root:

```sh
PYTHONPATH=bench/out/development-2026-11-02/reconciled-source/src \
  .venv/bin/python bench/out/development-2026-11-02/run.py fresh-before a b c d e f
PYTHONPATH=bench/out/development-2026-11-02/multi-parts-source/src \
  .venv/bin/python bench/out/development-2026-11-02/run.py fresh-after a b c d e f
.venv/bin/schem2net bench-compare \
  bench/out/development-2026-11-02/fresh-before-e.json \
  bench/out/development-2026-11-02/fresh-after-e.json
.venv/bin/python -m pytest --cov=schem2net --cov-fail-under=80
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Set `AUDIT_LIBRARY=bench/out/audit-2026-11-02/libraries` for library runs and
`AUDIT_SAMPLE=8` for the deterministic sample. Use a different phase name for
each configuration. Corpus manifests, truth, splits, trained assets and checked-in
benchmark baselines remain unchanged by development; upstream baseline changes
arrived only through the initial fast-forward.

## Next accuracy work

The largest remaining losses are missing/unnumbered parts and pins, especially
Eagle and Olimex. U10 shows why restoring detection alone is insufficient:
symbol-colored electrical continuations need consistent classification and
connectivity, while capacitor body strokes must remain body. Duplicate diode/LED
designators and their consequent numbering suppression are another concrete target.
Library geometry matching and hidden-pin recovery still require unambiguous unit
and pad evidence. The OpenLog pair needs a provenance decision independently of
algorithm development. No extra warnings or confidence caps were used to obtain
the measured gains here.

## Final repository state

The fixes are committed in small changes, using the repository's configured author:

- `3e57aa1` Preserve library pin names and unit boundaries
- `822dc5f` Apply page limits during PDF ingestion
- `2947a7d` Keep benchmark issues aligned with scored pins
- `3133de8` Use spatial searches for schematic wire labels
- `30cd763` Fix wire crossings and section frames

This report, the initial audit report, README, benchmark documentation and changelog
are committed together afterward. Main is six commits ahead of the fetched
origin/main. No changes are staged or left in tracked files. The user's PDF remains
untracked and its SHA-256 matches the pre-reconciliation hash. The safety stash
`3c4c65e32bb1224cc4411da57667e3ca72d420de` is retained. Generated evidence stays
under ignored `bench/out/`; no benchmark output or PDF is committed.

Complete final `git status --short`:

```text
?? schem2net_build_plan.pdf
```

No history was rewritten and nothing was pushed or published.
