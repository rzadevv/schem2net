# Independent evaluation across generators: protocol draft

Status: final draft, not registered. It is frozen by committing it, unchanged, together with
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
- Discovery follows "Discovery" below, and never runs the extractor.
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

Before reading, one commit holds this protocol, the manifest, the discovery log, the
seal `verified_<name>.json` and the freeze record `docs/evaluation-freeze.json`.

The seal holds the corpus whole: its settings (tier, shares, the checker's
thresholds), every design of the manifest with its manifest entry (repository,
commit, paths, licence, group, rendering), its group, its input hashes and its
eligibility decision. `verify-corpus` fails on any difference until resealed;
`evaluate` refuses a corpus that differs from its seal, a file whose hash changed,
and readings taken under another seal. Resealing an independent corpus after its
first reading voids it.

The freeze record names three wheels, each built from its commit by
`make eval-image` (`SOURCE_DATE_EPOCH` at the commit's time, so a rebuild is
byte-identical):

- the candidate extractor, `56caa06`;
- the comparator, the November 5 frozen extractor `5d2417c`, whose rebuilt wheel
  holds the same files as the one read on November 5;
- the runner: `evaluate` and its scorer, `schem2net.bench.score`, at the commit that
  carries this protocol. Both extractors are read and scored by it; no definition
  changes after the seal.

and the environment both are read in: the image, its base image digest, the locked
requirements with hashes (the runner's, which must equal the candidate's and the
comparator's: the build fails otherwise), the five learned files' hashes, the
library indexes' hashes, and resource limits.

## Environment

`docker/Dockerfile.eval`: Debian 13 `python:3.13.15-slim` pinned by digest, the
locked core dependencies installed with `--require-hashes` into three virtual
environments (`/opt/runner`, `/opt/candidate`, `/opt/comparator`), and no fonts and
no fontconfig. A PDF that does not embed a font is drawn with PDFium's own built-in
stand-ins, so text boxes do not depend on the fonts a machine happens to have: with
the host's fonts mounted, one EasyEDA design of corpus E reads 391 right pins
instead of 394. `run.json` records the reading interpreter's Python, platform,
dependency versions, PDFium version and font inventory, and `evaluate` refuses to
continue a reading on any other.

```sh
make eval-image   # prints the wheel, requirements and image hashes
run() { docker run --rm --network=none --read-only --tmpfs /tmp --cpus 2 --memory 8g \
          --user "$(id -u):$(id -g)" -e SCHEM2NET_HOLDOUT=1 \
          -v "$PWD/bench:/work/bench:ro" -v "$PWD/OUT:/out" "$IMAGE" "$@"; }
run /opt/runner/bin/schem2net evaluate NAME /out/candidate --python /opt/candidate/bin/python
run /opt/runner/bin/schem2net evaluate NAME /out/comparator --python /opt/comparator/bin/python
run /opt/runner/bin/schem2net bench-compare /out/comparator/report.json /out/candidate/report.json
```

The library reading mounts the frozen indexes read-only and adds `--library`.
After the reading, the image is kept with `docker save` and its archive hashed.

## Reading and scoring

- Each extractor is read once, in the image above, with the shipped models, drawing
  only, no library; 2 designs at once, 4 GiB of address space and 1800 s per design.
  A second, separately reported reading uses the frozen library indexes.
- Readings are written once, each with the hash of the PDF it read. A design that
  fails (an error, a memory or time limit, a crash) is recorded as failed and scores
  no pins; a page that fails leaves its pins missing. Failures stay in every figure,
  for both extractors alike, and are listed. A run that is interrupted before a
  design is recorded reads that design when resumed; a recorded reading or failure
  is final. Nothing is re-read, cropped or repaired, and reports are rebuilt from
  saved readings only.
- Primary scoring is strict: every pin of the truth counts, those of parts the source
  does not print and of repeated-channel instances included. Secondary, beside it and
  never in its place: the same figures over observable pins (`observable`), and the
  pins those parts hold, per design.
- All verified designs count in the primary result, revision-only ones (PDFs whose
  text cannot be read) included. Results are also given by evidence level (export,
  carried netlist, text, revision only) and by generator. Renderings are a separate
  study and never count as designs or groups.
- Report: pin accuracy (primary), correct, missed, wrong and extra pins, silent wrong
  pins, exact nets, connection precision, recall and F1, false merges and splits
  (silent ones apart), flag recall and precision, review items per 100 pins and their
  precision, component precision and recall, seconds and peak memory, pages and
  designs failed.

## Statistics

- Unit of resampling: the source group. 2,000 bootstrap draws of groups with
  replacement, seed 0, each design counted as often as its group is drawn; candidate
  and comparator use the same draws, so every interval is of the paired change.
  Intervals are 95% percentile intervals.
- Prespecified outcomes on the pooled panel (`bench-compare` prints them as
  `protocol:` lines), tested in this order, each only if the one before is shown:
  1. silent errors no worse: the upper bound of the change in `silent_error_rate`
     (wrong pins nothing flags, over all pins) is at most +0.001;
  2. pin accuracy no worse: the lower bound of the pin-accuracy change is above −0.002;
  3. pin accuracy higher: the lower bound is above 0.
  An interval that shows none of these says "not shown": it is not evidence that the
  two extractors are alike, and is reported as inconclusive.
- Everything else (secondary metrics, observable pins, evidence levels, generators,
  the library reading) is descriptive: point estimates with intervals, no tests, no
  adjustment for multiplicity, and no claim.
- A generator gets a statement of its own only with at least 8 groups and 1,000
  scored pins, and then only as a descriptive interval; with fewer, its figures are
  listed as too few to judge. With 8 to 12 groups an interval is wide and unstable;
  per-generator figures are never ranked or compared with each other.

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

## Discovery

The panel is drawn up from public sources by a fixed procedure, before any reading.

1. Exclusions (`verify.ledger` and `verify-corpus`): every repository of a corpus
   manifest (A to G, P, X) or of the November 5 panel, every owner of one, every
   fork whose parent is one, and every design sharing nine tenths of its true nets
   with any built design, the November 5 pairs included (`--against`). Ports and
   copies under another owner that the net check cannot see (a re-drawn board) are
   named in the discovery log and excluded by hand.
2. Search: for each generator, the queries and the date they were run are written in
   the discovery log before results are looked at (GitHub code and repository search
   for the generator's source file types beside a PDF). Results are taken in the
   order returned.
3. Each repository looked at is logged in `bench/discovery_<name>.json` with its URL,
   commit, generator, decision and reason, admitted or not: fork, used owner, no PDF,
   PDF older than its source, licence not determined, more than two circuits taken
   from it, more than three from its group.
4. A candidate is pinned to a commit; its paths, licence (SPDX, or `none`) and
   generator are written to the manifest; it is built and `verify-corpus` decides.
   Quarantined designs stay listed with their reasons.
5. Discovery for a generator stops when it has 12 admitted candidates (15 for Altium
   and OrCAD, whose pairs fail more often), or when its queries are exhausted. A
   generator short of 8 groups is reported short; eligibility is never loosened to
   fill it.

## Before collection

- Rebuild the image from the commit that merges this protocol and write its hashes
  to the freeze record, then commit the record before the first search.
- Supply per generator is unknown until discovery: at the pilot's yield about 12
  candidates give 8 groups.
