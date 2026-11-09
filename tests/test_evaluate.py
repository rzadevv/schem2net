import json

import pytest

from schem2net import kicad
from schem2net.bench import evaluate
from schem2net.bench.corpus import Project
from tests.test_verify import REFS, built, corpus, records


def test_only_verified_unchanged_designs_are_scored(bench):
    out = built(bench, "ok", REFS, [])
    built(bench, "copy", ["C5", "C6"], [])  # quarantined below
    projects = [Project(name=n, group=n, license="MIT") for n in ("ok", "copy", "failed")]
    built(bench, "failed", ["R1", "R9"], [])
    loaded = corpus(bench, projects)
    with pytest.raises(ValueError, match="verify-corpus"):
        evaluate.admitted(loaded)
    found = records(bench, projects)
    found["copy"]["decision"] = "quarantine"
    (bench / "verified_p.json").write_text(json.dumps(list(found.values())))
    assert [p.name for p in evaluate.admitted(loaded)] == ["failed", "ok"]

    preds = bench / "out"
    preds.mkdir()
    (preds / "run.json").write_text("{}")
    perfect = kicad.read_netlist(out / "truth.net")
    perfect.save(preds / "ok.prediction.json")
    evaluate._write(preds / "ok.timing.json", {"seconds": 1.0, "peak_rss_mb": 100})
    with pytest.raises(FileExistsError):
        evaluate._write(preds / "ok.timing.json", {})
    with pytest.raises(ValueError, match="failed has not been read"):
        evaluate.report(loaded, preds)
    evaluate._write(preds / "failed.failed.json", {"error": "MemoryError"})
    report = evaluate.report(loaded, preds)
    assert report["designs"]["ok"]["pins_correct"] == report["designs"]["ok"]["pins"] == 6
    assert report["designs"]["failed"]["pins_correct"] == 0
    assert report["extra"]["ok"]["merges"] == 0 and report["extra"]["failed"]["failed"]
    assert report["by_generator"]["kicad"] == {
        **report["by_generator"]["kicad"],
        "designs": 2,
        "groups": 2,
        "failed": 1,
    }

    (out / "truth.net").write_text((out / "truth.net").read_text().replace("R1", "R7"))
    with pytest.raises(ValueError, match="ok: truth changed since it was verified"):
        evaluate.admitted(loaded)
