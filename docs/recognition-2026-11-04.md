# Recognition and field ownership — 2026-11-04

This phase starts at `f968e86cdcc4d7c392bac60229ab1e2415247260`, preserving the
accepted connector recovery. The baseline contains 198 development designs,
55,853 scored pins, 49,401 correct pins, 5,095 missing pins, 1,357 wrong pins,
245 silent wrong pins and 9,773 exact nets. These are grouped out-of-fold
development results, with embedded netlists disabled. The retained changes add
266 correct pins and 139 exact nets across 26 designs: 18 Eagle, seven Olimex and
one mixed-source design. Missing pins fall by 242 and wrong pins by 24; total
silent wrong pins remain 245. Gains span multiple designs, with much of the
Olimex gain concentrated in AM3352 and Maxi.

Those changed designs span 17 C source groups, two D groups and one E group.
The Eagle result therefore extends across multiple source projects. The Olimex
result is concentrated in the OLINUXINO and SOM repositories, with shared export
conventions; its bootstrap lower bounds include zero. A/B/F electrical counts
remain unchanged. This establishes a broader development improvement within the
Eagle/Olimex cases, with limited evidence across other generators.

## Choosing the work

The existing prediction ledgers give the following starting symptom counts.
These buckets describe extraction output, not independently proven causes or
recoverable-pin estimates. In particular, an unnumbered pin need not be a glyph
failure, and a missing pin need not have a wire-classified root.

| Symptom | C: Eagle | D: Olimex | E: mixed PDFs |
| --- | ---: | ---: | ---: |
| Part missing | 277 | 737 | 167 |
| Unnumbered pin | 371 | 615 | 107 |
| Pin missing | 63 | 117 | 90 |
| Split net | 55 | 282 | 50 |
| Renumbered pin | 44 | 67 | 140 |

Glyph candidate exclusion was the best supported first opportunity: the exact
missing `8` was already present in the fixed font, and independent Eagle designs
had unread references and repeated net names. It required no new model or OCR
dependency. Field ownership then offered larger recoveries in Olimex, with
actual printed references and values available for comparison. Repeated labels
provided independent evidence for some of the remaining physical fragments.

The known Nolman U10.12 root requires reconciling both a wire-classified root and
a shape-classified continuation. The earlier numbered-edge trial recovered
nothing, as [previously documented](connector-recovery-2026-11-03.md). No new
bounded correction with adequate negative evidence was established here. The
symptom ledger does not establish its prevalence, so no recurring-case count or
accuracy gain is claimed for that class. No boundary-proximity fallback was
added, and the requested device-family counterexample suite remains necessary
before accepting such a rule.

## Corrections retained

### Glyph candidates across curve decompositions

The original matcher excluded templates whose segment count differed by more
than four. On MDBT50Q, seven uncached `o`-to-`8` decisions involve 22 query
segments and a 32-segment stored `8`; their geometric distances are
0.05699–0.05940, within the existing strong-match threshold of 0.06. The real
printed pad tokens `2o`, `4o` and `5o` become `28`, `48` and `58`.

Strong existing reads keep their original fast path. Only weak or absent reads
consider templates excluded by segment count. The fallback retains the existing
aspect filter, scales and geometric thresholds, using normalized ink length as
a coarse filter. A unique strong character can replace a weak read; an absent
read can accept a single plausible character. Competing identities preserve the
original result. Template lengths are prepared once per font table.

A synthetic two-loop glyph with 22 versus 32 chords reproduces the exclusion.
Controls cover indistinguishable `8`/`B` templates, an existing strong `B`, an
unrelated shape, and legitimate alphanumeric labels. All 738 template entries
across the four fixed folds retain their original interpretation. Native replays
on MDBT50Q, Tsunami and Qwiic 9DoF retain every changed matcher decision and text;
these replays are not a fully human-labelled false-substitution estimate.

### Pin-name ownership and overlaid alternatives

Numbered pins previously did not compete for their printed names. An adjacent
unnumbered pin could therefore borrow the name already belonging to a numbered
pin. Correctly decoding `P0.08` exposed this on MDBT50Q: the extra alias created
another scored occurrence of U1.24 on a different fragment. All pins now compete
under the existing geometry, with numbered pins reserving their own text while
retaining their number and provenance. This removes the erroneous alias.

The shared-prefix alternative-name rule now sees unnamed competing bodies too.
An alternate name nearer another pinned body is rejected before the existing
complete-stack and repeated-geometry checks. A focused test reproduces an
unrelated same-prefix stack beside another unassigned body. Model features for
the previously retained symbols remain unchanged.

### Values mistaken for references

AM3352's printed `BH40S`/`BH20S` values were becoming references while `LCD_CON`
and `JTAG` became values. The existing value drawing pass and designator model
both identify the misleading part numbers as weak references.

The retained correction preserves the initial joint reference assignment. It
then offers an assigned unusual value-like name an unused functional name for
the same part, using the existing search geometry and model odds. The replacement
must be stronger by the existing rounded order of magnitude. Common references,
supported unusual references, explicit drawing-order ownership, and equal or
weaker alternatives remain protected. The displaced text remains available as
a value, and the reference-to-field mapping follows the replacement.

### Repeated names overhanging short wires

On Maxi, the printed `PIN12/LCD_D11/UEXT_CS` is wider than the short wire beneath
it. Only about 68% of its width overlaps that wire, so ordinary recognition's
90% rule misses it. Independently recognized occurrences establish the exact
net name elsewhere on the page.

After body grouping, a remaining field with an exact repeated name can label a short wire
when its baseline and start align under the existing placement constants,
there is at least one text-height of overlap, exactly one candidate wire exists,
and the text lies outside complete component bounds, including pins and the
existing stroke tolerance. Uncertain names, numeric values and
common references are excluded. This is enabled only in profiles that already
share field and on-wire label recognition. Fourteen horizontal/rotated fixtures
cover the positive case, unknown names, uncertainty, body interiors, ambiguous
wires, capacitor values and wrong baselines. Additional regressions protect a USB
pad name outside the body outline but within the pins' bounds, and a jumper's
reference printed over a wire.

Maxi's UEXT.10 fragment gains its printed name and joins GPIO_CON.13 and U1.25.
On A20, USB0-DRV/PB9 joins the PC17/PB9 fragment, LRADC0 joins R12, and CLK125
joins R66. LCD_HSYNC also joins R58.2, and LCD_VSYNC joins FET4's unnumbered
gate fragment. These five A20 joins are raw predicted-net changes supported by PDF labels, not
joins inferred from truth-net equality.

## Experiments rejected

An initial fallback accepted only newly strong glyph reads. It corrected one
Tsunami BCLK occurrence but left another unread, creating two newly silent pins.
The retained unique-plausible fallback repairs both occurrences. A broader trial
replaced the segment-count filter globally with ink length; it was not retained
because it also revisited strong reads and expanded the work unnecessarily.

The first value experiment removed weak unusual candidates before joint field
assignment. Although its completed D run improved totals, per-pin review found
R118/R119 ownership shifts on A10/A20 Micro and lost R39/R27 identities. The
resistors' physical positions were unchanged while references moved. That version
was rejected; its remaining full-run jobs were stopped. Its completed D reports,
partial C predictions and source snapshots are kept as diagnostic evidence.
The retained version preserves the joint assignment and these neighboring
references. No unsuccessful variant remains in production code.

The first short-label version protected body outlines but omitted pin extents.
Its full Eagle run lost 17 correct pins and added seven silent errors relative
to the preceding stage: USB D+/D- fields became labels, and GEO/RTK/TP jumper
names disappeared. That version failed the six-corpus acceptance comparison.
Protecting all previously claimed text was also unsuitable: existing incorrect
field ownership then blocked the real Maxi label. Both variants were removed.
The retained geometric guard uses the complete part bounds, with the existing
touch tolerance; it preserves all five affected Eagle examples in focused real
PDF runs while keeping the Maxi and A20 physical repairs.

## Development results

Each cell is starting baseline → final. Silent wrong is wrong minus wrong flagged; it is a subset of wrong. All six comparison gates pass.

| Corpus | Correct | Missing | Wrong | Silent wrong | Exact nets |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 21,504 → 21,504 | 1,614 → 1,614 | 275 → 275 | 64 → 64 | 4,509 → 4,509 |
| B | 4,527 → 4,527 | 296 → 296 | 140 → 140 | 25 → 25 | 762 → 762 |
| C | 4,984 → 5,096 | 840 → 740 | 108 → 96 | 11 → 11 | 1,038 → 1,086 |
| D | 8,725 → 8,878 | 1,616 → 1,474 | 378 → 367 | 70 → 70 | 1,556 → 1,647 |
| E | 2,320 → 2,321 | 410 → 410 | 206 → 205 | 33 → 33 | 401 → 401 |
| F | 7,341 → 7,341 | 319 → 319 | 250 → 250 | 42 → 42 | 1,507 → 1,507 |
| All | 49,401 → 49,667 | 5,095 → 4,853 | 1,357 → 1,333 | 245 → 245 | 9,773 → 9,912 |

| Corpus | Pin accuracy | Missing rate | Silent rate | Pair-weighted F1 | Macro F1 | Exact-net rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 91.92493% → 91.92493% | 6.89950% → 6.89950% | 0.27359% → 0.27359% | 94.54896% → 94.54896% | 91.28978% → 91.28978% | 88.82979% → 88.82979% |
| B | 91.21499% → 91.21499% | 5.96413% → 5.96413% | 0.50373% → 0.50373% | 90.33833% → 90.33833% | 86.07996% → 86.07996% | 74.12451% → 74.12451% |
| C | 84.01888% → 85.90695% | 14.16049% → 12.47471% | 0.18543% → 0.18543% | 83.21980% → 85.61298% | 83.44292% → 84.63180% | 62.79492% → 65.69873% |
| D | 81.39752% → 82.82489% | 15.07603% → 13.75128% | 0.65305% → 0.65305% | 77.97821% → 78.79457% | 84.23934% → 84.85748% | 59.48012% → 62.95872% |
| E | 79.01907% → 79.05313% | 13.96458% → 13.96458% | 1.12398% → 1.12398% | 67.24955% → 67.24955% | 77.92486% → 77.92486% | 58.71157% → 58.71157% |
| F | 92.80657% → 92.80657% | 4.03287% → 4.03287% | 0.53097% → 0.53097% | 96.93114% → 96.93114% | 89.10260% → 89.10260% | 83.12190% → 83.12190% |
| ALL | 88.44825% → 88.92450% | 9.12216% → 8.68888% | 0.43865% → 0.43865% | 92.45167% → 92.51796% | 85.84421% → 86.36852% | 75.94219% → 77.02230% |

### Incremental effects

Deltas use the immediately preceding stage. The reference-only stage is an intermediate measurement: it exposes UEXT.10 on an incomplete fragment. It is retained together with the repeated-label reconstruction, not as a separate accepted endpoint.

| Step | Correct | Missing | Wrong | Silent wrong | Exact nets |
| --- | ---: | ---: | ---: | ---: | ---: |
| Glyph candidates | +93 | -90 | -3 | +0 | +40 |
| Pin-name ownership and prefix guard | +28 | -17 | -11 | +0 | +10 |
| Value/reference ownership | +129 | -132 | +3 | +2 | +76 |
| Repeated labels | +16 | -3 | -13 | -2 | +13 |

### Designs with electrical-count changes

| Design | Correct | Missing | Wrong | Silent wrong | Exact nets |
| --- | ---: | ---: | ---: | ---: | ---: |
| C / 2d barcode scanner breakout | 53 → 55 | 10 → 8 | 6 → 6 | 0 → 0 | 9 → 9 |
| C / ft232rl usb breakout | 52 → 55 | 11 → 9 | 5 → 4 | 4 → 4 | 13 → 14 |
| C / lte cat m1 shield | 170 → 182 | 43 → 31 | 12 → 12 | 0 → 0 | 33 → 38 |
| C / mp3 player shield | 159 → 161 | 34 → 34 | 2 → 0 | 0 → 0 | 24 → 26 |
| C / nrf52840 breakout mdbt50q | 119 → 135 | 43 → 30 | 3 → 0 | 0 → 0 | 11 → 16 |
| C / qwiic button | 50 → 51 | 13 → 13 | 1 → 0 | 0 → 0 | 8 → 8 |
| C / qwiic grideye | 39 → 40 | 3 → 3 | 1 → 0 | 0 → 0 | 8 → 8 |
| C / qwiic shield for teensy | 37 → 38 | 3 → 2 | 0 → 0 | 0 → 0 | 6 → 7 |
| C / qwiic shield for teensy extended | 39 → 41 | 4 → 2 | 0 → 0 | 0 → 0 | 5 → 7 |
| C / serial basic breakout-ch340c | 44 → 45 | 3 → 2 | 1 → 1 | 0 → 0 | 12 → 12 |
| C / qwiic 9dof imu breakout | 63 → 77 | 50 → 34 | 2 → 4 | 0 → 0 | 1 → 2 |
| C / qwiic led stick | 79 → 83 | 34 → 30 | 3 → 3 | 0 → 0 | 18 → 22 |
| C / qwiic micro samd21e | 83 → 86 | 16 → 14 | 4 → 3 | 0 → 0 | 21 → 22 |
| C / qwiic phat extension | 69 → 70 | 0 → 0 | 1 → 0 | 0 → 0 | 30 → 31 |
| C / qwiic pocket dev board esp32 c6 | 115 → 117 | 4 → 2 | 2 → 2 | 0 → 0 | 29 → 31 |
| C / tsunami super wav trigger qwiic | 480 → 524 | 73 → 32 | 4 → 1 | 0 → 0 | 91 → 113 |
| C / teensy arduino shield adapter | 78 → 80 | 20 → 19 | 2 → 1 | 0 → 0 | 24 → 25 |
| C / wifi shield-da16200 | 103 → 104 | 25 → 24 | 4 → 4 | 2 → 2 | 23 → 23 |
| D / A10/A20 Micro | 1,660 → 1,676 | 373 → 359 | 131 → 129 | 24 → 24 | 296 → 302 |
| D / LCD 7TS | 286 → 289 | 46 → 43 | 17 → 17 | 8 → 8 | 42 → 42 |
| D / AM3352 | 1,309 → 1,352 | 270 → 226 | 27 → 28 | 4 → 4 | 191 → 222 |
| D / LCD 10TS | 211 → 213 | 54 → 51 | 17 → 18 | 7 → 8 | 37 → 38 |
| D / iMX233 Maxi | 511 → 568 | 158 → 102 | 45 → 44 | 1 → 0 | 53 → 87 |
| D / iMX233 Micro | 405 → 412 | 90 → 87 | 45 → 41 | 2 → 2 | 69 → 75 |
| D / A20 SOM EVB | 834 → 859 | 207 → 188 | 35 → 29 | 1 → 1 | 189 → 202 |
| E / cyborg-sch-cyborg | 708 → 709 | 113 → 113 | 20 → 19 | 3 → 3 | 106 → 106 |

### Paired uncertainty and review burden

The fixed scorer supplies paired 95% bootstrap intervals over source groups. Values below are percentage-point deltas and their intervals. A/B/F accuracy and connection metrics are unchanged. These development samples have guided repeated algorithm choices; the intervals do not establish independent generalization.

| Corpus / metric | Delta | 95% interval |
| --- | ---: | ---: |
| C / pin_accuracy | +1.88806 | +0.65932 to +3.18527 |
| C / connection_f1 | +2.39319 | +0.60188 to +4.50139 |
| C / macro_connection_f1 | +1.18888 | +0.38623 to +2.40913 |
| C / net_exact | +2.90381 | +0.87534 to +5.18370 |
| D / pin_accuracy | +1.42737 | +0.00000 to +1.95069 |
| D / connection_f1 | +0.81635 | +0.00000 to +0.99033 |
| D / macro_connection_f1 | +0.61815 | +0.00000 to +1.01888 |
| D / net_exact | +3.47859 | +0.00000 to +4.84354 |
| E / pin_accuracy | +0.03406 | +0.00000 to +0.07854 |
| E / connection_f1 | +0.00000 | +0.00000 to +0.00000 |
| E / macro_connection_f1 | +0.00000 | +0.00000 to +0.00000 |
| E / net_exact | +0.00000 | +0.00000 to +0.00000 |

| Corpus | Review items / 100 pins | Review precision |
| --- | ---: | ---: |
| A | 2.66746 → 2.65892 | 40.70513% → 40.83601% |
| B | 11.72678 → 11.72678 | 34.36426% → 34.36426% |
| C | 21.08901 → 20.41470 | 35.17186% → 30.80099% |
| D | 11.04581 → 10.92453 | 65.37162% → 64.30401% |
| E | 16.28065 → 16.17847 | 49.37238% → 49.47368% |
| F | 5.54994 → 5.54994 | 52.84738% → 52.84738% |

### Separate library-enabled results

All 78 C designs and 19 D designs use the unchanged indexed Eagle/KiCad libraries and fixed folds. These results are separate from the library-free totals above. The baseline copies the accepted previous library artifacts; its two later defensive no-owner/power guards are absent from those cached artifacts, as documented in the preceding report. Final library extraction uses the exact retained source snapshot.

| Corpus | Correct | Missing | Wrong | Silent wrong | Exact nets |
| --- | ---: | ---: | ---: | ---: | ---: |
| C | 5,009 → 5,143 | 815 → 692 | 108 → 97 | 11 → 11 | 1,043 → 1,109 |
| D | 8,725 → 8,878 | 1,616 → 1,474 | 378 → 367 | 70 → 70 | 1,556 → 1,647 |

| Corpus | Pin accuracy | Pair-weighted F1 | Macro F1 | Exact-net rate | Review / 100 | Review precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C | 84.44032% → 86.69926% | 84.28158% → 87.25806% | 84.18881% → 85.74867% | 63.09740% → 67.09014% | 21.52731 → 21.25759 | 34.53406% → 28.86598% |
| D | 81.39752% → 82.82489% | 77.97821% → 78.79457% | 84.23934% → 84.85748% | 59.48012% → 62.95872% | 11.04581 → 10.92453 | 65.37162% → 64.30401% |

| Library corpus / metric | Delta, percentage points | Paired 95% interval |
| --- | ---: | ---: |
| C / pin_accuracy | +2.25893 | +0.74561 to +3.81038 |
| C / connection_f1 | +2.97648 | +0.89336 to +5.27207 |
| C / macro_connection_f1 | +1.55986 | +0.49434 to +3.02281 |
| C / net_exact | +3.99274 | +1.05998 to +7.06399 |
| D / pin_accuracy | +1.42737 | +0.00000 to +1.95069 |
| D / connection_f1 | +0.81635 | +0.00000 to +0.99033 |
| D / macro_connection_f1 | +0.61815 | +0.00000 to +1.01888 |
| D / net_exact | +3.47859 | +0.00000 to +4.84354 |


## Pin transitions and physical checks

Complete scored-pin ledgers are generated for every development design at each
retained stage, including designs whose aggregate counts cancel out. Raw
predictions remain available alongside the ledgers. Library-enabled transitions
are assessed separately. Newly wrong or missing pins are not excluded from the
reported totals.

All 285 changed pin-status transitions are retained. No scored pin becomes newly
missing. The transition totals are:

| Transition | Pins |
| --- | ---: |
| correct -> flagged wrong | 7 |
| flagged wrong -> correct | 34 |
| flagged wrong -> silent wrong | 1 |
| missed -> correct | 238 |
| missed -> flagged wrong | 4 |
| silent wrong -> correct | 1 |

The library-enabled MDBT50Q run also changes J2.6 from correct to flagged wrong
at the ownership step. Its raw singleton net, `P0.2O/AIN4`, and confidence 0.5
remain unchanged; the improved identity matching selects another fragment.
This regression is retained in the separate library ledger.

The glyph-only MDBT50Q regression at U1.24 is removed by reserving numbered pins'
printed names. Its numbered physical terminal never moved; the fault was a
second unnumbered terminal taking the same alias. Qwiic 9DoF still has
R11.1/R12.1 changing from correct to flagged wrong and R13.1 from missing to
flagged wrong. The resistors keep their two original physical terminals;
recovering their references changes passive-end normalization and exposes the
opposite orientation. These remain reported regressions.

AM3352 U1.E18 and U1.U14 change from correct to flagged wrong on unchanged
singleton fragments. U1.N15 and U1.R15 become scoreable through corrected name
ownership, but their raw unnamed pins remain on C161.2 and C122.2 fragments,
respectively. A20 R63.1 and UEXT2.5/6 likewise change to flagged wrong while their
raw net memberships remain unchanged. These are alignment consequences of
recovered identities, not new physical joins.

LCD 10TS FET2's printed name correctly replaces its `IRLML6402` value. Its
previously unscoreable D terminal becomes a flagged wrong FET2.3 on an incomplete
fragment. Separating FET2 also removes the old duplicate-`IRLML6402` warning.
The neighboring FET1.1 fragment keeps exactly the same members, but its confidence
rises from 0.6 to 1.0 under the unchanged policy, changing a flagged error to a
silent one. FET1's reference is still attached to a different small body; this
remains a real ownership/review limitation. No artificial warning or confidence
cap was added to conceal it. Maxi's UEXT.10, exposed as silent in the
reference-only intermediate stage, becomes correct through its printed repeated
label. Its R13.1 baseline silent error also resolves as the opposite resistor
terminal's physical connection restores passive-end alignment.

Numbered extra pins increase from 255 to 259. On A10/A20 Micro, PWR_LED takes a
MOSFET's pre-existing D/S terminals, previously filed under `IRLML6402`; the true
LED uses A/C pads. On AM3352, GND_PIN takes the existing 1/2 terminals previously
filed under `SMBJ16A`, while the true test pad uses P$1. All four positions and
terminal identifiers are unchanged, but these are incorrect recovered reference
identities. PWR_LED.D's fragment has confidence 1.0. The scorer tracks them as
extra pins, separately from scored wrong pins. They are included in
`extra-pin-ownership.json` and `extra-pin-geometry.json`, and remain a substantive
limitation of functional-name recovery. The glyph stage adds no extra pins.

Review precision also falls: C goes from 35.17% to 30.80%, and D from 65.37% to
64.30%, despite fewer review items per pin. The warning population changes as
names and connections recover; the confidence and warning rules are unchanged.
This cost accompanies the electrical-accuracy improvement and remains visible
in the tables and paired reports. C's precision delta is −4.37087 percentage
points, with a paired 95% interval of −7.84242 to −1.74976; D's interval is
−3.32334 to 0.00000. The C decline is therefore supported within this repeatedly
used development suite.

### Earlier A20 regressions

The preceding connector phase added 13 newly wrong pin assignments, offset by
two repairs for a net increase of 11. Six of those 13 now score correctly:
R58.1 and platform 4-21, 4-22, 4-40, LCD-8 and LCD-9. Seven remain flagged:
LDO3_2.8V_E.1, GPIO-2.6/22/24 and platform 2-1, 4-1 and LCD-3.

This count mixes identity, alignment and physical effects. In particular,
R58.1's own raw net is unchanged; the physical LCD_HSYNC join occurs on R58.2
and resolves passive-end alignment. LCD-8/9 first improve at the pin-name
ownership stage. The five raw A20 label joins are retained explicitly in
`a20-physical-label-joins.json`; no truth-based fragment merger was introduced.

## Remaining work and limits

The final symptom ledgers retain 184 part-missing, 368 unnumbered and 49 split
observations in C; D retains 572, 641 and 275, respectively. These are still
symptoms, not proven causes. RP2350-PC has 101 part-missing observations,
A10/A20 Micro 91 and ESP32-P4-PC 72, making ownership worth investigating across
more families.

The recurring opportunities are better ownership of references already claimed
by the wrong small body, unnumbered or disconnected pin fragments, and strong
but wrong glyph reads that this fallback deliberately leaves unchanged. The
LCD 10TS FET1 case illustrates the first problem; Nolman U10.12 illustrates why
the second needs role and continuation evidence together. Future pin-root rules
need positive and negative capacitor, transistor, diode, connector, amplifier
and ordinary-wire cases before entering production.

Library matching still needs careful unit and alphanumeric-pad handling; a
unique library identity cannot be assumed from a partial numeric sequence. The
OpenLog source mismatch remains in every comparison and is still a separate
dataset proposal. No input, truth, exclusion, scorer, fold model, confidence
policy or dependency was changed. No protected test or holdout sample was
evaluated. These repeatedly used development results support engineering
acceptance within the suite, not an independent deployment-accuracy estimate.

## Validation and performance

| Source stage | Tests | Coverage |
| --- | ---: | ---: |
| Glyph candidates | 320 | 82.59% |
| Pin-name ownership and prefix guard | 322 | 82.65% |
| Final reference and label recovery | 344 | 82.70% |

The intermediate reference-only snapshot also passes its 328 applicable tests
at 82.70% coverage. Final Ruff lint, formatting and diff checks pass. Separate
CI-style A/E development extraction and comparison gates pass using shipped
models; the scientific tables above use the fixed grouped out-of-fold models.
All runs use local Python 3.13.15. The CI Python-version matrix, Windows and a
distribution build were not run.

Three interleaved fresh-process trials per source and case measure extraction
only, with identical folds and no libraries. All 18 trials reproduce their
respective full-run counts. Other benchmark jobs were running, so host load is
not fully controlled; both wall and process CPU medians are reported.

| Design | Baseline wall | Final wall | Change | Baseline CPU | Final CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tsunami | 19.466 s | 22.926 s | +17.8% | 19.387 s | 22.737 s |
| MDBT50Q | 13.491 s | 16.322 s | +21.0% | 13.424 s | 16.224 s |
| iMX233 Maxi | 7.673 s | 8.421 s | +9.8% | 7.621 s | 8.373 s |

The observed wall-time cost is about 10–21% on these three selected cases.
The additional geometric glyph comparisons cost time; no general speed gain or
suite-wide performance estimate is claimed. Full samples are in `timing.json`.

## Provenance, commits and repository state

Evidence is under ignored `bench/out/recognition-2026-11-03/`. The accepted
endpoint is **`bounds-final`**, with **`bounds-final-lib`** for libraries and
`bounds-final-source/src` for the exact source. Earlier folders named `final`,
`stable-final`, `claimed-final` and `owned-final` are rejected experiments, not
accepted endpoints. `stable-values` is the reference-only intermediate stage.

`provenance.json` records all 198 PDF/truth hashes, 20 fixed fold assets, both
indexed library hashes, exact source snapshots, report hashes, accepted/rejected
phases and check results. Every input pair, model and library was verified
unchanged. Stored baseline reports are byte-for-byte copies of the preceding
accepted artifacts. Scorer, splits, dependency files and confidence policy are
unchanged. No protected test or holdout data was evaluated.

Full per-design counts, grouped paired intervals, all changed pin identities,
raw predictions, extra-pin ownership checks, real-case captures, font replay,
rejected variants and timing remain available there. In particular,
`final-transitions.json` and `final-library-transitions.json` include every new
wrong assignment; `final-results-paired-results.json` and
`final-library-paired-results.json` include intervals for every reported metric.

For reproduction, run `run.py` with a fresh phase name and the desired snapshot's
`src` on `PYTHONPATH`, followed by corpus arguments `a b c d e f`. Use
`AUDIT_LIBRARY=bench/out/audit-2026-11-02/libraries` for separate C/D library runs.
Existing phase reports are refused. Each source has its own prediction cache.

The source implementation ends at `2d1f61b860906a858a47c48ee677c52fd61bb472`.
Local implementation commits since the starting `f968e86` are:

```text
8a542d2 Read glyphs with different curve decompositions
615c125 Keep pin labels with their owners
2d1f61b Recover connector names and short net labels
```

The reporting commit changes documentation only. Its exact final HEAD and status
are recorded in `bench/out/recognition-2026-11-03/commits.json`. Final status is:

```text
?? schem2net_build_plan.pdf
```

Nothing was pushed or published, and history was not rewritten. Safety stash
`3c4c65e32bb1224cc4411da57667e3ca72d420de` remains intact. The original user PDF
is unchanged, with SHA-256
`c4438b0e190d9844a7a3e2deb3615497763896674e83dd39161b6a37d484c87d`.

