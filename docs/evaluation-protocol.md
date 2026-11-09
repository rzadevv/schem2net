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
- Eligibility comes before any reading: `verify-corpus` admits a design only with
  export, carried-netlist or text evidence (docs/benchmark.md, "Verifying a corpus").
  Revision-only evidence, an unchecked fork, a missing licence, a used repository,
  owner or fork parent, or nine tenths of nets shared with any built design keeps it
  out. Quarantined designs are listed with their reasons and never replaced by
  looser ones after the seal.
- The copy check reads the truth netlists of every built corpus, holdouts included,
  and nothing else of them: no PDF, prediction or score.
- Discovery logs every repository looked at and why it was turned away
  (`bench/discovery_<name>.json`), and never runs the extractor.
- Groups: one per repository owner; known families and ports merge. At most two
  circuits per repository and three per group. Different PDFs of one circuit are one
  design; a revision sharing nine tenths of its nets is the same group.
- Board-derived truth (OrCAD, some Altium) needs printed-text agreement; where the
  PDF carries the schematic's netlist, that netlist is the truth and the board only
  a cross-check.

## Freeze

Before reading, one commit holds this protocol, the manifest, `verified_<name>.json`
(file hashes and evidence) and the discovery log. It names:

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
- Report, by generator and pooled: pin accuracy, correct, missed and wrong pins,
  silent wrong pins, exact nets, connection precision, recall and F1, false merges
  and splits (silent ones apart), flag recall and precision, review items per 100
  pins and their precision, component precision (designators not in the truth),
  extra pins, seconds and peak memory, pages and designs failed.
- Uncertainty: 95% intervals from 2,000 bootstrap draws over groups; candidate
  against comparator paired on the same draws (`bench-compare`). Before reading,
  record the margins that count as better (interval of the pin-accuracy change above
  0) and as no worse (above −0.002, silent errors not higher), per generator.
- Renderings (colour and black and white, KiCad 7, 8 and 10, a published PDF) are
  read as a separate study: the spread of pin accuracy across one design's renderings.

## After the reading

Results are committed whatever they show. No change made because of a panel design
may claim an independent result on that panel; a revised candidate needs a new
panel. The panel's PDFs, sources and truths are never redistributed by this
repository; NC or unlicensed designs are scored locally and named as such.

## Lessons of the pilot (corpus P)

The exploratory pilot (bench/corpus_p.toml, 20 designs from 20 new owners, 11
renderings) admitted 15 designs and 9 renderings. Its verifier kept out:

- a PDF exported seconds before parts were added to the source (EasyEDA);
- a board-derived truth 149 designators away from its PDF (OrCAD), and in corpus X an
  Altium PDF whose carried netlist lacks the panel parts the drawing shows;
- mounting holes connected in the truth whose names the PDF does not print;
- a raster PDF; an Altium board KiCad could not import (out of memory);
- KiCad 7 and 8 renderings of a KiCad 10-era design, whose own netlists differ from
  the design's: an older version reads one of its nets otherwise.

Published KiCad PDFs that outline their text were admitted as renderings on their
revision alone; the extractor reads nothing from them. Licensed Altium and OrCAD
pairs were scarce: 3 of 4 Altium and 1 of 3 OrCAD candidates were admitted.

## Open before registering

- Each generator's eligible pool, measured by discovery alone; at the pilot's yield
  (about 3 of 4 candidates admitted, fewer for OrCAD), 8 groups per generator needs
  roughly 12 candidates each, 15 or more for OrCAD and Altium.
- Whether designs whose truth names unprinted parts (mounting holes) should be
  admitted with those parts left out of scoring, decided before discovery.
- Margins and minimum sample per generator for a claim.
- A rule for repeated channels drawn once (Altium "logical" prints): admitted now,
  the truth holding every channel.
