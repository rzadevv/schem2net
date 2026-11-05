"""One frozen release experiment, with extraction separated from scoring.

Run with the installed wheel's Python: release_eval.py ROOT run|summarize.
The run refuses to overwrite its start marker or any prediction. Summarizing
saved predictions is repeatable and never invokes extraction.
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def worker(pdf, output, libraries):
    # One native thread keeps the identical 4 GiB ceiling meaningful on this host.
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    from schem2net import pipeline, profile

    profile.use_learned(None)
    cpu, wall = time.process_time(), time.perf_counter()
    design = pipeline.extract(
        Path(pdf), embedded=False, library_dir=Path(libraries) if libraries else None
    )
    stats = {
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "package": str(Path(profile.__file__).resolve()),
    }
    write(
        Path(output).with_suffix(".prediction.json"), design.model_dump(mode="json", by_alias=True)
    )
    write(Path(output).with_suffix(".timing.json"), stats)


def run(root):
    manifest = root / "panel.json"
    freeze = json.loads(Path("docs/release-2026-11-05-freeze.json").read_text())
    panel = json.loads(manifest.read_text())
    for row in panel:
        for key in ("pdf", "truth"):
            assert digest(root / row[key]) == row[key + "_sha256"], row["name"]
    for name, expected in freeze["libraries"].items():
        assert digest(root / "libraries" / name) == expected
    for version in ("initial", "recent", "candidate"):
        source = root / version / "src"
        for relative, expected in freeze["candidate_files"].items():
            if Path(relative).name in freeze["installed_environment"]["models"]:
                assert digest(root / version / relative) == expected
        assert (source / "schem2net").is_dir()
    # Probe paths and models in each actual extraction environment before starting.
    environments = {}
    for version in ("initial", "recent", "candidate"):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "SCHEM2NET_LIBRARY", "SCHEM2NET_HOLDOUT")
        }
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONHASHSEED="0")
        if version != "candidate":
            env["PYTHONPATH"] = str(root / version / "src")
        code = (
            "import hashlib,json; from schem2net import profile; "
            "profile.use_learned(None); print(json.dumps({'package':profile.__file__,"
            "'models':{n:hashlib.sha256(profile.learned_file(n).read_bytes()).hexdigest() "
            "for n in ['roles.npz','designators.npz','groups.npz',"
            "'eagle_font.json','eagle_fills.json']}}))"
        )
        probe = subprocess.run(
            [sys.executable, "-c", code], env=env, text=True, capture_output=True, check=True
        )
        check = json.loads(probe.stdout)
        for name, expected in freeze["installed_environment"]["models"].items():
            assert check["models"][name] == expected["sha256"]
        if version == "candidate":
            assert "/site-packages/schem2net/" in check["package"]
        environments[version] = env, check
    write(
        root / "RUN_STARTED.json",
        {
            "panel_sha256": digest(manifest),
            "freeze_sha256": digest(Path("docs/release-2026-11-05-freeze.json")),
            "driver_sha256": digest(Path(__file__)),
            "python": sys.version,
            "models": {k: v[1] for k, v in environments.items()},
            "limits": {
                "address_space_bytes": 4 * 1024**3,
                "outer_seconds": 1800,
                "workers": 2,
                "native_threads": 1,
            },
        },
    )

    def design_job(job):
        index, row = job
        versions = ["initial", "recent", "candidate"]
        versions = versions[index % 3 :] + versions[: index % 3]
        for mode in ("primary", "library"):
            for version in versions:
                out = root / "predictions" / mode / version / row["name"]
                out.parent.mkdir(parents=True, exist_ok=True)
                cmd = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "worker",
                    str(root / row["pdf"]),
                    str(out),
                    str(root / "libraries") if mode == "library" else "",
                ]
                start = time.perf_counter()
                record = {"name": row["name"], "version": version, "mode": mode}
                try:
                    result = subprocess.run(
                        cmd,
                        env=environments[version][0],
                        capture_output=True,
                        text=True,
                        timeout=1800,
                    )
                    record.update(
                        exit=result.returncode, stdout=result.stdout, stderr=result.stderr
                    )
                except subprocess.TimeoutExpired as error:
                    record.update(exit=None, failure=str(error))
                record["process_wall_seconds"] = time.perf_counter() - start
                write(out.with_suffix(".process.json"), record)
                print(mode, version, row["name"], record["exit"], flush=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(design_job, enumerate(panel)))
    write(root / "RUN_FINISHED.json", {"designs": len(panel)})


def diagnostics(pred, truth):
    from schem2net.bench.score import align
    from schem2net.ir import unnumbered

    aligned = align(pred, truth)
    true_owner = {p: i for i, net in enumerate(aligned.true_nets) for p in net}
    pred_owner = {p: i for i, net in enumerate(aligned.pred_nets) for p in net}
    wrong = [
        {
            "pin": p,
            "truth_net": t,
            "pred_net": pred_owner[p],
            "confidence": aligned.confidence[pred_owner[p]],
            "issue_named": p in aligned.doubted,
        }
        for p, t in true_owner.items()
        if p in pred_owner and aligned.match.get(t) != pred_owner[p]
    ]
    true_pins = {p for n in truth.nets for p in n.pins}
    true_pins |= {(c.ref, p.num) for c in truth.components for p in c.pins}
    refs = {c.ref for c in truth.components}
    raw = {tuple(p) for net in pred.nets for p in net.pins if not unnumbered(p[1])}
    extra = sorted(p for p in raw if p[0] in refs and aligned.aliases.get(p, p) not in true_pins)
    return {
        "wrong_pins": wrong,
        "extra_raw_identities": extra,
        "unsupported_references": sorted({c.ref for c in pred.components} - refs),
        "numbered_pins_on_unsupported_references": sorted(p for p in raw if p[0] not in refs),
        "true_nets": [sorted(n) for n in aligned.true_nets],
        "aligned_pred_nets": [sorted(n) for n in aligned.pred_nets],
        "match": aligned.match,
        "aliases": [[p, q] for p, q in sorted(aligned.aliases.items())],
    }


def summarize(root):
    from schem2net import kicad
    from schem2net.bench.score import Counts, compare, intervals, score, summary
    from schem2net.ir import Design

    panel = json.loads((root / "panel.json").read_text())
    records, all_counts = [], {}
    for mode in ("primary", "library"):
        all_counts[mode] = {}
        for version in ("initial", "recent", "candidate"):
            counts = []
            for row in panel:
                out = root / "predictions" / mode / version / row["name"]
                truth = kicad.read_netlist(root / row["truth"])
                process = json.loads(out.with_suffix(".process.json").read_text())
                failed = process["exit"] != 0
                pred = (
                    Design(source=truth.source)
                    if failed
                    else Design.load(out.with_suffix(".prediction.json"))
                )
                count = score(pred, truth)
                counts.append(count)
                evidence = diagnostics(pred, truth)
                # Derived artifacts can be rebuilt without extracting again.
                out.with_suffix(".diagnostics.json").write_text(json.dumps(evidence))
                timing = {} if failed else json.loads(out.with_suffix(".timing.json").read_text())
                records.append(
                    {
                        **{k: row[k] for k in ("name", "group", "generator")},
                        "mode": mode,
                        "version": version,
                        "failure": failed,
                        "empty": not pred.components,
                        "counts": asdict(count),
                        "metrics": count.metrics(),
                        "timing": timing,
                        "unsupported_references": len(evidence["unsupported_references"]),
                        "unknown_ref_pins": len(
                            evidence["numbered_pins_on_unsupported_references"]
                        ),
                    }
                )
            all_counts[mode][version] = counts
    result = {"designs": len(panel), "groups": len({r["group"] for r in panel}), "strata": {}}
    for generator in ["all", *sorted({r["generator"] for r in panel})]:
        indices = [
            i for i, row in enumerate(panel) if generator == "all" or row["generator"] == generator
        ]
        groups = [panel[i]["group"] for i in indices]
        result["strata"][generator] = {}
        for mode, versions in all_counts.items():
            selected = {v: [rows[i] for i in indices] for v, rows in versions.items()}
            item = {
                "designs": len(indices),
                "groups": len(set(groups)),
                "versions": {},
                "comparisons": {},
            }
            for version, counts in selected.items():
                item["versions"][version] = {
                    "counts": asdict(sum(counts, Counts())),
                    "metrics": summary(counts),
                    "intervals": intervals(counts, groups=groups, resamples=2000, seed=0),
                }
            for baseline in ("initial", "recent"):
                item["comparisons"][baseline] = compare(
                    selected[baseline], selected["candidate"], groups=groups, resamples=2000, seed=0
                )
            result["strata"][generator][mode] = item
    (root / "per-design.json").write_text(json.dumps(records, indent=2))
    (root / "results.json").write_text(json.dumps(result, indent=2))
    print(f"Scored {len(panel)} designs in {result['groups']} groups")


if __name__ == "__main__":
    if sys.argv[1] == "worker":
        worker(*sys.argv[2:])
    else:
        {"run": run, "summarize": summarize}[sys.argv[2]](Path(sys.argv[1]).resolve())
