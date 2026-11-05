# Architecture

The input is a vector drawing, not a raster image. PDF paths, text objects,
colours and drawing order provide evidence about symbols and connectivity.
`pipeline.extract` returns a `Design`; `pipeline.run` also retains per-page scenes.

## Data flow

| Stage | Responsibility | Modules |
|---|---|---|
| Read | Walk PDF objects and nested forms; transform paths and text into millimetres. | `pdf`, `primitives` |
| Identify | Detect EDA conventions from metadata or colour; distinguish schematics from other pages. | `ingest`, `profile` |
| Normalize | Recover print scale, join split text and lines, read vector glyphs, infer roles in black/custom themes. | `grid`, `strokes`, `fills`, `roles` |
| Build scenes | Separate wires, junctions, symbol graphics, labels, sheet boxes and fields. | `scene` |
| Reconstruct parts | Find physical pin ends, group body graphics, assign references, values and numbers. | `symbols`, `fields`, `designators` |
| Resolve identities | Reconcile units and optionally match indexed library pins. | `fields`, `library` |
| Connect | Join wire endpoints, contacts, labels, buses and hierarchical ports; retain evidence and issues. | `nets`, `buses` |
| Output | Save the IR, export netlists/projects, draw reports or answer queries. | `ir`, `export`, `kicad_sch`, `report`, `query`, `mcp_server` |

An Altium Smart PDF may carry its own netlist in bookmarks. `bookmarks.read`
provides that direct path; drawing-only evaluation explicitly disables it.
Otherwise the drawing goes through the stages above. Pages that fail are retained
as issues, while other pages continue. The broad exception boundary in
`pipeline._extract` is deliberate page isolation, not silent success.

## Geometry and drawing conventions

Coordinates use millimetres from the displayed page's top-left. PDF rotation and
nested affine transforms are resolved before connectivity work. Bézier paths are
sampled; line widths, fill colours, object order and native text bounds remain
available. Resource guards are described in [usage](usage.md#failures-and-resource-limits).

`geometry.GridIndex` restricts nearby-object searches to occupied grid cells.
Distance-to-segment, polygon, bounding-box and orientation helpers support later
stages. Wire geometry is not interchangeable with symbol geometry: a capacitor
plate, section border or diode lead can look like a wire but has a different role.

`profile` loads declarative conventions for KiCad, Altium, Eagle, EasyEDA and
OrCAD. Profiles describe colours, order, label scope, scaling and pin placement;
unknown keys fail validation. Export/print styles may lose colour or generator
metadata, so `roles` uses learned path/text features to infer those roles. Unknown
profiles are tried as alternatives and the selected guess is reported. This is a
heuristic choice, not an accuracy certificate.

## Text and identity recovery

Native PDF text is preferred. Eagle exports may encode letters as strokes or
filled outlines; `strokes` and `fills` group those primitives into glyphs and match
normalized shapes against bundled tables. Stroke matching reuses prepared query
shapes and compiled pairwise-distance operations. It does not add raster OCR.

A symbol's pin joins its body at one end and the electrical network at the other.
Touching free ends must not merge two component bodies. Dashed outlines, floating
body pieces, stacked alternatives and pins continued into wires require separate
handling. Generator drawing order helps where distance alone is ambiguous.

`fields` assigns references and values using geometry, order and learned
designator likelihoods, then numbers terminals from nearby text, repeated rows or
limited shape/position rules. Printed numbers take precedence over inferred
names. Functional names such as G/S/D can identify a terminal without establishing
a package pad; unresolved numbers stay `?N`. Guessed numbers produce review issues.

Some functions in `fields`, `symbols` and `nets` remain long because they implement
ordered decisions with shared geometry and evidence. Reordering fallbacks or
splitting that state across helpers can change behaviour. Their regression tests
and frozen comparisons are more useful than a purely structural rewrite.

## Connectivity and confidence

`nets.Netlister` records joins in a union-find graph. Nodes include wire points,
component pins, local/global names and sheet ports. Join edges retain evidence
kinds, so final nets can report why terminals were connected.

Shared endpoints, T contacts and explicit junction dots connect; a plain interior
crossing does not. Local labels are scoped to their sheet. Global and power names
connect according to the generator profile. Hierarchical ports match parent and
child paths. Vector buses map by member position across sheets; group buses map
by member name. Bus labels must not attach to nearby scalar wires merely because
the text lies close to them.

Confidence is derived from the weakest joining evidence and consistency checks.
It is **not a calibrated probability**. Conflicting power names, duplicated pins,
missing numbers and unconnected pins are separate issues; a high-confidence net
may still contain a wrong reference or pad. Keep pin-level issues when reviewing
or transforming the IR.

## Libraries and learned data

Library indexes are optional inputs, not implicit system dependencies. KiCad
fits compare visible pin positions, known numbers/names, unit and orientation;
stacked pins may be recovered where those constraints agree. Eagle indexes supply
pin names without guessing package-specific numbers. An ambiguous fit is left
unresolved. The IR records the index fingerprint.

Runtime inference uses NumPy arrays and flattened decision trees, plus measured
glyph tables; it does not import scikit-learn. Model generation is in
`schem2net.bench`, which selects development groups and supports out-of-fold
models. `profile.use_learned(None)` selects the shipped assets; caches are keyed by
asset path. The [asset inventory](learned-assets.md) records the unresolved
training-source and distribution questions.

## Interfaces and evaluation

`ir.Design` holds source metadata, components, pins, nets, evidence and issues.
`PinRef` is `(reference, physical_pad_number)`. JSON writes are atomic. Exporters
consume the IR rather than running a separate electrical reconstruction. HTML
reports combine saved geometry with escaped text; MCP delegates to the same
read-only `Query` operations.

The KiCad, Eagle and EasyEDA CAD readers support benchmark truth construction;
they are not extra PDF extraction engines. `bench.score` aligns predicted and
true nets one-to-one with a Hungarian assignment on Jaccard overlap. Its pin-name
aliases and allowed passive-end swaps are scoring conventions, not corrections
to the raw prediction. Power-net exclusions from pair F1, singleton handling and
review metrics are defined in [benchmark methodology](benchmark.md#metrics).

The [independent evaluation](release-2026-11-05.md) is frozen at `5d2417c`.
Repository presentation and CI changes do not alter that extractor. Future
functional changes need development regression checks and a fresh independent
panel for a new independent-release claim.
