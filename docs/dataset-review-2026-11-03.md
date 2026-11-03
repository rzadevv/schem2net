# Dataset review — 2026-11-03

This review is separate from extraction improvements. No PDF, truth, manifest,
split or baseline was changed. OpenLog remains in every comparison with its
existing errors; the [previous correction proposal](openlog-provenance-2026-11-02.md)
remains a proposal.

Four development cases were checked against their cached, pinned Eagle sources.
The checks establish the meaning of the components investigated here, rather than
certifying every connection or revision in those designs.

- [LCD 7TS revision A](https://github.com/OLIMEX/OLINUXINO/blob/a8672538a650d3a1eb23c11fe9ef594229333232/HARDWARE/LCDs/LCD-OLinuXino-7TS/Hardware%20revision%20A/LCD-OLINUXINO-7TS_Rev_A.sch):
  LCD_CON, LCD_LIME and LCD_LIME2 are three ML40 parts with different packages.
  Their instances share location `(220.98, 134.62)` and rotation R180. Their NAME
  attributes occupy three separate rows, matching the PDF. These are distinct
  alternative connectors sharing connections, rather than three units of one
  reference. Copying electrical pins to their separately printed names is supported.
- [LCD 4.3TS revision A](https://github.com/OLIMEX/OLINUXINO/blob/a8672538a650d3a1eb23c11fe9ef594229333232/HARDWARE/LCDs/LCD-OLinuXino-4.3TS/Hardware%20revision%20A/LCD-OLINUXINO-4.3TS_Rev_A.sch):
  the source likewise contains LCD_CON, LCD_LIME and LCD_LIME2 as separate ML40
  parts. The same recovery applies; fewer scored terminals are connected.
- [A20 SOM EVB revision C](https://github.com/OLIMEX/SOM/blob/6a2798c6f8c015fb360993eb86d6c965d028b0c1/A20/A20-SOM-EVB/A20-SOM-EVB_Rev_C.sch):
  A20-SOM-EVB_PLATFORM is one part, one gate, using the six-connector device.
  The PDF's six sections belong to that single reference. Treating their internal
  pad labels as separate references is an extraction error.
- [nRF52840 MDBT50Q](https://github.com/sparkfun/nRF52840_Breakout_MDBT50Q/blob/6c5adaa14dac9ce4c3fc99354011cb9172e05439/Hardware/nrf52840-breakout-mdbt50q.sch):
  U1 is the MDBT50Q module. The problematic printed numbers have a geometric
  decoding failure: the font matcher excludes the candidate 8 by segment count.
  That evidence does not establish another PDF/source mismatch.

No additional mismatch was established in these component checks. No separately
versioned dataset correction is proposed from them. All measured gains in this
phase use the original dataset; dataset-only before/after effects are zero.

Exact source and PDF SHA-256 values, instance attributes and part definitions are
saved in ignored `bench/out/units-2026-11-03/dataset-review.json`, alongside the
source excerpts. The development-input hashes were checked against the preceding
phase for all 198 designs. Protected test and holdout designs were not evaluated.
