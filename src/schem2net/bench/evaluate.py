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
    """Read each admitted design not read yet into out/<name>.prediction.json."""
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "SCHEM2NET_LIBRARY")}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONHASHSEED="0")
    record = out / "run.json"
    if not record.exists():
        record.write_text(json.dumps(_environment(library), indent=1) + "\n")
    elif json.loads(record.read_text()) != _environment(library):
        raise ValueError(f"{out} was read with other code, models or library")

    def one(project):
        target = out / project.name
        if target.with_suffix(".prediction.json").exists():
            return
        pdf = corpus.build_dir(project) / "schematic.pdf"
        cmd = [sys.executable, "-m", "schem2net.bench.evaluate", str(pdf), str(target)]
        cmd += [str(library)] if library else []
        try:
            done = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=SECONDS,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY)),
            )  # fmt: skip
            error = done.stderr.strip().splitlines()[-1:] if done.returncode else None
        except subprocess.TimeoutExpired:
            error = [f"still reading after {SECONDS} s"]
        if error:
            _write(target.with_suffix(".failed.json"), {"error": error[0] if error else ""})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, admitted(corpus)))


def report(corpus: corpora.Corpus, out: Path) -> dict:
    """Scores of the saved predictions: per design, generator and group, with grouped
    intervals, in the form bench-compare reads."""
    designs, extra, groups = {}, {}, {}
    for p in admitted(corpus):
        truth = kicad.read_netlist(corpus.build_dir(p) / "truth.net")
        saved = out / f"{p.name}.prediction.json"
        if saved.exists():
            predicted = Design.load(saved)
            counts = score(predicted, truth)
            found = {
                **json.loads((out / f"{p.name}.timing.json").read_text()),
                **wiring_mistakes(predicted, truth),
            }
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
        "total": summary([designs[n] for n in names]),
        "intervals": intervals([designs[n] for n in names], [groups[n] for n in names]),
        "by_generator": by_generator,
        "renderings": renderings,
        "designs": {n: asdict(c) for n, c in designs.items()},
        "extra": extra,
        "groups": groups,
    }


def _environment(library: Path | None) -> dict:
    """What a reading depends on: the code's version and the learned and library files."""
    import schem2net
    from schem2net import profile

    profile.use_learned(None)
    package = Path(schem2net.__file__).parent
    code = hashlib.sha256()
    for f in sorted(package.rglob("*")):
        if f.suffix in (".py", ".toml") and "__pycache__" not in f.parts:
            code.update(f.relative_to(package).as_posix().encode() + f.read_bytes())
    files = {n: _digest(Path(str(profile.learned_file(n)))) for n in LEARNED}
    if library:
        files |= {str(f): _digest(f) for f in sorted(library.glob("*")) if f.is_file()}
    return {
        "schem2net": schem2net.__version__,
        "code": code.hexdigest(),
        "embedded": False,
        "files": files,
    }


def _worker(pdf: str, target: str, library: str | None) -> None:
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
    _write(
        Path(target).with_suffix(".prediction.json"), design.model_dump(mode="json", by_alias=True)
    )
    _write(Path(target).with_suffix(".timing.json"), stats)


def _write(path: Path, value) -> None:
    with path.open("x") as stream:  # never overwrite a reading
        json.dump(value, stream, indent=1)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    _worker(*sys.argv[1:3], sys.argv[3] if len(sys.argv) > 3 else None)
