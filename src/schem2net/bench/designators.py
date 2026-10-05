"""Learn which texts are designators, from the dev designs of each corpus.

Each design is read as usual up to the point where designators are given out; there
the features of every text are taken, and the truth netlist says which texts name
parts. The truth is used for nothing else. Gradient-boosted trees are fitted for
each generator and written out as node arrays for `designators.Forest`.
"""

from collections import Counter
from pathlib import Path

import numpy as np

from schem2net import designators, fields, kicad, pipeline
from schem2net.bench.roles import _fit

Example = tuple[str, np.ndarray, np.ndarray]  # generator, features, labels (-1: unknown)


def rows(design: Path) -> list[Example]:
    """The features and labels of the texts on each page of a design read from its PDF."""
    refs = {c.ref for c in kicad.read_netlist(design / "truth.net").components}
    out: list[tuple] = []
    annotate = fields.annotate

    def capture(symbols, scene, profile, runs):
        if scene.fields:
            x = designators.features(scene, symbols, runs, profile)
            y = np.array([designators.label(t, refs) for t in scene.fields], dtype=int)
            out.append((profile.name, x, y, [t.text.strip() for t in scene.fields]))
        return annotate(symbols, scene, profile, runs)

    fields.annotate = capture
    try:
        pipeline.run(design / "schematic.pdf", embedded=False)
    finally:
        fields.annotate = annotate
    # A designator is written once. A string that names a part and is written more
    # often, such as C1 also naming a transistor's pin, leaves its texts unlabelled.
    counts = Counter(w for _, _, _, words in out for w in words)
    return [
        (g, x, np.where((y == 1) & np.array([counts[w] > 1 for w in words], bool), -1, y))
        for g, x, y, words in out
    ]


def train(examples: list[Example]) -> dict[str, np.ndarray]:
    """For each generator, the model of designators, as arrays named "<generator>.<field>"."""
    arrays = {}
    for generator in sorted({g for g, _, _ in examples}):
        mine = [(x[y >= 0], y[y >= 0]) for g, x, y in examples if g == generator]
        mine = [(x, y) for x, y in mine if len(y)]
        if not mine:
            continue
        for name, value in _fit(mine).items():
            arrays[f"{generator}.{name}"] = value
    return arrays


def save(arrays: dict[str, np.ndarray], path: Path) -> None:
    np.savez_compressed(path, **arrays)
