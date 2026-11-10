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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from schem2net import kicad
from schem2net.bench import corpus as corpora
from schem2net.bench import reader
from schem2net.bench.reader import write as _write
from schem2net.bench.score import intervals, score, summary, wiring_mistakes
from schem2net.bench.verify import content_sha, drift, generator
from schem2net.ir import Design

SECONDS = 1800  # a design still being read after this has failed
READER = str(Path(reader.__file__))


def _records(corpus: corpora.Corpus) -> dict[str, dict]:
    path = corpus.root / f"verified_{corpus.name}.json"
    return {r["name"]: r for r in json.loads(path.read_text())["designs"]}


def admitted(corpus: corpora.Corpus) -> list[corpora.Project]:
    """The corpus's designs verify-corpus admitted, each checked to be unchanged."""
    path = corpus.root / f"verified_{corpus.name}.json"
    if not path.exists():
        raise ValueError(f"{path} is missing: run verify-corpus {corpus.name} first")
    # The corpus must be the one sealed: no design added, removed or regrouped, no
    # source moved to another revision, no setting changed.
    changed = drift(corpus, json.loads(path.read_text()))
    if changed:
        raise ValueError(f"{path} does not seal this corpus: {'; '.join(changed[:5])}")
    records = _records(corpus)
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


def extract(
    corpus: corpora.Corpus,
    out: Path,
    workers: int = 2,
    library: Path | None = None,
    python: str = sys.executable,
):
    """Read each admitted design not read yet into out/<name>.json, with the schem2net
    installed for `python`: the candidate's own, or a comparator's."""
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "SCHEM2NET_LIBRARY"}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONHASHSEED="0")
    record = out / "run.json"
    expected = {**_probe(env, python, library), "seal": _seal(corpus)}
    if not record.exists():
        _write(record, expected)
    if json.loads(record.read_text()) != expected:
        raise ValueError(f"{out} was read with other code, models, library, platform or seal")

    def one(project):
        target = out / project.name
        if any(target.with_suffix(s).exists() for s in (".json", ".failed.json")):
            return
        pdf = corpus.build_dir(project) / "schematic.pdf"
        reading = target.with_suffix(".json")
        cmd = [python, "-P", READER, str(pdf), content_sha(pdf), str(reading)]
        try:
            done = subprocess.run(
                cmd + ([str(library)] if library else []),
                env=env, capture_output=True, text=True, timeout=SECONDS,
            )  # fmt: skip
            error = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        except subprocess.TimeoutExpired:
            done, error = None, f"still reading after {SECONDS} s"
        if done is None or done.returncode:
            _write(target.with_suffix(".failed.json"), {"pdf": content_sha(pdf), "error": error})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, admitted(corpus)))
    if json.loads(record.read_text()) != {**_probe(env, python, library), "seal": _seal(corpus)}:
        raise ValueError(f"the code, models or library changed while {out} was read")


def report(corpus: corpora.Corpus, out: Path) -> dict:
    """Scores of the saved predictions: per design, generator and group, with grouped
    intervals, in the form bench-compare reads."""
    run = json.loads((out / "run.json").read_text())
    if run.get("seal") != _seal(corpus):
        raise ValueError(f"{out} was read under another seal of the corpus")
    designs, observable, extra, groups = {}, {}, {}, {}
    records = _records(corpus)
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
            record = json.loads(failed.read_text())
            if record["pdf"] != content_sha(corpus.build_dir(p) / "schematic.pdf"):
                raise ValueError(f"{p.name} failed on another PDF than the one verified")
            counts = score(Design(source=truth.source), truth)
            found = {"failed": record["error"]}
        designs[p.name] = counts
        text = records[p.name].get("text") or {}
        # Secondary: only the parts a drawing can name, without those the source does
        # not print and the instances of a channel drawn once.
        hidden = {*text.get("refs_unprinted", []), *text.get("refs_channel", [])}
        seen = _without(truth, hidden)
        observable[p.name] = score(
            predicted if saved.exists() else Design(source=truth.source), seen
        )
        extra[p.name] = {
            "generator": generator(p),
            "evidence": records[p.name]["evidence"],
            "unprinted": text.get("refs_unprinted", []),
            # Scored as any pin: the truth is not changed, but how many there are is shown.
            "unprinted_pins": sum(
                ref in text.get("refs_unprinted", [])
                for n in truth.nets
                if len(set(n.pins)) >= 2
                for ref, _ in set(n.pins)
            ),
            "channels": text.get("refs_channel", []),
            **found,
        }
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
    by_evidence = {
        e: summary([designs[n] for n in names if extra[n]["evidence"] == e])
        for e in sorted({extra[n]["evidence"] for n in names})
    }
    return {
        "corpus": corpus.name,
        "tier": corpus.tier,
        "run": run,
        "size": {"designs": len(names), "groups": len({groups[n] for n in names})},
        "total": summary([designs[n] for n in names]),
        "intervals": intervals([designs[n] for n in names], [groups[n] for n in names]),
        "by_generator": by_generator,
        "by_evidence": by_evidence,
        "observable": summary([observable[n] for n in names]),
        "observable_designs": {n: asdict(observable[n]) for n in names},
        "renderings": renderings,
        "designs": {n: asdict(designs[n]) for n in names},  # what bench-compare reads
        "rendering_counts": {n: asdict(c) for n, c in designs.items() if n not in names},
        "extra": extra,
        "groups": {n: groups[n] for n in names},
    }


def _without(truth: Design, refs: set[str]) -> Design:
    """The truth without these parts and their pins."""
    return truth.model_copy(
        update={
            "components": [c for c in truth.components if c.ref not in refs],
            "nets": [
                n.model_copy(update={"pins": [q for q in n.pins if q[0] not in refs]})
                for n in truth.nets
            ],
        }
    )


def _probe(env: dict, python: str, library: Path | None) -> dict:
    """What a reading depends on, asked of the Python the designs are read with: the
    extractor's code, the learned and library files it loads, and its platform."""
    cmd = [python, "-P", READER, "--environment"]
    found = subprocess.run(
        cmd + ([str(library)] if library else []), env=env, capture_output=True, text=True
    )
    if found.returncode:
        raise ValueError(f"cannot load schem2net to read with: {found.stderr.strip()[-300:]}")
    return json.loads(found.stdout)


def _seal(corpus: corpora.Corpus) -> str:
    path = corpus.root / f"verified_{corpus.name}.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()
