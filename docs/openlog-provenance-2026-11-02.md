# OpenLog benchmark pairing review

The development design `sparkfun-qwiic_openlog` pairs different hardware products.
This is a benchmark-input problem, separate from extraction improvements. No
manifest, input, ground truth, split or score was changed during this review.

The manifest pins SparkFun's Qwiic OpenLog schematic at commit
`1d8b6e44495efb476bb991847acbf9008f55b063`, path
[`Hardware/Qwiic-OpenLog.sch`](https://github.com/sparkfun/Qwiic_OpenLog/blob/1d8b6e44495efb476bb991847acbf9008f55b063/Hardware/Qwiic-OpenLog.sch).
Its bytes match the cached schematic used to build `truth.net`.
The PDF is SparkFun's older [serial OpenLog schematic](https://cdn.sparkfun.com/datasheets/Dev/Arduino/Boards/OpenLog_v15.pdf),
whose SHA-256 matches the manifest:
`3ea7e98163c5a35b471110a5bf1d7c702e0676f5ea8934da6b1dacd1f1151541`.

| Evidence | PDF | Paired schematic |
|---|---|---|
| Interface | Serial connection for Arduino Pro/Pro Mini | Qwiic/I2C interface |
| Microcontroller | U1, ATmega328P | U2, ATmega328P |
| U2 | MIC5205 regulator | Microcontroller |
| Qwiic connectors | Absent | J2, J3, J4 |
| Configuration | Serial/SPI headers | I2C pull-ups and address jumper |
| C1 | 10 µF | 4.7 µF |

Both drawings contain “V15.” That shared annotation does not establish that they
represent the same product. The regulator, microcontroller references, interfaces
and connectors establish the mismatch independently.

## Impact, without changing the benchmark

At starting commit `5dc079c`, this case scores 21 correct, 58 missing and one wrong
pin out of 80. It contributes **6.87% of Eagle's 844 missing development pins**.
The 59 non-correct pins represent at most **0.99461 percentage points** of the
whole corpus's pin-accuracy deficit. This is an upper bound on the case's total
contribution, not an estimate that all 59 errors were caused by pairing.

As a sensitivity calculation only, dropping this case would raise the starting
Eagle pin accuracy from 83.95145% to 84.74026%. **The case was retained in every
reported extraction comparison.** That hypothetical increase is not an extraction
gain and is not included in the development results.

## Proposed correction for review

Generate a PDF from the exact pinned Qwiic schematic, or identify a published PDF
whose component references, pin mapping and hardware revision match that source.
Verify that pairing before proposing a manifest/hash change. Preserve the old
input and results, and establish a separate benchmark version if a correction is
accepted. Alternatively, pair the serial OpenLog PDF with its own exact schematic
in a separately reviewed dataset change.

There is no proposed automatic exclusion, reference renaming, split movement or
replacement of existing baseline figures. Matching PDFs should be checked for
other candidates before extending conclusions beyond this confirmed case.

Reproducibility evidence, source hashes, per-design counts and the sensitivity
calculation are in ignored
`bench/out/recovery-2026-11-02/openlog-provenance.json`. The source comparison used
the pinned local Git object; the PDF was also checked against SparkFun's published
file. No source repository was modified.
