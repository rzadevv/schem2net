# Independent evaluation across generators: protocol draft

Status: draft, not registered. It is frozen by committing it, unchanged, together with
the panel manifest and before any design of the panel is read by the extractor. It
follows the [November 5 protocol](release-2026-11-05-protocol.md) and does not
change that evaluation or its results.

## Question

How well does a frozen extractor read schematics it was never tuned on, for each of
KiCad, Eagle, Altium, EasyEDA and OrCAD? Consistency across renderings of one design
is a separate question, answered apart and never counted as more designs.

## Panel

- Target: 60 designs in at least 40 source groups, at least 8 groups for each
  generator. A generator short of 8 groups is reported as short, not padded with
  weaker pairs, and has no claim of its own.
- A corpus manifest `bench/corpus_<name>.toml` with `tier = "independent"` and
  `holdout_share = 1.0`. It stores references only: repository, commit, paths,
  licence.
- Licence, as recorded in the manifest: an SPDX identifier; `none` where the source
  states or shows no grant (default copyright); never left absent, `NOASSERTION` or
  `unknown`. An undetermined licence keeps a design out until it is resolved. `none`
  and non-commercial designs are scored locally and named in the report. Neither a
  missing licence nor `none` permits redistribution, and no panel file is
  redistributed by this repository in any case.
- Eligibility comes before any reading and never depends on how well schem2net could
  read a design: `verify-corpus` (docs/benchmark.md, "Verifying a corpus") keeps a
  design out only for a mismatch between PDF, source and truth, for provenance (used
  repository, owner or fork parent; nine tenths of nets shared with any built
  design; licence not determined; fork status unchecked), or for scope (not built, unreadable
  file, an image rather than a vector drawing). Outlined or stroked text, unusual
  fonts and colours are no reason: such a PDF rests on its revision, and results are
  reported by evidence. Every exclusion is listed with its kind and never replaced by
  a looser pair after the seal.
- The copy check reads the truth netlists of every built corpus, holdouts included,
  and nothing else of them: no PDF, prediction or score.
- Discovery logs every repository looked at and why it was turned away
  (`bench/discovery_<name>.json`), and never runs the extractor.
- Groups: one per repository owner; known families and ports merge. At most two
  circuits per repository and three per group. Different PDFs of one circuit are one
  design; a revision sharing nine tenths of its nets is the same group.
- Truth is never edited to agree with a drawing or the extractor. Three cases:
  - Parts the source does not print (hidden designators, as mounting holes): kept in
    the truth and scored like any part.
  - A repeated channel drawn once (an Altium "logical" print shows `U3` for `1U3`,
    `2U3`): kept, every instance in the truth; the design is admitted and named in
    the report.
  - Board-derived truth (OrCAD, some Altium): admitted only with printed-text
    agreement both ways, as any published PDF. Where the PDF carries the schematic's
    netlist, that is the truth and the board only a cross-check. A drawing that
    shows parts the truth lacks (front-panel parts off the board) is a mismatch.

## Freeze

Before reading, one commit holds this protocol, the manifest, the discovery log and
the seal, `verified_<name>.json`. The seal holds the corpus whole: its settings (tier,
shares, the checker's thresholds), every design of the manifest with its manifest
entry (repository, commit, paths, licence, group, rendering), its group, its input
hashes and its eligibility decision. `verify-corpus` fails on any difference until
resealed, and `evaluate` refuses a corpus that differs from its seal (a design added,
removed or regrouped, a source moved, a setting changed) or a file whose hash
changed. Resealing an independent corpus after its first reading voids it. The
freeze commit names:

- the candidate commit, installed as a wheel built from it with `uv.lock`;
- the hashes of the five learned files (`evaluate` records them in `run.json` and
  refuses a second reading with other code, models or library);
- the comparator: the November 5 frozen extractor `5d2417c`, read the same way;
- the scorer: `schem2net.bench.score` at the candidate commit, unchanged; no
  definition may change after the seal.

## Reading and scoring

- `schem2net evaluate <name> OUT` with `SCHEM2NET_HOLDOUT=1`, once per extractor:
  shipped models, drawing only, no library, 4 GiB, 1800 s per design; a second,
  separately reported reading with the frozen library indexes.
- Predictions are written once. A design or page that fails stays failed: it scores
  no pins and is listed. Nothing is re-read, cropped or repaired.
- Primary scoring is strict: every pin of the truth counts, those of parts the source
  does not print and of repeated-channel instances included. Secondary, reported
  beside it and never in its place: the same figures over observable pins, without
  those parts (`observable`), and the number of pins they hold.
- Report, by generator and pooled: pin accuracy, correct, missed and wrong pins,
  silent wrong pins, exact nets, connection precision, recall and F1, false merges
  and splits (silent ones apart), flag recall and precision, review items per 100
  pins and their precision, component precision (designators not in the truth),
  extra pins, seconds and peak memory, pages and designs failed.
- Uncertainty: 95% intervals from 2,000 bootstrap draws over groups, candidate
  against comparator paired on the same draws (`bench-compare`), on the pooled
  panel. Prespecified criteria for the candidate against the comparator:
  - better: the interval of the pin-accuracy change lies above 0;
  - pin accuracy no worse: its lower bound is above −0.002;
  - silent errors no worse: the upper bound of the interval of the change in
    `silent_error_rate` (wrong pins nothing flags, over all pins) is at most +0.001,
    an absolute 0.1 percentage point.
  The primary claim is pooled. Per-generator figures are descriptive, given with
  their intervals; a generator is claimed better or no worse on its own only with
  at least 8 groups and 1,000 scored pins, and never from fewer.
- Renderings (colour and black and white, KiCad 7, 8 and 10, a published PDF) are
  read as a separate study: the spread of pin accuracy across one design's renderings.

## After the reading

Results are committed whatever they show. No change made because of a panel design
may claim an independent result on that panel; a revised candidate needs a new
panel. The panel's PDFs, sources and truths are never redistributed by this
repository; NC or unlicensed designs are scored locally and named as such.

## Lessons of the pilot (corpus P)

The exploratory pilot (bench/corpus_p.toml, 20 designs from 20 new owners, 11
renderings) admitted 18 designs and 9 renderings. Kept out: a raster PDF and an
Altium board KiCad could not import (scope), and the KiCad 7 and 8 renderings of a
KiCad 10-era design, whose own netlists differ from the design's (mismatch). In
corpus X an Altium PDF's carried netlist lacks the panel parts its drawing shows.

A first version of the checker also turned away three hard but valid designs: two
EasyEDA PDFs whose sources hide some designators, and an OrCAD print that runs each
designator into its value. Admitted, they lowered the pilot's pooled pin accuracy
from 0.847 to 0.783: excluding what is hard to read flatters the result.

Published KiCad PDFs that outline their text are admitted on their revision; the
extractor reads nothing from them. Licensed Altium and OrCAD pairs were scarce.

## Decisions before registering

- Supply per generator, from discovery alone: at the pilot's yield, about 12
  candidates for 8 groups, 15 or more for Altium and OrCAD.
- Whether revision-only designs count in the headline figure or only in their
  stratum (recommended: in the headline, with the stratum reported).
- The machine and session the candidate and comparator are read in, recorded.
