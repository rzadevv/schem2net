"""Find the roles of paths and texts on a page printed without colour.

Generators draw wires, symbols, labels and fields in colours of their own, and the
profiles read roles from them. A page printed in black or grey loses that, so the
role of each path is predicted from its shape, what it touches and the paths drawn
around it, and the role of each text from what it says and what it sits on. The
models are learned from colour pages, where the colours themselves say what each
path and text is. The page is then given the profile's colours and read as usual.
"""

from dataclasses import replace
from functools import cache
from importlib import resources

import numpy as np

from schem2net import geometry, scene, strokes
from schem2net.primitives import Page, Path, Text
from schem2net.profile import Profile

# Roles, in the order a colour is matched against them: a colour two roles share
# goes to the first.
PATH_ROLES = ("wire", "bus", "pin", "symbol", "hier_label", "sheet_pin", "note")
TEXT_ROLES = ("local_label", "global_label", "hier_label", "pin_number", "field", "bus", "note")

TOUCH = 0.05  # mm between ends that meet
DOT = 1.5  # mm; filled shapes smaller than this may be junction dots
CONTEXT = 5  # paths drawn before and after that a path is compared with
NEAR = 3.0  # mm around a text searched for what it sits on
ALONG_GAP = 1.0  # mm between a net label and the wire it sits on
GREY_SPREAD = 8  # an ink whose red, green and blue differ by no more than this is grey


def colourless(page: Page) -> bool:
    """True if every path is inked in black or grey: printed without colour. (Generators
    may use black or grey for some roles, but never for all of them.)"""
    inks = {p.stroke or p.fill for p in page.paths if p.stroke or p.fill}
    return bool(inks) and all(max(c) - min(c) <= GREY_SPREAD for c in inks)


def path_role(path: Path, profile: Profile) -> int:
    """The role a path's colour gives it, as an index; len(PATH_ROLES) for none."""
    return _role(path.stroke or path.fill, profile, PATH_ROLES)


def text_role(text: Text, profile: Profile) -> int:
    return _role(text.color, profile, TEXT_ROLES)


def drawing(page: Page, profile: Profile) -> list[Path]:
    """The paths whose roles are found: one of each copy, lettering left out, in order."""
    paths = [p for p in scene.unique_paths(page.paths) if p.subpaths and p.subpaths[0]]
    if profile.text_font:
        _, lettering = strokes.read(paths, profile.text_font)
        paths = [p for p in paths if p.seq not in lettering]
    return sorted(paths, key=lambda p: p.seq)


def contacts(paths: list[Path]) -> list[tuple[list[int], list[int]]]:
    """For each path and each of its two ends, the paths ending there and the paths
    passing through it: (meeting, crossing) per end, so four lists per path."""
    ends = [(p.subpaths[0][0], p.subpaths[0][-1]) for p in paths]
    index = geometry.GridIndex(cell=2.0)
    for k, p in enumerate(paths):
        index.add(k, p.bbox)
    out = []
    for k in range(len(paths)):
        per_end = []
        for e in ends[k]:
            meet, land = [], []
            for j in index.near(e, 2 * TOUCH):
                if j == k:
                    continue
                if any(geometry.distance(e, f) < TOUCH for f in ends[j]):
                    meet.append(j)
                elif any(
                    geometry.distance_to_segment(e, s) < TOUCH
                    for s in geometry.segments(paths[j].subpaths[0])
                ):
                    land.append(j)
            per_end.append((meet, land))
        out.append(tuple(per_end))
    return out


def path_features(paths: list[Path], texts: list[Text], touching=None) -> np.ndarray:
    """One row per path, in drawing order: its shape, its contacts, its neighbours."""
    n = len(paths)
    touching = touching if touching is not None else contacts(paths)
    ends = [(p.subpaths[0][0], p.subpaths[0][-1]) for p in paths]
    widths = [round(p.width, 3) for p in paths]
    lines = [len(p.subpaths) == 1 and len(p.subpaths[0]) == 2 and not p.fill for p in paths]
    line_widths = [w for w, line in zip(widths, lines, strict=True) if line]
    common = max(set(line_widths), key=line_widths.count, default=0.0)
    dots = geometry.GridIndex(cell=2.0)
    for k, p in enumerate(paths):
        if p.fill and _size(p.bbox) < DOT:
            dots.add(k, p.bbox)
    text_index = _index([t.bbox for t in texts])

    rows = []
    for k, p in enumerate(paths):
        x0, y0, x1, y1 = p.bbox
        sub = p.subpaths[0]
        a, b = ends[k]
        length = sum(geometry.distance(u, v) for u, v in zip(sub, sub[1:], strict=False))
        axis = lines[k] and (abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3)
        meets = [len(meet) for meet, _ in touching[k]]
        lands = [len(land) for _, land in touching[k]]
        on_dot = lines[k] and any(dots.near(e, 0.3) for e in (a, b))
        near = text_index.within((x0 - NEAR, y0 - NEAR, x1 + NEAR, y1 + NEAR))
        text_gap = min((geometry.bbox_gap(p.bbox, texts[j].bbox) for j in near), default=NEAR)
        around = [j for j in range(max(0, k - CONTEXT), min(n, k + CONTEXT + 1)) if j != k]
        alike = sum(lines[j] and widths[j] == widths[k] for j in around) / max(len(around), 1)
        run = 1
        if lines[k]:
            j = k - 1
            while j >= 0 and lines[j] and widths[j] == widths[k]:
                run, j = run + 1, j - 1
            j = k + 1
            while j < n and lines[j] and widths[j] == widths[k]:
                run, j = run + 1, j + 1
        rows.append(
            [
                len(sub),
                len(p.subpaths),
                len(sub) > 2 and geometry.distance(sub[0], sub[-1]) < 1e-3,
                p.fill is not None,
                p.stroke is not None,
                p.curved,
                lines[k],
                axis,
                length,
                p.width,
                widths[k] == common,
                _size(p.bbox),
                min(x1 - x0, y1 - y0),
                min(meets),
                max(meets),
                min(lands),
                max(lands),
                on_dot,
                text_gap,
                alike,
                np.log1p(run),
                k / max(n - 1, 1),
            ]
        )
    return _matrix(rows)


def context_features(scores: np.ndarray, touching, n: int) -> np.ndarray:
    """One row per path from first guesses at every path's role, as scores per role:
    its own, the lowest and highest over its two ends of what meets it there, and the
    mean over the paths drawn around it. A line is a wire if wires carry on from it."""
    width = scores.shape[1]
    rows = []
    for k in range(n):
        per_end = []
        for meet, land in touching[k]:
            near = meet + land
            per_end.append(scores[near].mean(axis=0) if near else np.zeros(width))
        around = [j for j in range(max(0, k - CONTEXT), min(n, k + CONTEXT + 1)) if j != k]
        drawn = scores[around].mean(axis=0) if around else np.zeros(width)
        rows.append(np.concatenate([scores[k], np.minimum(*per_end), np.maximum(*per_end), drawn]))
    return np.asarray(rows) if rows else np.zeros((0, 4 * width))


def text_features(texts: list[Text], paths: list[Path], roles: list[int]) -> np.ndarray:
    """One row per text: what it says, and the paths of each role it sits on or near."""
    wire, symbol = PATH_ROLES.index("wire"), PATH_ROLES.index("symbol")
    pin = PATH_ROLES.index("pin")
    wires = [s for p, r in zip(paths, roles, strict=True) if r == wire for s in _segments(p)]
    wire_boxes = [geometry.bbox_of(s) for s in wires]
    wire_index = _index(wire_boxes)
    wire_ends = [(*e, *e) for s in wires for e in s]
    wire_end_index = _index(wire_ends)
    marks = [p for p, r in zip(paths, roles, strict=True) if r in (symbol, pin)]
    mark_ends = [(*e, *e) for p in marks for e in (p.subpaths[0][0], p.subpaths[0][-1])]
    mark_end_index = _index(mark_ends)
    closed = [
        p
        for p in paths
        if len(p.subpaths[0]) > 3 and geometry.distance(p.subpaths[0][0], p.subpaths[0][-1]) < 1e-3
    ]
    bodies = [p.bbox for p, r in zip(paths, roles, strict=True) if r == symbol and p in closed]
    body_index = _index(bodies)
    closed_index = _index([p.bbox for p in closed])
    text_index = _index([t.bbox for t in texts])

    rows = []
    for k, t in enumerate(texts):
        x0, y0, x1, y1 = t.bbox
        grown = (x0 - NEAR, y0 - NEAR, x1 + NEAR, y1 + NEAR)
        s = t.text.strip()
        wire_gap = _gap(t.bbox, wire_boxes, wire_index.within(grown))
        end_gap = _gap(t.bbox, wire_ends, wire_end_index.within(grown))
        mark_gap = _gap(t.bbox, mark_ends, mark_end_index.within(grown))
        holders = [
            closed[j]
            for j in closed_index.within(t.bbox)
            if _contains(closed[j].bbox, t.bbox)
            and _size(closed[j].bbox) < 6 * max(x1 - x0, y1 - y0, 1)
        ]
        holder = min(holders, key=lambda p: _size(p.bbox), default=None)
        others = [j for j in text_index.within(grown) if j != k]
        along = _along(t.bbox, [wires[j] for j in wire_index.within(grown)])
        inside = any(_contains(bodies[j], t.bbox) for j in body_index.within(t.bbox))
        rows.append(
            [
                len(s),
                sum(c.isdigit() for c in s) / max(len(s), 1),
                sum(c.isalpha() for c in s) / max(len(s), 1),
                sum(c.isupper() for c in s) / max(sum(c.isalpha() for c in s), 1),
                s.isdigit(),
                any(c in s for c in "/_+-"),
                t.size,
                round(t.angle) % 180 == 90,
                wire_gap,
                end_gap,
                mark_gap,
                holder is not None,
                _size(holder.bbox) if holder else 0.0,
                len(others),
                along,
                inside,
            ]
        )
    return _matrix(rows)


def _along(box, segments) -> float:
    """The share of a text's length that a wire runs along, just past its long side, as
    under a net label."""
    x0, y0, x1, y1 = box
    best = 0.0
    for (ax, ay), (bx, by) in segments:
        across = abs(ay - by) < 1e-3 and x1 > x0  # by the top or bottom of the text
        upward = abs(ax - bx) < 1e-3 and y1 > y0  # by either side of turned text
        if across and min(abs(ay - y0), abs(ay - y1)) <= ALONG_GAP:
            shared = min(x1, max(ax, bx)) - max(x0, min(ax, bx))
            best = max(best, shared / (x1 - x0))
        elif upward and min(abs(ax - x0), abs(ax - x1)) <= ALONG_GAP:
            shared = min(y1, max(ay, by)) - max(y0, min(ay, by))
            best = max(best, shared / (y1 - y0))
    return best


def recolour(page: Page, profile: Profile, models=None) -> Page:
    """The page with each path and text given the profile's colour for its predicted role.
    Text drawn as strokes, and anything whose role the profile has no colour for, keeps
    its ink."""
    first, second, texts_model = models or _models(profile.name)
    paths = drawing(page, profile)
    texts = [t for t in page.texts if t.visible]
    if not paths:
        return page
    touching = contacts(paths)
    base = path_features(paths, texts, touching)
    guesses = context_features(first.scores(base), touching, len(paths))
    path_roles = [int(r) for r in second.predict(np.hstack([base, guesses]))]
    text_roles = (
        [int(r) for r in texts_model.predict(text_features(texts, paths, path_roles))]
        if texts
        else []
    )
    # Copies of one path, which the page may hold, take the role found for the first.
    role_of = {_shape_key(p): r for p, r in zip(paths, path_roles, strict=True)}

    def coloured(p: Path) -> Path:
        colour = _colour(profile, PATH_ROLES, role_of.get(_shape_key(p)))
        if colour is None:
            return p
        return replace(p, stroke=colour if p.stroke else None, fill=colour if p.fill else None)

    text_colour = {
        id(t): _colour(profile, TEXT_ROLES, r) for t, r in zip(texts, text_roles, strict=True)
    }
    return replace(
        page,
        paths=[coloured(p) for p in page.paths],
        texts=[replace(t, color=text_colour.get(id(t)) or t.color) for t in page.texts],
    )


class Forest:
    """Gradient-boosted trees: one tree per class in each round, their leaf values summed
    into a score per class. Node arrays of all trees are stored end to end."""

    def __init__(self, arrays: dict, prefix: str):
        def get(name):
            return arrays[f"{prefix}.{name}"]

        self.classes = get("classes")
        self.baseline = get("baseline").astype(float)
        self.starts, self.depths = get("starts"), get("depths")
        self.feature, self.threshold = get("feature").astype(int), get("threshold")
        self.left, self.right = get("left").astype(int), get("right").astype(int)
        self.value = get("value")

    def predict(self, rows: np.ndarray) -> np.ndarray:
        if len(self.classes) == 1:
            return np.full(len(rows), self.classes[0])
        return self.classes[self._raw(rows).argmax(axis=1)]

    def scores(self, rows: np.ndarray) -> np.ndarray:
        """How likely each row is to have each role, one column per role of PATH_ROLES
        and one for none."""
        out = np.zeros((len(rows), len(PATH_ROLES) + 1))
        if len(self.classes) == 1:
            out[:, self.classes[0]] = 1.0
            return out
        raw = self._raw(rows)
        odds = np.exp(raw - raw.max(axis=1, keepdims=True))
        out[:, self.classes] = odds / odds.sum(axis=1, keepdims=True)
        return out

    def _raw(self, rows: np.ndarray) -> np.ndarray:
        scores = np.tile(self.baseline, (len(rows), 1))
        per_round = len(self.baseline)
        for t, (start, depth) in enumerate(zip(self.starts, self.depths, strict=True)):
            scores[:, t % per_round] += self._run(int(start), int(depth), rows)
        return scores

    def _run(self, start: int, depth: int, rows: np.ndarray) -> np.ndarray:
        node = np.full(len(rows), start)
        every = np.arange(len(rows))
        for _ in range(depth):
            leaf = self.left[node] < 0
            go_left = rows[every, self.feature[node]] <= self.threshold[node]
            step = np.where(go_left, self.left[node], self.right[node]) + start
            node = np.where(leaf, node, step)
        return self.value[node]


@cache
def _models(generator: str):
    with resources.files("schem2net").joinpath("profiles", "roles.npz").open("rb") as f:
        arrays = dict(np.load(f))
    return tuple(Forest(arrays, f"{generator}.{kind}") for kind in ("paths", "paths2", "texts"))


def _role(colour, profile: Profile, roles: tuple[str, ...]) -> int:
    for k, role in enumerate(roles):
        if profile.is_(role, colour):
            return k
    return len(roles)


def _colour(profile: Profile, roles: tuple[str, ...], k: int | None):
    if k is None or k >= len(roles) or not profile.colors.get(roles[k]):
        return None
    return min(profile.colors[roles[k]])


def _matrix(rows: list[list]) -> np.ndarray:
    return np.asarray(rows, dtype=float) if rows else np.zeros((0, 0))


def _segments(p: Path):
    return [s for sub in p.subpaths for s in zip(sub, sub[1:], strict=False)]


def _index(boxes) -> geometry.GridIndex:
    index = geometry.GridIndex(cell=5.0)
    for k, b in enumerate(boxes):
        index.add(k, b)
    return index


def _gap(box, boxes, near) -> float:
    """The distance from box to the nearest of the given boxes, at most NEAR."""
    return min((geometry.bbox_gap(box, boxes[j]) for j in near), default=NEAR)


def _contains(outer, inner) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _shape_key(p: Path) -> tuple:
    return tuple((round(x, 3), round(y, 3)) for sub in p.subpaths for x, y in sub)


def _size(box) -> float:
    return max(box[2] - box[0], box[3] - box[1])
