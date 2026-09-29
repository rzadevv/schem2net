# Benchmark

## Corpora

| Corpus | Source | Ground truth |
|---|---|---|
| A | Open KiCad projects rendered with `kicad-cli` (KiCad 10) | Netlist exported by `kicad-cli` |
| B | Vendor PDFs (Altium, OrCAD) | Design sources where published, hand labels otherwise |

Manifests (`bench/corpus_*.toml`) store references only: a repository URL and
commit, or a demo that ships with KiCad. PDFs are rendered without property
popups and hierarchy links, so the extractor sees only the drawing.

Corpus B is not built yet.

## Splits

Each project is assigned to `dev` or `test` by a hash of its name, so the
split cannot drift. Tune on `dev`. Report `test`.

```sh
schem2net bench a --split dev
schem2net bench a --split test --json results.json
```

## Metrics

Nets are sets of `(refdes, pin)` pairs. Predicted nets are matched one-to-one
to true nets by maximising Jaccard overlap (Hungarian algorithm). Nets with a
single pin in the ground truth are not scored.

| Metric | Meaning |
|---|---|
| `pin_accuracy` | Share of pins placed in the matched net. Primary metric. |
| `signal_pin_accuracy` | The same, excluding power and ground nets. |
| `net_exact` | Share of true nets reproduced exactly. |
| `connection_precision`, `connection_recall`, `connection_f1` | Over pairs of pins that share a net, excluding power nets. |
| `component_precision`, `component_recall` | By reference designator. |
| `value_accuracy` | Component values, ignoring case and spaces. |
| `flag_recall` | Share of wrong nets that were flagged low-confidence (below 0.8). |
| `flag_precision` | Share of flagged nets that were actually wrong. |
| `perfect_designs` | Share of designs with every net correct. |

Corpus totals are summed over pins, not averaged over designs.

Swapping the two pins of a resistor, non-polarised capacitor, inductor,
ferrite bead, fuse or crystal is not counted as an error. Polarised parts
are not treated this way.

Power nets are recognised by name: names starting with `+` or `-`, voltages
such as `3V3`, `VCC`, `VDD`, `VSS`, `VBUS` and anything containing `GND`.

## Known gaps in the ground truth

Some connections exist in the design but are not visible in the PDF:

- Hidden power pins that connect to a net by name.
- Label scope set in project settings. For example, Altium's net identifier
  scope decides whether same-named labels on different sheets connect.
- Parts that are not fitted in a variant.

These are not handled yet.
