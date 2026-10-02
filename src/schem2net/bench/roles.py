"""Learn the roles of paths and texts from colour pages, for pages printed in black.

On a colour page the generator's colours say what every path and text is, so the
dev split of each corpus gives labelled examples; no truth netlist is used.
Gradient-boosted trees are fitted to them for each generator (scikit-learn, needed
only here) and written out as plain node arrays, which `roles.Forest` evaluates.
"""

from pathlib import Path

import numpy as np

from schem2net import grid, ingest, pdf, profile, roles

ROUNDS = 150
DEPTH = 6

Example = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]  # paths and texts


def rows(job: tuple[str, Path]) -> list[Example]:
    """Features and colour-given roles of the paths and texts of each colour page."""
    generator, file = job
    rules = profile.load(generator)
    out = []
    try:
        doc = pdf.read(file)
    except (OSError, ValueError):
        return out
    for page in doc.pages:
        if ingest.page_kind(page, text_as_strokes=bool(rules.text_font)) != "vector":
            continue
        if roles.colourless(page):
            continue
        page = grid.rescale(page, 1 / grid.scale(page, rules))
        paths = roles.drawing(page, rules)
        path_roles = [roles.path_role(p, rules) for p in paths]
        if path_roles.count(roles.PATH_ROLES.index("wire")) < 5:
            continue  # wires in no colour the profile knows: not an example
        texts = [t for t in page.texts if t.visible]
        out.append(
            (
                roles.path_features(paths, texts),
                np.array(path_roles),
                roles.text_features(texts, paths, path_roles),
                np.array([roles.text_role(t, rules) for t in texts]),
            )
        )
    return out


def train(examples: dict[str, list[Example]]) -> dict[str, np.ndarray]:
    """For each generator, the models of paths and texts, as arrays named
    "<generator>.<paths|texts>.<field>"."""
    arrays = {}
    for generator, pages in examples.items():
        paths = [(e[0], e[1]) for e in pages]
        texts = [(e[2], e[3]) for e in pages if len(e[3])]
        for kind, data in (("paths", paths), ("texts", texts)):
            if data:
                for name, value in _fit(data).items():
                    arrays[f"{generator}.{kind}.{name}"] = value
    return arrays


def _fit(examples: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, np.ndarray]:
    from sklearn.ensemble import HistGradientBoostingClassifier

    x = np.concatenate([f for f, _ in examples])
    y = np.concatenate([labels for _, labels in examples])
    classes = np.array(sorted({int(c) for c in y}))
    if len(classes) == 1:
        trees, baseline = [], np.zeros(1)
    else:
        model = HistGradientBoostingClassifier(max_iter=ROUNDS, max_depth=DEPTH, random_state=0)
        model.fit(x, y)
        trees = [t.nodes for round_ in model._predictors for t in round_]
        baseline = model._baseline_prediction.ravel()
        if len(classes) == 2:  # one score, the second class's: the first scores zero
            trees = [n for t in trees for n in (_zero(), t)]
            baseline = np.array([0.0, baseline[0]])
    starts = np.cumsum([0] + [len(t) for t in trees[:-1]]) if trees else np.zeros(0)
    nodes = np.concatenate(trees) if trees else _zero()[:0]
    leaf = nodes["is_leaf"].astype(bool)
    return {
        "classes": classes.astype(np.int16),
        "baseline": baseline.astype(np.float32),
        "starts": np.asarray(starts, dtype=np.int32),
        "depths": np.array([t["depth"].max() for t in trees], dtype=np.int8),
        "feature": nodes["feature_idx"].astype(np.int16),
        "threshold": nodes["num_threshold"].astype(np.float64),
        "left": np.where(leaf, -1, nodes["left"].astype(int)).astype(np.int16),
        "right": np.where(leaf, -1, nodes["right"].astype(int)).astype(np.int16),
        "value": nodes["value"].astype(np.float32),
    }


def _zero() -> np.ndarray:
    """A tree of one leaf scoring zero, in scikit-learn's node layout."""
    from sklearn.ensemble._hist_gradient_boosting.common import PREDICTOR_RECORD_DTYPE

    node = np.zeros(1, dtype=PREDICTOR_RECORD_DTYPE)
    node["is_leaf"] = 1
    return node
