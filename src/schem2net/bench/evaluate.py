"""Read a verified corpus once, then score the saved predictions.

Extraction and scoring are apart: each design is read in a process of its own, with
the shipped models, drawing only, under a memory ceiling, and its prediction and
timing are written once and never overwritten. Scoring reads only what was saved, so
it can be repeated without reading the PDFs again. Only designs `verify-corpus`
admitted are read; a corpus held out whole needs SCHEM2NET_HOLDOUT=1, as `bench` does.
"""

import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from schem2net import kicad
from schem2net.bench import corpus as corpora
from schem2net.bench.score import intervals, score, summary, wiring_mistakes
from schem2net.bench.verify import content_sha, generator
from schem2net.ir import Design

MEMORY = 4 * 1024**3  # bytes of address space a design may take
SECONDS = 1800  # a design still being read after this has failed
LEARNED = ("roles.npz", "designators.npz", "groups.npz", "eagle_font.json", "eagle_fills.json")


def admitted(corpus: corpora.Corpus) -> list[corpora.Project]:
    """The corpus's designs verify-corpus admitted, each checked to be unchanged."""
    path = corpus.root / f"verified_{corpus.name}.json"
    if not path.exists():
        raise ValueError(f"{path} is missing: run verify-corpus {corpus.name} first")
    records = {r["name"]: r for r in json.loads(path.read_text())}
    split = "holdout" if corpus.tier == "independent" else "all"
    found = []
    for p in sorted(corpus.projects, key=lambda p: p.name):
        record = records.get(p.name)
        if not record or record["decision"] != "verified" or not corpus.in_split(p, split):
            continue
        out = corpus.build_dir(p)
        for label, file in (("pdf", "schematic.pdf"), ("truth", "truth.net")):
            if content_sha(out / file) != record["files"][label]:
                raise ValueError(f"{p.name}: {label} changed since it was verified")
        found.append(p)
    return found


def extract(corpus: corpora.Corpus, out: Path, workers: int = 2, library: Path | None = None):
    """Read each admitted design not read yet into out/<name>.json."""
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "SCHEM2NET_LIBRARY"}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONHASHSEED="0")
    record = out / "run.json"
    if not record.exists():
        _write(record, _probe(env, library))
    if json.loads(record.read_text()) != _probe(env, library):
        raise ValueError(f"{out} was read with other code, models or library")

    def one(project):
        target = out / project.name
        if any(target.with_suffix(s).exists() for s in (".json", ".failed.json")):
            return
        pdf = corpus.build_dir(project) / "schematic.pdf"
        cmd = [sys.executable, "-m", "schem2net.bench.evaluate", str(pdf), str(target)]
        try:
            done = subprocess.run(
                cmd + ([str(library)] if library else []),
                env=env, capture_output=True, text=True, timeout=SECONDS,
            )  # fmt: skip
            error = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        except subprocess.TimeoutExpired:
            done, error = None, f"still reading after {SECONDS} s"
        if done is None or done.returncode:
            _write(target.with_suffix(".failed.json"), {"error": error})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, admitted(corpus)))
    if json.loads(record.read_text()) != _probe(env, library):
        raise ValueError(f"the code, models or library changed while {out} was read")


def report(corpus: corpora.Corpus, out: Path) -> dict:
    """Scores of the saved predictions: per design, generator and group, with grouped
    intervals, in the form bench-compare reads."""
    designs, extra, groups = {}, {}, {}
    for p in admitted(corpus):
        truth = kicad.read_netlist(corpus.build_dir(p) / "truth.net")
        saved = out / f"{p.name}.json"
        if saved.exists():
            reading = json.loads(saved.read_text())
            if reading["pdf"] != content_sha(corpus.build_dir(p) / "schematic.pdf"):
                raise ValueError(f"{p.name} was read from another PDF than the one verified")
            predicted = Design.model_validate(reading["prediction"])
            counts = score(predicted, truth)
            found = {**reading["stats"], **wiring_mistakes(predicted, truth)}
        else:  # the whole design failed: none of its pins is right
            failed = out / f"{p.name}.failed.json"
            if not failed.exists():
                raise ValueError(f"{p.name} has not been read")
            counts = score(Design(source=truth.source), truth)
            found = {"failed": json.loads(failed.read_text())["error"]}
        designs[p.name] = counts
        extra[p.name] = {"generator": generator(p), **found}
        if p.variant_of:
            extra[p.name]["variant_of"] = p.variant_of
        groups[p.name] = corpus.groups[p.name]
    # Renderings of a design are reported beside it, not counted as designs of their own.
    names = [n for n in designs if "variant_of" not in extra[n]]
    if not names:
        raise ValueError("no design of the corpus is admitted")
    renderings: dict[str, dict] = {}
    for n, e in extra.items():
        if "variant_of" in e:
            base = e["variant_of"]
            known = designs[base].metrics()["pin_accuracy"] if base in designs else None
            renderings.setdefault(base, {base: known})
            renderings[base][n] = designs[n].metrics()["pin_accuracy"]
    by_generator = {}
    for g in sorted({extra[n]["generator"] for n in names}):
        chosen = [n for n in names if extra[n]["generator"] == g]
        by_generator[g] = {
            "designs": len(chosen),
            "groups": len({groups[n] for n in chosen}),
            "total": summary([designs[n] for n in chosen]),
            "failed": sum("failed" in extra[n] for n in chosen),
        }
    return {
        "corpus": corpus.name,
        "tier": corpus.tier,
        "run": json.loads((out / "run.json").read_text()),
        "size": {"designs": len(names), "groups": len({groups[n] for n in names})},
        "total": summary([designs[n] for n in names]),
        "intervals": intervals([designs[n] for n in names], [groups[n] for n in names]),
        "by_generator": by_generator,
        "renderings": renderings,
        "designs": {n: asdict(designs[n]) for n in names},  # what bench-compare reads
        "rendering_counts": {n: asdict(c) for n, c in designs.items() if n not in names},
        "extra": extra,
        "groups": {n: groups[n] for n in names},
    }


def _probe(env: dict, library: Path | None) -> dict:
    """What a reading depends on, asked of the Python the designs are read with: the
    extractor's code and the learned and library files it loads."""
    cmd = [sys.executable, "-m", "schem2net.bench.evaluate", "--environment"]
    found = subprocess.run(
        cmd + ([str(library)] if library else []),
        env=env, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return json.loads(found.stdout)


def _environment(library: str | None) -> dict:
    import schem2net
    from schem2net import profile

    profile.use_learned(None)
    package = Path(schem2net.__file__).parent
    code = hashlib.sha256()
    for f in sorted(package.rglob("*")):
        # The extractor's code: the bench tools that read and score it may change.
        parts = set(f.relative_to(package).parts)
        if f.suffix in (".py", ".toml") and not {"__pycache__", "bench"} & parts:
            code.update(f.relative_to(package).as_posix().encode() + f.read_bytes())
    files = {n: _digest(Path(str(profile.learned_file(n)))) for n in LEARNED}
    if library:
        files |= {f.name: _digest(f) for f in sorted(Path(library).glob("*")) if f.is_file()}
    return {
        "schem2net": schem2net.__version__,
        "package": str(package),
        "code": code.hexdigest(),
        "embedded": False,
        "files": files,
    }


def _worker(pdf: str, target: str, library: str | None) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    from schem2net import pipeline, profile

    profile.use_learned(None)
    cpu, wall = time.process_time(), time.perf_counter()
    design = pipeline.extract(
        Path(pdf), embedded=False, library_dir=Path(library) if library else None
    )
    stats = {
        "seconds": round(time.perf_counter() - wall, 2),
        "cpu_seconds": round(time.process_time() - cpu, 2),
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
        "pages_failed": sum(i.kind == "page_failed" for i in design.issues),
    }
    prediction = design.model_dump(mode="json", by_alias=True)
    reading = {"pdf": content_sha(Path(pdf)), "stats": stats, "prediction": prediction}
    _write(Path(target).with_suffix(".json"), reading)


def _write(path: Path, value) -> None:
    """Write a file whole, once: a reading is never overwritten or left half written."""
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    part.write_text(json.dumps(value, indent=1) + "\n")
    try:
        os.link(part, path)  # fails if the file exists
    finally:
        part.unlink()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    if sys.argv[1] == "--environment":
        print(json.dumps(_environment(sys.argv[2] if len(sys.argv) > 2 else None)))
    else:
        _worker(*sys.argv[1:3], sys.argv[3] if len(sys.argv) > 3 else None)
