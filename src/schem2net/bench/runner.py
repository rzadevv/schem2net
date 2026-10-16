"""Run the extractor over a corpus and score each design."""

import random
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from schem2net import kicad, pipeline
from schem2net.bench.corpus import Corpus
from schem2net.bench.score import Counts, score
from schem2net.ir import Design


def run(
    corpus: Corpus,
    split: str = "dev",
    sample: int | None = None,
    extract: Callable[[Path], Design] = pipeline.extract,
    workers: int = 2,
) -> list[tuple[str, Counts]]:
    projects = [
        p
        for p in corpus.projects
        if corpus.is_built(p) and (split == "all" or corpus.split(p) == split)
    ]
    if sample is not None and sample < len(projects):
        projects = random.Random(0).sample(projects, sample)

    projects = sorted(projects, key=lambda p: p.name)
    dirs = [corpus.build_dir(p) for p in projects]
    with ProcessPoolExecutor(max_workers=workers) as pool:  # each holds whole PDFs in memory
        counts = list(pool.map(partial(_score, extract=extract), dirs))
    return [(p.name, c) for p, c in zip(projects, counts, strict=True)]


def _score(out: Path, extract: Callable[[Path], Design]) -> Counts:
    return score(extract(out / "schematic.pdf"), kicad.read_netlist(out / "truth.net"))
