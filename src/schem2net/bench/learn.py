"""The learned files of profiles/: which dev designs each is learned from, and how.

Learning takes two steps: rows read from each design, which is slow and the same
whichever designs are kept, then models fitted to the rows of the designs kept. So the
models of each fold of the dev split, each learned without that fold's designs, cost
one reading of each design. Rows are read with the shipped models: a fold's model never
sees the fold's designs, though rows of the others were read with models that had.
"""

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from schem2net.bench import corpus as corpora
from schem2net.bench import designators, font, groups, roles

GENERATORS = {"a": "kicad", "b": "altium", "c": "eagle", "e": "easyeda", "f": "orcad"}

Design = tuple[str, Path]  # corpus name, build folder
Rows = list[tuple[Design, object]]


def _role_rows(design: Design):
    name, folder = design
    return roles.rows((GENERATORS[name], folder / "schematic.pdf"))


def _designator_rows(design: Design):
    return designators.rows(design[1])


def _group_rows(design: Design):
    return groups.rows(design[1])


def _font_rows(design: Design):
    folder = design[1]
    return font.samples_of((folder / "schematic.sch", folder / "schematic.pdf"))


def _write_roles(rows: Rows, out: Path, workers: int) -> str:
    by_generator: dict[str, list] = {}
    for (name, _), pages in rows:
        by_generator.setdefault(GENERATORS[name], []).append(pages)
    np.savez_compressed(out / "roles.npz", **roles.train(by_generator))
    counts = ", ".join(
        f"{g} {sum(len(e[1]) for d in designs for e in d)}" for g, designs in by_generator.items()
    )
    return f"roles.npz: paths of {counts}"


def _write_designators(rows: Rows, out: Path, workers: int) -> str:
    examples = [e for _, found in rows for e in found]
    np.savez_compressed(out / "designators.npz", **designators.train(examples))
    texts = {g: 0 for g, _, _ in examples}
    for g, _, labels in examples:
        texts[g] += int((labels >= 0).sum())
    return f"designators.npz: {len(rows)} designs, texts {texts}"


def _write_groups(rows: Rows, out: Path, workers: int) -> str:
    examples = [found for _, found in rows]
    np.savez_compressed(out / "groups.npz", **groups.train(examples))
    pairs = sum(int((y >= 0).sum()) for _, _, y in examples)
    return f"groups.npz: {pairs} pairs of shapes in {len(rows)} designs"


def _write_font(rows: Rows, out: Path, workers: int) -> str:
    found = [s for _, (stroked, _) in rows for s in stroked]
    filled = [s for _, (_, outlined) in rows for s in outlined]
    # Then glyphs too rare to place by position, from lines missing only them.
    table = font.build(found)
    shapes = [
        (e["char"], [tuple(map(tuple, seg)) for seg in sh]) for e in table for sh in e["shapes"]
    ]
    jobs = [(d / "schematic.sch", d / "schematic.pdf", shapes) for (_, d), _ in rows]
    with ProcessPoolExecutor(max_workers=workers) as pool:  # each holds whole PDFs in memory
        found += [s for got in pool.map(font.gap_samples_of, jobs) for s in got]
    table = font.build(found)
    font.write(table, out / "eagle_font.json")
    fills = font.build_fills(filled)
    font.write(fills, out / "eagle_fills.json")
    return (
        f"eagle_font.json: {len(table)} stroked characters from {len(found)} glyphs, "
        f"{len(fills)} outlined from {len(filled)}, in {len(rows)} designs"
    )


@dataclass(frozen=True)
class Kind:
    corpora: str
    rows: Callable[[Design], object]
    write: Callable[[Rows, Path, int], str]
    from_source: bool = False  # only designs whose Eagle or EasyEDA source places each part


KINDS = {
    "roles": Kind("abcef", _role_rows, _write_roles),
    "designators": Kind("abcde", _designator_rows, _write_designators),
    "groups": Kind("cde", _group_rows, _write_groups, from_source=True),
    "font": Kind("c", _font_rows, _write_font),
}


def dev_designs(kind: Kind, bench_dir: Path) -> list[tuple[Design, int]]:
    """The dev designs a kind is learned from, each with its fold."""
    out = []
    for name in kind.corpora:
        try:
            loaded = corpora.load(name, bench_dir)
        except FileNotFoundError:
            continue
        out += [
            ((name, loaded.build_dir(p)), loaded.fold(p))
            for p in loaded.projects
            if loaded.in_split(p, "dev") and (p.eagle or p.easyeda or not kind.from_source)
        ]
    return out


def learn(
    names: list[str], bench_dir: Path, out: Path, workers: int = 2, folds: bool = False
) -> list[str]:
    """Learn each named kind from the dev designs into `out`, or with `folds` into
    out/fold-K for each fold K, from the designs of the other folds. Returns what each
    file was learned from."""
    lines = []
    for name in names:
        kind = KINDS[name]
        found = dev_designs(kind, bench_dir)
        with ProcessPoolExecutor(max_workers=workers) as pool:  # each holds whole PDFs in memory
            rows = list(pool.map(kind.rows, [design for design, _ in found]))
        parts = [(out / f"fold-{k}", k) for k in range(corpora.FOLDS)] if folds else [(out, None)]
        for folder, held in parts:
            folder.mkdir(parents=True, exist_ok=True)
            kept = [(d, r) for (d, fold), r in zip(found, rows, strict=True) if fold != held]
            lines.append(f"{folder}/{kind.write(kept, folder, workers)}")
    return lines
