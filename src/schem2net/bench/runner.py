"""Run the extractor over a corpus and score each design."""

import random
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from schem2net import kicad, pipeline, profile
from schem2net.bench.corpus import Corpus
from schem2net.bench.score import score
from schem2net.ir import Design


def run(
    corpus: Corpus,
    split: str = "dev",
    sample: int | None = None,
    extract: Callable[[Path], Design] = pipeline.extract,
    workers: int = 2,
    judge: Callable[[Design, Design], Any] = score,
    folds: Path | None = None,
) -> list[tuple[str, Any]]:
    """Each design's name and what judge makes of its prediction and truth, by default
    its Counts. With `folds`, each dev design is read with the models learned without
    its fold, from folds/fold-K."""
    projects = [p for p in corpus.projects if corpus.in_split(p, split)]
    if sample is not None and sample < len(projects):
        projects = random.Random(0).sample(projects, sample)

    projects = sorted(projects, key=lambda p: p.name)
    dirs = [corpus.build_dir(p) for p in projects]
    learned = [
        folds / f"fold-{corpus.fold(p)}" if folds and corpus.split(p) == "dev" else None
        for p in projects
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:  # each holds whole PDFs in memory
        found = list(pool.map(partial(_judge, extract=extract, judge=judge), dirs, learned))
    return [(p.name, f) for p, f in zip(projects, found, strict=True)]


def _judge(out: Path, learned: Path | None, extract: Callable, judge: Callable) -> Any:
    profile.use_learned(learned)
    return judge(extract(out / "schematic.pdf"), kicad.read_netlist(out / "truth.net"))
