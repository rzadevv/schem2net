# Reliability and extraction runtime

Development evaluation, 4–5 November 2026. Starting commit: `1934cda`.
Ending implementation commit: `cd7dfbbb81acbfd2c5766ac90cdf284bf60fa0fa`.
The final repository commit is recorded in `bench/out/reliability-2026-11-04/commits.json`.

Across 198 development designs and 55,853 truth pins, correct pins rise from 49,667 to 49,843.
Missing pins fall by 166, wrong pins by 10, scored silent wrong pins by 18, and extra numbered
pins by 9. There are 66 more exact nets. Review precision falls by 0.5594 percentage points; the
lower review burden and remaining field errors are documented below.

Scored electrical results change in 10 designs from 7 source groups.
One additional complete output changes only its unattached-label notices.

## Confirmed failures and changes

**Reference ownership.** The joint field assignment could name a nearby body after
its device value while sending its real reference to a distant small drawing.
The later recovery pass then used a different unused name. On A10/A20 Micro,
FET1 went to D4's body and PWR_LED went to the transistor. On AM3352, D5 went
to a test pad and GND_PIN went to the TVS. The same pattern affected LCD
transistors, AM3352's UEXT connector, and Tsunami's J10 header.

The correction reserves nearby references only when the nearer body currently
holds a weak, unusual reference from a detected value pass. The existing model,
drawing-order evidence, functional-name reach and separation between body pieces
supply the checks. Standard references, supported unusual references, isolated
fields and close competitors keep their existing treatment. No device names,
board names or new text patterns enter the rule.

All four reported extra numbered pins disappear; both false reference associations are removed.
This does not recover the real
PWR_LED's two terminals or the GND_PIN test pad. Their geometry/identity problems
remain. The corrected TVS still receives guessed numeric pads instead of the
truth's A/C names: D5.2 is one newly scored extra, on a 0.6-confidence ground net
and explicitly named by a `pin_number_guessed` issue.

**Confidence and review.** FET1 in LCD 10TS was attached to the voltage-selection
jumper. Its alleged pin 1 shared a fragment with the transistor's drain at
confidence 1.0. FET1 now belongs to the actual transistor; its gate is associated
with the real pull-down fragment, and the existing unnumbered-pin issue follows
that gate. Scored FET1.1 becomes correct. The displaced IRLML6402 value still names the
jumper incorrectly, and some of its unscored fragments retain high confidence.
This residual field error is recorded explicitly: a lower scored silent-error
count does not establish that all high-confidence identities are correct.

On both LCD boards, false R32/T1 terminals on a supply mark had made an incomplete
fragment appear terminated. Moving these references to their actual bodies
exposes the unresolved wire end to the existing confidence policy. Ten silent
wrong pins become flagged. Thresholds and warning rules are unchanged. The
supply-mark interpretation itself still needs work.

**Glyph recognition.** Profiling the real nRF52840 extraction found 262,180
segment-distance calls; they consumed 12.0 of 26.6 profiled seconds. The fallback
recomputed scaled query arrays for every excluded template, and each distance
used four separate NumPy endpoint broadcasts. The implementation now reuses the
scaled queries, computes endpoint distances with SciPy's existing compiled
`cdist` kernel, and avoids repeated linear candidate-membership searches.
Candidate filters, scales, thresholds, ambiguity handling and strong-read early
returns retain their meaning. No dependency was added.

All 6,376 uncached glyph decisions from nRF52840, Tsunami and Qwiic 9DoF, and all
738 fold-template reads, match the baseline recognizer. The
optimization alone produces identical complete designs on all 198 development
cases and all 97 library-enabled cases. This preserves the earlier MDBT50Q
numeric-pad corrections and legitimate alphanumeric labels. Remaining fallback
work compares plausible alternative characters and scales so ambiguous reads
remain ambiguous.

**Bus connectivity.** A parsed bus name could still follow the scalar-wire path
when its printed color did not classify it as a bus. Repeated `{Main-BUS}` labels
therefore joined three unrelated GPIO nets on RP2350-PC at confidence 0.9.
Parsed, unoutlined bus names now attach to bus geometry. Existing outlined bus
and hierarchical-label handling remains in place. The resulting GPIO9, GPIO33
and GPIO40 nets are physically separate. The same correction separates HDMI SCL
from HPD on VGA2HDMI.

**Unpopulated parts and touching bodies.** RP2350-PC and ESP32-P4-PC print visible,
crossed-out components in a KiCad gray palette missing from the profile. Their
body, field and pad-number colors are now recognized by three exact profile
entries. Pale fills, DNP crosses and unrelated gray drawing remain excluded.

Restoring these drawings exposed capacitor plates whose ends touch adjacent
resistor bodies. An existing plate-rejection pass already recognizes a body
stroke when another pin starts at its middle. It now also handles that stroke
ending on a separate closed body across a reference boundary. This repairs
C37/R25 and the corresponding ESP32 case while preserving pin names such as A1,
R2 and D3 within their own component drawings. C35 also moves from the RP2350
power switch to its actual gray capacitor, removing two invented pad numbers.
R10.1 changes from an isolated fragment to the USB_D- network; the palette also
provides body-role context to the existing unknown-text classifier.

## Electrical results

The baseline is the accepted cached output of `1934cda`, including its library
runs. All comparisons use the same 198 development designs, four existing
out-of-fold model sets, truth files, source groups and inputs. Embedded netlists
are disabled. No protected test or holdout extraction was run.

| Corpus | Correct | Missing | Wrong | Silent wrong | Extra | Exact nets |
|---|---|---|---|---|---|---|
| A | 21,504 → 21,504 | 1,614 → 1,614 | 275 → 275 | 64 → 64 | 4 → 4 | 4,509 → 4,509 |
| B | 4,527 → 4,527 | 296 → 296 | 140 → 140 | 25 → 25 | 3 → 3 | 762 → 762 |
| C | 5,096 → 5,112 | 740 → 724 | 96 → 96 | 11 → 11 | 106 → 106 | 1,086 → 1,094 |
| D | 8,878 → 9,038 | 1,474 → 1,324 | 367 → 357 | 70 → 52 | 102 → 93 | 1,647 → 1,705 |
| E | 2,321 → 2,321 | 410 → 410 | 205 → 205 | 33 → 33 | 1 → 1 | 401 → 401 |
| F | 7,341 → 7,341 | 319 → 319 | 250 → 250 | 42 → 42 | 43 → 43 | 1,507 → 1,507 |
| ALL | 49,667 → 49,843 | 4,853 → 4,687 | 1,333 → 1,323 | 245 → 227 | 259 → 250 | 9,912 → 9,978 |

Retained steps, each compared on all six development corpora and both library corpora:

| Step | Δ correct | Δ missing | Δ wrong | Δ silent | Δ extra | Δ exact |
|---|---|---|---|---|---|---|
| Reference ownership | +32 | -30 | -2 | -11 | -7 | +16 |
| Glyph optimization | +0 | +0 | +0 | +0 | +0 | +0 |
| Bus routing | +6 | +0 | -6 | -6 | +0 | +3 |
| Gray palette / body plates | +138 | -136 | -2 | -1 | -2 | +47 |

| Corpus | Pin accuracy | Pair-weighted F1 | Macro F1 | Extra-pin rate |
|---|---|---|---|---|
| A | 91.9249% → 91.9249% | 94.5490% → 94.5490% | 91.2898% → 91.2898% | 0.0171% → 0.0171% |
| B | 91.2150% → 91.2150% | 90.3383% → 90.3383% | 86.0800% → 86.0800% | 0.0604% → 0.0604% |
| C | 85.9069% → 86.1767% | 85.6130% → 85.7376% | 84.6318% → 84.6474% | 1.7869% → 1.7869% |
| D | 82.8249% → 84.3176% | 78.7946% → 79.6503% | 84.8575% → 86.0548% | 0.9516% → 0.8676% |
| E | 79.0531% → 79.0531% | 67.2496% → 67.2496% | 77.9249% → 77.9249% | 0.0341% → 0.0341% |
| F | 92.8066% → 92.8066% | 96.9311% → 96.9311% | 89.1026% → 89.1026% | 0.5436% → 0.5436% |
| ALL | 88.9245% → 89.2396% | 92.5180% → 92.5596% | 86.3685% → 86.4901% | 0.4637% → 0.4476% |

Paired 95% group-bootstrap intervals, in percentage points, use the fixed scorer and 2,000
source-group resamples:

| Corpus | Δ pin accuracy [95% CI] | Δ pair F1 [95% CI] | Δ macro F1 [95% CI] | Δ silent rate [95% CI] |
|---|---|---|---|---|
| A | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| B | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| C | +0.2697 [+0.0000, +0.7385] | +0.1247 [+0.0000, +0.3349] | +0.0156 [+0.0000, +0.0474] | +0.0000 [+0.0000, +0.0000] |
| D | +1.4927 [+0.2764, +4.6011] | +0.8558 [+0.1177, +4.4495] | +1.1973 [+0.1667, +3.0071] | -0.1679 [-0.3018, +0.0000] |
| E | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| F | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| ALL | +0.3151 [+0.0493, +0.6996] | +0.0417 [+0.0037, +0.3787] | +0.1216 [+0.0151, +0.2559] | -0.0322 [-0.0714, +0.0000] |

Development source-family dependence remains important; these are not unseen-design confidence intervals.

Overall extra-pin-rate change: -0.0161 [-0.0401, +0.0000] percentage points (95% interval).


## Changes by design and pin

| Design | Δ correct | Δ missing | Δ wrong | Δ silent | Δ extra | Δ exact |
|---|---|---|---|---|---|---|
| C: Tsunami | +16 | -16 | +0 | +0 | +0 | +8 |
| D: ESP32-EVB | +2 | -2 | +0 | +0 | +0 | +1 |
| D: ESP32-P4-PC | +58 | -58 | +0 | +0 | +0 | +21 |
| D: A10/A20 Micro | +3 | -3 | +0 | +0 | -4 | +0 |
| D: LCD OLinuXino 7TS | -1 | +1 | +0 | -5 | +0 | +0 |
| D: AM3352 | +11 | -10 | -1 | +0 | -3 | +8 |
| D: LCD 10TS | +3 | -2 | -1 | -6 | +0 | +0 |
| D: RP2350-PC | +69 | -64 | -5 | -4 | -2 | +18 |
| D: UEXT-3to5V | +4 | -4 | +0 | +0 | +0 | +3 |
| D: VGA2HDMI | +11 | -8 | -3 | -3 | +0 | +7 |
| F: BeagleBone Black | +0 | +0 | +0 | +0 | +0 | +0 |

BeagleBone Black has unchanged complete nets and components; five unattached scalar-label
notices for DDR vector buses disappear. All other raw changed designs appear above, including
changes that score no pins.

Reference ownership changes existing terminal identities; they do not repair
wire geometry. Gray-part recovery makes visible terminals available to the
existing graph. Plate rejection fixes which strokes are body and which are
pins. Bus routing changes actual net connectivity. The glyph optimization
changes neither the complete output nor its scores.

| Pin transition | Count |
|---|---|
| correct -> missed | 1 |
| flagged wrong -> correct | 2 |
| missed -> correct | 167 |
| silent wrong -> correct | 8 |
| silent wrong -> flagged wrong | 10 |

There are 10 removed extra pins and 1 added extra pin (the flagged D5.2 described above). The
sole adverse scored transition is LCD OLinuXino 7TS T1.1, correct → missing: its reference moves
off a one-pin supply graphic onto the real three-terminal transistor, whose pad numbers remain
unresolved. This removes an accidentally correct identity association. No scored pin becomes
newly wrong or newly silent.

ESP32-EVB C39 and UEXT-3to5V C7/C10 use the newly recognized gray palette. VGA2HDMI C22/R11 and
C23/R16 instead use ordinary red graphics and benefit from the closed-body plate correction.
Their reference/value texts, terminal coordinates and source colors are recorded in
`additional-cases.json`; this is evidence beyond the two targeted boards.

Full aligned pin transitions, extra-pin additions/removals, component bounds,
terminal coordinates, issues and affected nets are retained under
`bench/out/reliability-2026-11-04/`:

- `final-results-pins.json`, `final-results-extras.json`.
- [Readable pin ledger](../bench/out/reliability-2026-11-04/pin-changes.csv) and
  [extra-pin ledger](../bench/out/reliability-2026-11-04/extra-pin-changes.csv).
- `final-library-pins.json`, `final-library-extras.json`.
- `confidence-forensics.json`, `physical-bus-evidence.json`.
- `glyph-output-equivalence.json`, `glyph-replay.json`, `font-replay.json`.
- `timing.json`, `timing-summary.json`, `provenance.json` and frozen phase reports.

Accepted predictions are in `plates/` and `plates-lib/`, with source in
`plates-source/`. The `near`, `dnp` and `palette` trials are rejected diagnostics.

## Review and library comparisons

| Corpus | Wrong-pin review recall | Review precision | Items per 100 pins |
|---|---|---|---|
| A | 76.7273% → 76.7273% | 40.8360% → 40.8360% | 2.6589 → 2.6589 |
| B | 82.1429% → 82.1429% | 34.3643% → 34.3643% | 11.7268 → 11.7268 |
| C | 88.5417% → 88.5417% | 30.8010% → 30.7438% | 20.4147 → 20.3978 |
| D | 80.9264% → 85.4342% | 64.3040% → 62.6866% | 10.9245 → 10.6260 |
| E | 83.9024% → 83.9024% | 49.4737% → 49.4737% | 16.1785 → 16.1785 |
| F | 83.2000% → 83.2000% | 52.8474% → 52.8474% | 5.5499 → 5.5499 |
| ALL | 81.6204% → 82.8420% | 45.4889% → 44.9295% | 8.0569 → 7.9978 |

Overall review-precision change: -0.5594 [-1.3542, -0.0571] percentage points; burden change:
-0.0591 [-0.1466, -0.0017] items per 100 pins (95% intervals).


Total scored review items change 4,500 → 4,467; useful items 2,047 → 2,007; scored
false-positive items 2,453 → 2,460. The reduction in total burden does not erase the precision
cost. Corpus D review precision changes -1.6174 [-6.8002, -0.1916] percentage points (95%
interval).

Review precision measures useful review items, and burden counts review items
per 100 truth pins. Pin-addressed review recall covers wrong pins under the fixed
scorer; missing pins remain a separate failure class. Extra numbered pins are
reported separately from wrong connections. False references outside the truth
are not fully represented by the extra-pin count. Component precision and recall
count reference-name matches, not correct physical ownership; removing a wrongly
placed GND_PIN can lower nominal reference recall without losing a real test pad.

| Corpus | Correct | Missing | Wrong | Silent | Extra | Exact | Pair F1 | Macro F1 |
|---|---|---|---|---|---|---|---|---|
| C | 5,143 → 5,159 | 692 → 676 | 97 → 97 | 11 → 11 | 106 → 106 | 1,109 → 1,117 | 87.2581% → 87.3792% | 85.7487% → 85.7642% |
| D | 8,878 → 9,038 | 1,474 → 1,324 | 367 → 357 | 70 → 52 | 102 → 93 | 1,647 → 1,705 | 78.7946% → 79.6503% | 84.8575% → 86.0548% |

All 78 C and 19 D library designs were evaluated at each retained step. Every library comparison
gate passes; the same sole scored pin loss is documented in the full aligned library ledger.
Glyph optimization changes no complete library output.

## Runtime

| Case | Median wall seconds | Change | Median CPU seconds | Change |
|---|---|---|---|---|
| nRF52840 | 15.449 → 11.996 | -22.4% | 15.339 → 11.901 | -22.4% |
| Tsunami | 22.244 → 18.477 | -16.9% | 22.043 → 18.376 | -16.6% |
| iMX233 Maxi | 7.927 → 6.269 | -20.9% | 7.872 → 6.223 | -20.9% |

The trials use fresh processes, one CPU affinity, interleaved version/case order,
three repetitions per case, no library, no embedded netlist, and the same frozen
fold assets. AMD Ryzen 5 5600H with Radeon Graphics; Python 3.13.15, NumPy 2.5.3, SciPy 1.18.1.
Timing covers extraction, excluding imports, scoring and output
comparison. Every timed complete output must equal its own version's scientific
prediction. Scientific batch elapsed times are not used as runtime evidence;
those runs overlap and some resume from completed per-design caches.

## Rejected experiments and safeguards

- A general nearest-body restriction changed unrelated assignments. The retained
  rule is limited to bodies currently named by weak values; it removes the four
  false identities without those unrelated changes.
- Adding the gray palette alone recovered 110 correct pins in the two targeted
  boards, but lost four previously correct resistor pins and exposed two new
  silent wrong pins on the existing bus short. That trial was not retained.
- Restricting every pin's body contacts across reference-shaped text failed corpus
  A: 1,277 fewer correct pins, 1,248 more missing pins and 29 more wrong pins.
  Legitimate pin names can look like references. That code was removed; the
  narrower plate correction passes explicit counterexamples and the full corpus
  comparisons. Completed and partial rejected artifacts remain diagnostic only.

The scorer, confidence thresholds, development splits, fixed baselines, models,
library indexes and dependencies are unchanged. Hash checks cover all 198
PDF/truth pairs, all 20 fold assets and both library indexes. The original user
PDF and safety stash retain their original hashes. No history was rewritten.

## Validation and independent evaluation

371 tests pass with 82.83% total statement coverage on Python 3.13.15/Linux; Ruff lint and
formatting checks pass. New ownership positives fail on the starting source (six failures, four
controls pass); the bus positives fail before the routing fix (six failures, two scalar controls
pass); both touching-body orientations fail before the plate fix. Three reference-shaped
pin-name controls reject the broad drawing-order trial. Existing strong/ambiguous glyph and
alphanumeric-pad controls pass.

All six grouped out-of-fold comparison gates pass for every retained step and for the complete
change. The C/D library gates pass throughout. CI-style A/E extraction with shipped models and
fixed repository baselines also passes. These local checks do not execute the full CI Python
matrix, Windows or a distribution build. Timing covers three Eagle designs, not a generator-wide
runtime survey.

Native CLI reproduction uses `schem2net bench <corpus> --split dev --drawing-only --folds
bench/out/folds --json <report>` for each of a–f under the selected frozen source. Add
`--library bench/out/audit-2026-11-02/libraries` for C/D. Use fresh report paths and the
recorded input/model hashes; CI-style shipped-model runs are a separate configuration.

The next release gate is a frozen independent evaluation with the existing review
workflow. Remaining high-confidence identity errors prevent an unsupervised release claim.
Repeated tuning on the same development panel and source-family
correlation limit the evidence for new designs. These results establish local
engineering improvements, not an independent estimate of release accuracy.

Before any independent extraction:

1. Freeze the implementation commit, lockfile, Python environment, shipped model
   assets, library indexes and scoring code; record their hashes. Do not retrain
   on the independent sample.
2. Assemble at least 60 correctly paired unseen designs from at least 40 source
   groups spanning the supported generators, large and small parts, populated and
   visible DNP parts, functional references, alphanumeric pads and bus labels.
   Keep all revisions/siblings of each source together, and exclude groups already
   used for development or model training.
3. Verify each PDF and CAD netlist came from the same revision and variant before
   extraction. Record source commit, filenames, hashes, group, generator and
   inclusion decision in an immutable manifest. Define treatment of hidden pins,
   label scope and visible DNP terminals in advance. Quarantine ambiguous pairs
   before looking at extraction scores. Existing OpenLog pairing concerns stay
   separate; no current benchmark row is removed or repaired to improve results.
4. Read the manifest once with the frozen baseline and candidate. Use
   `profile.use_learned(None)`, `pipeline.extract(pdf, embedded=False)` and the
   unchanged `schem2net.bench.score.score(predicted, kicad.read_netlist(truth))`. Save every complete
   prediction, raw count and issue; use the same manifest order and source-group
   bootstrap in `schem2net.bench.score.compare`. Run library-enabled extraction as a separately
   declared secondary comparison, with the same frozen indexes.
5. Pre-register acceptance: no failed pages; no decrease in primary pin accuracy
   (paired group-bootstrap lower bound at least zero); no increase in silent-error
   rate or extra-pin rate (upper bounds at most zero); and no newly introduced
   unsupported high-confidence identity after blinded adjudication. Report pair
   and macro F1, exact nets, missing pins, component precision/recall and review
   metrics even if a primary gate fails. Require median extraction CPU/wall time
   no more than 5% worse and no material review-burden increase without a measured
   gain in error detection.
6. Run the supported Python CI matrix and a packaged CLI smoke test against the
   frozen artifact. Archive all outcomes, including failures. If gates
   fail, reject that release candidate; any later implementation tuning requires
   a fresh independent evaluation panel. Do not reuse the same panel to tune and
   claim an independent result. These sample sizes are planning minimums, not a
   power guarantee; an inconclusive interval remains inconclusive.

## Most valuable unresolved problems

1. Remaining body/reference and power-mark ownership: large A10/A20 connector
   identities, the real LED/test-pad identities, and the LCD supply fragments.
   Correct body association and library roles must precede more functional-name
   recovery.
2. Incomplete pin/fragment interpretation, including Nolman U10.12's wire-classified
   root. No new root rule was justified here; proximity to a body remains
   insufficient evidence. Missing and unnumbered terminals still dominate many
   failures.
3. Strong but wrong glyph/pad identities and confidence calibration, including
   P0.2O-style reads and the TVS A/C mismatch. The optimized weak-read fallback
   deliberately preserves strong-read behavior; current review precision and
   remaining silent errors require independent measurement before broader changes.

## Commits and repository state

- `a82e2d2` Keep nearby references with their component bodies
- `89d7d3f` Speed up glyph distance comparisons
- `0eb467d` Keep bus labels off scalar wires
- `cd7dfbb` Read unpopulated parts without merging neighboring bodies

Implementation is committed locally. Final status is checked after the documentation commit:
tracked files clean; only the original `schem2net_build_plan.pdf` remains untracked. Nothing was
pushed or published. The safety stash is preserved.
