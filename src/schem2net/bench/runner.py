"""Run the extractor over a corpus and score each design."""

import random
from collections.abc import Callable
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
) -> list[tuple[str, Counts]]:
    projects = [
        p
        for p in corpus.projects
        if corpus.is_built(p) and (split == "all" or corpus.split(p) == split)
    ]
    if sample is not None and sample < len(projects):
        projects = random.Random(0).sample(projects, sample)

    results = []
    for project in sorted(projects, key=lambda p: p.name):
        out = corpus.build_dir(project)
        truth = kicad.read_netlist(out / "truth.net")
        predicted = extract(out / "schematic.pdf")
        results.append((project.name, score(predicted, truth)))
    return results
