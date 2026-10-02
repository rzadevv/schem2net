"""Learn the roles of paths and texts from colour pages, for pages printed in black.

On a colour page the generator's colours say what every path and text is, so the
dev split of each corpus gives labelled examples; no truth netlist is used.
Gradient-boosted trees are fitted to them for each generator (scikit-learn, needed
only here) and written out as plain node arrays, which `roles.Forest` evaluates.
Paths take two passes: the second sees first guesses at the roles of what each path
touches, made by models that never saw that design, as they will be on a new one.
"""

from pathlib import Path

import numpy as np

from schem2net import grid, ingest, pdf, profile, roles

ROUNDS = 150
DEPTH = 6
FOLDS = 4  # designs held out in turn to make the first guesses the second pass learns from

Example = tuple  # path features and roles, text features and roles, path contacts


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
        touching = roles.contacts(paths)
        out.append(
            (
                roles.path_features(paths, texts, touching),
                np.array(path_roles),
                roles.text_features(texts, paths, path_roles),
                np.array([roles.text_role(t, rules) for t in texts]),
                touching,
            )
        )
    return out


def train(examples: dict[str, list[list[Example]]]) -> dict[str, np.ndarray]:
    """For each generator, from the pages of each of its designs, the models of paths
    (first and second pass) and of texts, as arrays named "<generator>.<model>.<field>"."""
    arrays = {}
    for generator, designs in examples.items():
        pages = [page for design in designs for page in design]
        first = _fit([(e[0], e[1]) for e in pages])
        second = _fit([(np.hstack([e[0], g]), e[1]) for e, g in _guesses(designs)])
        texts = _fit([(e[2], e[3]) for e in pages if len(e[3])])
        for kind, model in (("paths", first), ("paths2", second), ("texts", texts)):
            for name, value in model.items():
                arrays[f"{generator}.{kind}.{name}"] = value
    return arrays


def _guesses(designs: list[list[Example]]):
    """Each page with first-pass guesses at its paths' roles, from a model fitted to the
    other designs."""
    for fold in range(FOLDS):
        held = [d for k, d in enumerate(designs) if k % FOLDS == fold]
        rest = [e for k, d in enumerate(designs) if k % FOLDS != fold for e in d]
        if not held or not rest:
            continue
        forest = roles.Forest(
            {f"m.{k}": v for k, v in _fit([(e[0], e[1]) for e in rest]).items()}, "m"
        )
        for design in held:
            for e in design:
                yield e, roles.context_features(forest.scores(e[0]), e[4], len(e[1]))


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
