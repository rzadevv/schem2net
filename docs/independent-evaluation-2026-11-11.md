# Independent evaluation, 11 November 2026

The first and only reading of the independent panel (corpus H), run as
[the protocol](evaluation-protocol.md) and [the freeze record](evaluation-freeze.json)
fix it. Results are reported whatever they show. Nothing here redistributes a panel
design: the figures are counts over the designs' pins, and the designs are named by
reference only in `bench/corpus_h.toml`.

## What was read

- Panel: 59 designs in 59 source groups, drawn up by the registered discovery
  (`bench/discovery_h.json`, searches registered in `9758ca0`), seal
  `b2a0e1e5146316eeea8b7c3b1bfb0f3c108f6d0ab676cea809e320104e52f8e2`. KiCad 12,
  Eagle 12, EasyEDA 12, Altium 15, OrCAD 8.
- Candidate: the extractor at `56caa06`. Comparator: the November 5 extractor at
  `5d2417c`. Both read and scored by the runner at `0b1b691`.
- Environment: image `sha256:701ef31a…` (archive `fb68c8ae…`), Python 3.13.15,
  linux/amd64, PDFium 153.0.7999.0, no fonts; no network, read-only inputs, 2 CPUs,
  8 GB, 2 designs at once, 4 GiB and 1800 s per design, `SCHEM2NET_HOLDOUT=1`.
  The result holds for this image only.
- Primary reading: drawing only, shipped models, no library. A second reading with
  the frozen November 5 library indexes is reported apart.
- Each extractor read each design once, on 2026-11-11 between 12:25 and 12:38 UTC.
  No design and no page failed.

## Primary result

Strict scoring (every pin of the truth), 16,817 pins:

| | Comparator `5d2417c` | Candidate `56caa06` | Change, 95% interval |
|---|---|---|---|
| Pin accuracy | 0.6869 | 0.6890 | +0.0021 [+0.0002, +0.0055] |
| Silent error rate | 0.0150 | 0.0133 | −0.0017 [−0.0041, −0.0001] |
| Correct / missed / wrong / extra pins | 11,551 / 3,866 / 1,400 / 119 | 11,587 / 3,865 / 1,365 / 117 | |
| Silent wrong pins | 252 | 223 | |

Pin accuracy, candidate, with a group-bootstrap interval: 0.689 [0.584, 0.769].

The prespecified outcomes, tested in order (`bench-compare`, 2,000 paired draws over
source groups, seed 0, 95% percentile intervals):

1. Silent errors no worse (upper bound ≤ +0.001): **shown** (upper bound −0.0001).
2. Pin accuracy no worse (lower bound > −0.002): **shown** (lower bound +0.0002).
3. Pin accuracy higher (lower bound > 0): **shown** (lower bound +0.0002).

The candidate changed the counts of 7 of the 59 designs. The improvement is small and
its lower bound barely clears zero: it shows the candidate is not worse and slightly
better on this panel, not that the gain is large.

## Secondary figures (descriptive)

Candidate (comparator):

- Observable pins (parts the source does not print left out, 9 pins): pin accuracy
  0.6894 (0.6872).
- Exact nets 0.556 (0.555). Connections: precision 0.975 (0.971), recall 0.556
  (0.555), F1 0.708 (0.707). False merges 101 (106), 15 (20) silent; false splits
  773 (783), 28 (28) silent.
- Components: precision 0.952, recall 0.848 (both).
- Flags: recall 0.737 (0.737), precision 0.842 (0.843). Review items per 100 pins
  16.3 (16.4), of which 62.9% (62.9%) are right.
- Time: 254 s (256 s) for all 59 designs, median 0.8 s, slowest 62 s. Peak memory:
  median 134 MB, largest 176 MB (177 MB).

By evidence (candidate; pins; pin accuracy with interval):

| Evidence | Designs | Pins | Pin accuracy | Change |
|---|---|---|---|---|
| KiCad export | 12 | 6,480 | 0.779 [0.652, 0.871] | +0.0014 |
| Carried netlist | 12 | 3,539 | 0.653 [0.356, 0.874] | 0 |
| Printed text | 29 | 6,443 | 0.646 [0.536, 0.737] | +0.0042 |
| Revision only | 6 | 355 | too few to judge (0.197) | 0 |

By generator (candidate). A generator is described only with 8 groups and 1,000
pins; the intervals are wide and the generators are not ranked against each other.

| Generator | Groups | Pins | Pin accuracy | Silent error rate |
|---|---|---|---|---|
| Altium | 15 | 5,335 | 0.702 [0.477, 0.857] | 0.004 |
| EasyEDA | 12 | 1,677 | 0.519 [0.363, 0.713] | 0.001 |
| KiCad | 12 | 6,480 | 0.779 [0.652, 0.871] | 0.024 |
| OrCAD | 8 | 2,369 | 0.627 [0.473, 0.812] | 0.011 |
| Eagle | 12 | 956 | too few pins to judge (0.460) | 0.017 |

## Library reading (descriptive)

With the frozen November 5 indexes, pin accuracy is 0.6891 (candidate) and 0.6870
(comparator): +0.0001 against the drawing-only reading for each. Ten designs change;
review items fall by 0.7 per 100 pins and silent errors rise by 0.0002. The paired
change between the extractors is the same as without the library.

## Where the errors are

- Missed pins (3,865) outnumber wrong ones (1,365) almost three to one, and
  connection recall (0.56) lags precision (0.98): the extractor mostly fails to find
  connections rather than inventing them.
- Parts not found: in 14 designs fewer than 70% of the parts are found, accounting
  for 1,429 of the missed pins; one Altium design alone misses 608 of 621.
- PDFs without readable text (revision only): 0.197 pin accuracy over 6 designs,
  three of them none at all.
- Silent wrong pins are concentrated in KiCad exports (KiCad's silent error rate
  0.024), four designs holding 149 of the 223.

## Limitations

- One panel of 59 public designs, mostly hobby and small-team boards, found by
  GitHub code search (files under 384 KB on default branches, at most 1,000 results
  per query). OrCAD's results ran out at 8 groups; Eagle has too few pins for a
  statement of its own.
- Truth comes from each source's own netlist or board, checked against the printed
  PDF; a board can differ from its drawing. Wrong pin numbers remain possible in the
  truth as in the prediction.
- The result holds for the frozen image; another machine or font set is another
  measurement.
- The candidate and comparator differ little; the panel shows the size of the change,
  not a large improvement.
- Any change made because of this panel cannot claim an independent result on it.

## Reproducibility

- Reports: candidate `5286f079…`, comparator `9d94e647…`, candidate with library
  `7051084c…`, comparator with library `c97a980a…`; `bench-compare` output
  `73bf10f4…` (library `27b2b84d…`). All four readings and their run manifests are
  kept locally, read-only, with a checksum list (`SHA256SUMS`, `0f03e457…`) and an
  archive (`47be677f…`) with a separate backup.
- `bench/results_h.json` holds the descriptive figures and every design's counts.
