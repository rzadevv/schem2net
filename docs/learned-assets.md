# Bundled assets: provenance and distribution review

Status at candidate `5d2417c`: **redistribution clearance is unresolved**. Keep the
assets intact for reproducibility; the release assessment does not authorize
publishing them. This is an evidence inventory, not a finding of infringement or
a determination that trained parameters inherit any particular source license.

The wheel contains five learned assets and the project's Apache-2.0 `LICENSE`.
Its metadata declares Apache-2.0. It contains no separate asset provenance,
third-party attribution, font permission, or asset-specific clearance record.
The sdist includes the benchmark source manifests and training code, but those
do not establish a complete binary-to-training-input rights chain.

## What can be established

All five assets are byte-identical in the initial audit baseline, recent baseline
and frozen candidate. Full SHA-256 values are in
[the freeze manifest](release-2026-11-05-freeze.json). The following records the
last Git change to each binary, not a reconstructed training run:

| Asset | Last change | Documented training inputs / implementation |
|---|---|---|
| `roles.npz` | `d4e0b64f202017cf0ef0f7fe04a9832a0f728458` | Color/shape rows from development A/B/C/E/F; `bench.learn.KINDS`, `bench.roles` |
| `designators.npz` | `d4e0b64f202017cf0ef0f7fe04a9832a0f728458` | Text/designator rows with development truth from A–E; `bench.designators` |
| `groups.npz` | `d326efe5c02744abaa9e9de165d8acdb02efc436` | Development Eagle C/D and EasyEDA E sources; `bench.groups`, filtered by `from_source` |
| `eagle_font.json` | `d4e0b64f202017cf0ef0f7fe04a9832a0f728458` | Stroke glyph measurements paired to development C Eagle source text; `bench.font` |
| `eagle_fills.json` | `d4e0b64f202017cf0ef0f7fe04a9832a0f728458` | Filled-outline glyph measurements from the same source class |

These descriptions agree with `docs/benchmark.md` and the training implementation.
They do not prove exactly which input rows produced the checked-in bytes. No new
training was performed in the release evaluation. None of the new panel inputs
are supplied to the predictor as training data or component libraries.

The stored source manifests identify repositories, revisions and declared
licenses, including CC BY-SA, MIT, Apache, CERN-OHL and unspecified terms. A
repository-level license label can differ from the hardware file's actual terms.
For example, corpus D labels AgonLight2-HvIO at
`42d4c541f873b38df1ba1f53b2cf5026bc1f1484` as GPL-3.0, while its pinned
[README](https://github.com/OLIMEX/AgonLight2-HvIO/blob/42d4c541f873b38df1ba1f53b2cf5026bc1f1484/README.md)
assigns CERN-OHL version 2 Strongly Reciprocal to hardware and GPL3 to software.
That discrepancy is retained as an audit finding; old manifests and benchmark
results have not been rewritten. It does not establish that this particular
board contributed to a particular learned binary.

Glyph tables need separate review of the measured EDA font shapes as well as
the schematic source licenses. Source-design licensing alone does not document
the rights status of every font. The repository has no recorded permission or
review resolving that question.

## External library indexes

The secondary experiment uses the existing KiCad and SparkFun indexes, with
hashes in the freeze manifest. They are local evaluation inputs and are **not**
inside the frozen schem2net wheel. The documented upstream revisions are
`kicad-symbols` `e1bb0a65` and `SparkFun-Eagle-Libraries` `2354dae`.

The pinned [SparkFun library README](https://github.com/sparkfun/SparkFun-Eagle-Libraries/blob/2354dae/readme.md)
identifies CC BY-SA 4.0. The [official KiCad library license](https://www.kicad.org/libraries/license/)
includes an exception for electronic designs and their generated files, but
explicitly distinguishes redistribution of library collections and requires
their license and attribution information to remain. This review does not assume
that a compressed index qualifies for the design exception. Preserve upstream
notices and review collection redistribution before shipping those indexes.

The [CC BY-SA 4.0 summary](https://creativecommons.org/licenses/by-sa/4.0/)
describes attribution and ShareAlike conditions; its application to a particular
tree or glyph artifact remains a separate question. Apache package metadata is
not evidence that these questions have been answered.

## Evidence needed to clear distribution

Before a public release, establish each binary's exact training/source revision
inventory, applicable file and font terms, required credit and modification
notices, and a documented rights decision for the intended artifact distribution.
Resolve incorrect or unspecified source-license labels in that inventory.
Record the training code/environment and source hashes needed to reproduce a
cleared asset. Include the resulting required notices in both wheel and sdist,
then inspect the built distributions again.

If clearance requires replacing or retraining assets, that creates a new
candidate. Its independent accuracy claim needs a fresh panel under the frozen
evaluation protocol. No asset has been removed, relicensed, or declared to be a
derivative work by this audit.

## Repository publication scope

The repository cleanup was checked against the fetched public `origin/main` at
`19d02f61211f89bb79357bdd2fb316cefce89550`. All five asset files have identical
bytes there and locally; no pending commit changes them. The source/documentation
push therefore adds no learned-asset content. This is not clearance of the
existing public assets or permission to distribute a new model or package.

The tag-triggered PyPI workflow has been removed. CI builds and tests packages
locally on its runners but does not publish distributions. Before restoring
package publication or changing an asset, complete the per-artifact source/font
review and notices described above. Replacing assets, if needed, must be an
explicit, separately validated change rather than a silent cleanup.
