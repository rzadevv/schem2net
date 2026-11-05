# Development and reproducibility

## Local checks

Python 3.11+ and uv are required. `make install` installs locked development and
optional MCP dependencies. CI tests Python 3.11 and 3.14.

```sh
make install
make test
make lint
make package-check
```

`make package-check` builds both distributions, replaces the editable package in
`.venv` with the wheel, runs the full coverage suite, then exercises installed CLI
exports and MCP with a disposable synthetic PDF. Distribution inspection rejects
untracked local files; the sdist has an explicit project-path allowlist so personal
PDFs and tool settings are not bundled. The target calls `.venv/bin/python`
directly so uv cannot silently restore the editable installation. Run
`make install` afterward to resume editable development.

Tests cover geometry, glyph decoding, wire crossings, symbol/pin reconstruction,
library fits, source readers, scoring and output formats. Synthetic PDF fixtures
make regression geometry explicit. Property tests mutate PDFs and vary drawing
conditions; nightly CI uses 2,000 examples rather than the usual 100. The suite's
coverage floor is 80%, not a claim that all input styles are reliable.

## Repository layout

| Path | Purpose |
|---|---|
| `src/schem2net/` | Runtime pipeline, IR, CLI, exporters and queries. |
| `src/schem2net/profiles/` | Generator conventions and five bundled learned assets. |
| `src/schem2net/bench/` | Corpus construction, truth readers, training and scoring. |
| `tests/` | Unit, property and end-to-end regression tests; synthetic fixtures. |
| `bench/corpus_*.toml` | Pinned external sources and grouping inputs. |
| `bench/baseline_*_dev.json` | Existing CI development regression baselines. |
| `bench/release_*.py` | Frozen-panel acquisition/evaluation and reusable installed-package smoke checks. |
| `bench/release-2026-11-05-*.json` | Independent panel and complete aggregate results. |
| `docker/` | KiCad CLI image used for corpus exports and round trips. |
| `docs/` | Architecture, usage, evaluation, provenance and this guide. |

Downloaded projects, built PDF/truth pairs, fold models and raw experiment output
remain ignored under `bench/cache`, `bench/build` and `bench/out`. Do not commit
those inputs or local virtual environments.

## Development benchmarks

Building KiCad-based corpora requires Docker. Source manifests pin revisions or
file hashes; no third-party design PDF is included in the tracked tree.

```sh
make bench             # KiCad development corpus A
make bench-b           # Altium drawing reconstruction
make bench-c           # Eagle
make bench-d           # Olimex, mixed KiCad/Eagle
make bench-e           # EasyEDA
make bench-f           # OrCAD
make bench-schematic   # exported KiCad project round trips
```

Default benchmark commands use shipped models. Out-of-fold development runs
must explicitly supply fold directories; they are a different configuration.
Library-enabled runs must identify the index fingerprint. Rebuilds can include
new PDF/netlist timestamps, so preserve the exact evaluated bytes and hashes.
See [methodology](benchmark.md) for splits, model training and metrics.

Compare only identical design sets and use the same scorer on saved predictions:

```sh
uv run schem2net bench a --split dev --json candidate-a.json
uv run schem2net bench-compare bench/baseline_a_dev.json candidate-a.json
```

These development gates are regression checks. They are not fresh test accuracy.
The historical test/holdout data was already observed; do not tune on it or rename
it as a new independent test. Keep related source revisions in one group.

## Frozen independent experiment

The [release evaluation](release-2026-11-05.md) identifies the candidate, initial
and recent baselines, 63 verified new designs, source-group intervals, adverse
cases and failed/inconclusive gates. Its [registered protocol](release-2026-11-05-protocol.md),
[environment freeze](release-2026-11-05-freeze.json),
[panel seal](release-2026-11-05-panel.json),
[input manifest](../bench/release-2026-11-05-panel.json) and
[results](../bench/release-2026-11-05-results.json) remain the authoritative records.
The protocol, hashes and machine-readable results have not been rewritten during
repository cleanup. Only historical-report links in the narrative were updated.

Local `bench/out/release-2026-11-05/evidence.tar.gz` preserves the exact PDFs,
truth, all 378 predictions, issues, resource measurements and source-verification
records. It is intentionally not uploaded. A fresh checkout can inspect the
tracked summaries and source references, but cannot reproduce exact input-byte
hashes without that local archive. Re-exporting the pinned sources reproduces the
circuits subject to recorded tool/version and timestamp limitations.

To score the retained predictions without extracting again:

```sh
.venv/bin/python bench/release_eval.py bench/out/release-2026-11-05 summarize
```

Use the original archived environment for exact reproduction. The extraction
runner refuses an existing start marker. Do not overwrite the experiment or tune
on its failures and claim a second independent pass. Frozen records refer to
paths at their recorded source commits; recover those snapshots with `git archive`
or `git show` rather than editing the records to match a newer layout.

## Engineering history

Seven overlapping phase reports have been consolidated here. Their complete
per-corpus tables, confidence intervals, rejected experiments and raw-evidence
recipes remain in the immutable pre-cleanup Git snapshot
[`5cd8f75`](https://github.com/rzadevv/schem2net/tree/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs).
No historical commit, source input, stored baseline or independent result was
rewritten. The following values summarize repeated development measurements,
not unseen-design accuracy.

| Accepted checkpoint | Correct pins | Missing | Wrong | Silent wrong | Exact nets |
|---|---:|---:|---:|---:|---:|
| Crossing/frame fixes, `5dc079c` | 49,031 | 5,475 | 1,347 | 247 | 9,552 |
| Pin continuation/reference ownership, `6111d64` | 49,063 | 5,444 | 1,346 | 245 | 9,570 |
| Connector recovery, `f968e86` | 49,401 | 5,095 | 1,357 | 245 | 9,773 |
| Glyph/field recognition, `1934cda` | 49,667 | 4,853 | 1,333 | 245 | 9,912 |
| Reliability candidate, `5d2417c` | 49,843 | 4,687 | 1,323 | 227 | 9,978 |

Each row covers the same 198 development designs and 55,853 connected truth pins,
with existing grouped fold models and no part library. Connector recovery added
338 correct pins while also adding 11 wrong pins; aggregate gains did not remove
that regression. The final phase lowered review precision from 45.4889% to
44.9295%. Its three-case CPU reduction is development evidence, not an independent
speed estimate across all generators.

The initial audit corrected page guards, library names/units and scorer issue
alignment. Its electrical counts did not improve solely from those accounting
fixes. Historical silent-error figures need the reconciled scorer on both saved
predictions; do not mix the old and corrected confidence accounting. Later work
addressed plain crossings, section frames, continued pins, overlaid connector
references, glyph curve decompositions, field ownership, bus labels and visible
unpopulated parts. No new model training was performed in those improvement
phases.

| Original report | Immutable record |
|---|---|
| Initial correctness audit | [audit](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/audit-2026-11-02.md) |
| Reconciled extraction development | [development](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/development-2026-11-02.md) |
| Component/pin recovery | [recovery](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/recovery-2026-11-02.md) |
| CAD correspondence checks | [dataset review](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/dataset-review-2026-11-03.md) |
| Connector recovery | [connectors](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/connector-recovery-2026-11-03.md) |
| Glyph/field ownership | [recognition](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/recognition-2026-11-04.md) |
| Final development comparison/runtime | [reliability](https://github.com/rzadevv/schem2net/blob/5cd8f75c0b3814f76c22418ae101b4f4754d92e3/docs/reliability-2026-11-05.md) |

The [OpenLog pairing review](openlog-provenance-2026-11-02.md) remains separate
because it establishes a concrete dataset mismatch. That case is retained in the
original benchmarks; no accuracy claim relies on silently correcting or removing
it. CAD correspondence also confirmed that the LCD alternatives are distinct
parts sharing a position, while A20's six connector sections belong to one
reference. Those distinctions remain covered by regression tests and the linked
source checks.

## Distribution boundary

The current source cleanup does not add or change learned-asset bytes relative
to the fetched public `origin/main`. Existing publication is not proof of rights
clearance. [Five asset records](learned-assets.md) remain unresolved; no package
release, retraining or new asset publication is authorized by this cleanup.
Tag-triggered PyPI publication is removed until the required review is complete.
Do not infer that a successful build establishes redistribution permission.
