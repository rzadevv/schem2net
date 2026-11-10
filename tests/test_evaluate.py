import hashlib
import json
import subprocess
from dataclasses import replace

import pytest

from schem2net import kicad
from schem2net.bench import evaluate
from schem2net.bench.corpus import Project
from schem2net.bench.verify import content_sha
from tests.test_verify import REFS, built, corpus, seal


def reading(out, prediction):
    seal = out.parents[2] / "verified_p.json"  # bench/build/p/<name>
    return {
        "pdf": content_sha(out / "schematic.pdf"),
        "seal": hashlib.sha256(seal.read_bytes()).hexdigest(),
        "stats": {"seconds": 1.0, "peak_rss_mb": 100},
        "prediction": prediction.model_dump(mode="json", by_alias=True),
    }


@pytest.fixture
def pilot(bench):
    out = built(bench, "ok", REFS, [])
    built(bench, "copy", ["C5", "C6"], [])  # quarantined below
    built(bench, "failed", ["R1", "R9"], [])
    projects = [Project(name=n, group=n, license="MIT") for n in ("ok", "copy", "failed")]
    loaded = corpus(bench, projects)
    with pytest.raises(ValueError, match="verify-corpus"):
        evaluate.admitted(loaded)
    found = seal(bench, projects)
    for r in found["designs"]:
        if r["name"] == "copy":
            r["decision"] = "quarantine"
    (bench / "verified_p.json").write_text(json.dumps(found))
    return loaded, out


def test_only_verified_unchanged_designs_are_scored(pilot, tmp_path):
    loaded, out = pilot
    assert [p.name for p in evaluate.admitted(loaded)] == ["failed", "ok"]
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "run.json").write_text(json.dumps({"seal": evaluate._seal(loaded)}))
    evaluate._write(preds / "ok.json", reading(out, kicad.read_netlist(out / "truth.net")))
    with pytest.raises(FileExistsError):
        evaluate._write(preds / "ok.json", {})
    assert sorted(p.name for p in preds.iterdir()) == ["ok.json", "run.json"]  # no part left
    with pytest.raises(ValueError, match="failed has not been read"):
        evaluate.report(loaded, preds)
    failed = loaded.build_dir(loaded.projects[2]) / "schematic.pdf"
    evaluate._write(
        preds / "failed.failed.json",
        {"pdf": "0" * 64, "seal": evaluate._seal(loaded), "error": "MemoryError"},
    )
    with pytest.raises(ValueError, match="failed failed on another PDF"):
        evaluate.report(loaded, preds)
    (preds / "failed.failed.json").unlink()
    evaluate._write(
        preds / "failed.failed.json",
        {"pdf": content_sha(failed), "seal": evaluate._seal(loaded), "error": "MemoryError"},
    )
    report = evaluate.report(loaded, preds)
    assert report["designs"]["ok"]["pins_correct"] == report["designs"]["ok"]["pins"] == 6
    assert report["designs"]["failed"]["pins_correct"] == 0
    assert report["extra"]["ok"]["merges"] == 0 and report["extra"]["failed"]["failed"]
    assert report["size"] == {"designs": 2, "groups": 2}

    (out / "schematic.pdf").write_bytes((out / "schematic.pdf").read_bytes() + b"\n")
    record = json.loads((loaded.root / "verified_p.json").read_text())
    for r in record["designs"]:
        if r["name"] == "ok":
            r["files"]["pdf"] = content_sha(out / "schematic.pdf")  # resealed
    (loaded.root / "verified_p.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="read under another seal"):  # resealing voids readings
        evaluate.report(loaded, preds)
    (preds / "run.json").unlink()
    (preds / "run.json").write_text(json.dumps({"seal": evaluate._seal(loaded)}))
    with pytest.raises(ValueError, match="under another seal"):  # each reading
        evaluate.report(loaded, preds)  # keeps its seal: a fresh run.json changes nothing
    (out / "truth.net").write_text((out / "truth.net").read_text().replace("R1", "R7"))
    with pytest.raises(ValueError, match="ok: truth changed since it was verified"):
        evaluate.admitted(loaded)


def test_a_reading_that_dies_is_recorded_once(pilot, tmp_path, monkeypatch):
    loaded, _ = pilot
    run = subprocess.run
    calls = []

    def fake(cmd, **kwargs):
        if "--environment" in cmd:
            return run(cmd, **kwargs)
        calls.append(cmd)  # killed without a word, as a segfault is
        return subprocess.CompletedProcess(cmd, -11, "", "")

    monkeypatch.setattr(evaluate.subprocess, "run", fake)
    preds = tmp_path / "preds"
    evaluate.extract(loaded, preds)
    assert len(calls) == 2
    assert json.loads((preds / "ok.failed.json").read_text())["error"] == "exit -11"
    evaluate.extract(loaded, preds)  # read again: nothing left to read
    assert len(calls) == 2

    run_json = preds / "run.json"
    record = json.loads(run_json.read_text())
    run_json.unlink()
    run_json.write_text(json.dumps({**record, "fonts": {"count": 1049, "sha256": "x"}}))
    with pytest.raises(ValueError, match="platform or seal"):  # another machine's fonts
        evaluate.extract(loaded, preds)
    run_json.unlink()
    run_json.write_text(json.dumps({**record, "seal": "0" * 64}))
    with pytest.raises(ValueError, match="platform or seal"):  # read under an older seal
        evaluate.extract(loaded, preds)


def test_a_corpus_that_drifted_from_its_seal_is_not_scored(pilot):
    loaded, _ = pilot
    assert len(evaluate.admitted(loaded)) == 2  # unchanged
    p = loaded.projects
    changes = {
        "added": [*p, replace(p[0], name="extra")],
        "removed": p[:2],
        "moved": [replace(p[0], commit="b" * 40), *p[1:]],
        "regrouped": [replace(p[0], group="copy"), *p[1:]],
    }
    for projects in changes.values():
        with pytest.raises(ValueError, match="does not seal this corpus"):
            evaluate.admitted(replace(loaded, projects=projects))
    with pytest.raises(ValueError, match="settings: tier changed"):
        evaluate.admitted(replace(loaded, tier="development"))


def test_observable_pins_leave_out_parts_no_drawing_names(pilot, tmp_path):
    loaded, out = pilot
    path = loaded.root / "verified_p.json"
    sealed = json.loads(path.read_text())
    for r in sealed["designs"]:
        if r["name"] == "ok":
            r["text"] = {"refs_unprinted": ["U1"], "refs_channel": ["U2"]}
    path.write_text(json.dumps(sealed))
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "run.json").write_text(json.dumps({"seal": evaluate._seal(loaded)}))
    evaluate._write(preds / "ok.json", reading(out, kicad.read_netlist(out / "truth.net")))
    evaluate._write(
        preds / "failed.failed.json", {"pdf": "x", "seal": evaluate._seal(loaded), "error": "x"}
    )
    with pytest.raises(ValueError):  # the failure is tied to another PDF
        evaluate.report(loaded, preds)
    (preds / "failed.failed.json").unlink()
    failed = loaded.build_dir(loaded.projects[2]) / "schematic.pdf"
    evaluate._write(
        preds / "failed.failed.json",
        {"pdf": content_sha(failed), "seal": evaluate._seal(loaded), "error": "x"},
    )
    report = evaluate.report(loaded, preds)
    assert report["designs"]["ok"]["pins"] == 6  # strict: every true pin
    assert report["observable_designs"]["ok"]["pins"] == 4  # without U1 and U2
    assert report["extra"]["ok"]["unprinted_pins"] == 1


def test_renderings_are_reported_beside_their_design_never_counted(bench, tmp_path):
    outs = {n: built(bench, n, REFS, []) for n in ("board", "board-bw")}
    projects = [
        Project(name="board", group="board", license="MIT"),
        Project(name="board-bw", group="board", license="MIT", variant_of="board"),
    ]
    loaded = corpus(bench, projects)
    (bench / "verified_p.json").write_text(json.dumps(seal(bench, projects)))
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "run.json").write_text(json.dumps({"seal": evaluate._seal(loaded)}))
    for name, out in outs.items():
        evaluate._write(preds / f"{name}.json", reading(out, kicad.read_netlist(out / "truth.net")))
    report = evaluate.report(loaded, preds)
    assert report["size"] == {"designs": 1, "groups": 1}
    assert list(report["designs"]) == ["board"] and list(report["rendering_counts"]) == ["board-bw"]
    assert report["renderings"] == {"board": {"board": 1.0, "board-bw": 1.0}}
    assert report["by_generator"]["kicad"]["designs"] == 1
