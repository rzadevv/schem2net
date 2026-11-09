import json
import os
import subprocess
from dataclasses import replace

import pytest

from schem2net import export
from schem2net.bench.corpus import Corpus, Project
from schem2net.bench.verify import check_sealed, verify
from schem2net.ir import Component, Design, Net, Pin, Source
from tests.conftest import PdfBuilder


def pdf(path, words):
    """A one-page PDF whose text layer holds these words."""
    page = PdfBuilder()
    for i, w in enumerate(words):
        page.text(w, 20, 780 - 12 * i)
    page.save(path)


def truth(path, refs, names=()):
    """A netlist joining pin 1 of each part in pairs, the nets named as given."""
    nets = [
        Net(id=str(k), name=names[k] if k < len(names) else f"N${k}", pins=[(a, "1"), (b, "1")])
        for k, (a, b) in enumerate(zip(refs[::2], refs[1::2], strict=False))
    ]
    design = Design(
        source=Source(file="x"),
        components=[Component(ref=r, pins=[Pin(num="1")]) for r in refs],
        nets=nets,
    )
    path.write_text(export.kicad_netlist(design))


def git(repo, *args, when="2026-01-01T00:00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()  # fmt: skip


def built(bench, name, refs, words, names=()):
    out = bench / "build" / "p" / name
    out.mkdir(parents=True)
    pdf(out / "schematic.pdf", words)
    truth(out / "truth.net", refs, names)
    return out


def corpus(bench, projects, tier="exploratory", holdout_share=0.0):
    return Corpus(
        name="p",
        root=bench,
        test_share=0.0,
        projects=projects,
        holdout_share=holdout_share,
        tier=tier,
    )


def records(bench, projects, refs=(), tier="exploratory", holdout_share=0.0, forks=None):
    projects = [replace(p, group=p.group or p.name) for p in projects]
    found = verify(
        corpus(bench, projects, tier, holdout_share),
        [bench / "build", *refs],
        github=lambda repo: (forks or {}).get(repo),
    )
    return {r["name"]: r for r in found}


REFS = ["R1", "R2", "C1", "C2", "U1", "U2"]


def test_an_export_is_verified_and_hashed(bench):
    built(bench, "ok", REFS, [])
    found = records(bench, [Project(name="ok", license="MIT")])["ok"]
    assert found["decision"] == "verified" and found["evidence"] == "export"
    assert set(found["files"]) == {"pdf", "truth"} and found["generator"] == "kicad"


def test_a_published_pdf_must_print_the_truths_parts_and_names(bench):
    names = ["SDA", "SCL", "D3"]
    built(bench, "good", REFS, [*REFS[:4], "U", "1A", "U2", "SDA", "SCL", "D[0..7]"], names)
    built(bench, "other", REFS, ["R1", "R2", "R7", "R8", "R9", "R11", "C1", "C2"])
    built(bench, "unread", REFS, [])
    projects = [
        Project(name=n, pdf="s.pdf", pcb="b.PcbDoc", license="MIT")
        for n in ("good", "other", "unread")
    ]
    found = records(bench, projects)
    assert found["good"]["decision"] == "verified", found["good"]["reasons"]
    assert found["good"]["text"]["refs_printed"] == 1.0  # U1 printed as "U" "1A"
    assert found["good"]["text"]["names_printed"] == 1.0  # D3 by its bus D[0..7]
    reasons = " ".join(found["other"]["reasons"])
    assert "2 of 6 designators not in the PDF" in reasons
    assert "names 4 parts the truth lacks" in reasons
    assert found["unread"]["evidence"] == "revision only"
    assert found["unread"]["decision"] == "verified"  # exploratory: allowed, but noted
    independent = records(bench, projects[2:], tier="independent", holdout_share=1.0)
    assert independent["unread"]["decision"] == "quarantine"


def test_a_pdf_older_than_its_source_is_quarantined(bench):
    repo = bench / "cache" / "repos" / "me_board"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "board.sch").write_text('<eagle version="9.6.2"><sheet></sheet></eagle>')
    (repo / "board.pdf").write_text("old print")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "draw")
    (repo / "board.sch").write_text('<eagle version="9.6.2"><sheet></sheet>changed</eagle>')
    git(repo, "commit", "-qam", "edit", when="2026-02-01T00:00:00")
    head = git(repo, "rev-parse", "HEAD")
    built(bench, "stale", REFS, REFS)
    project = Project(
        name="stale", repo="https://github.com/me/board", commit=head,
        eagle="board.sch", pdf="board.pdf", license="CERN-OHL-S-2.0",
    )  # fmt: skip
    found = records(bench, [project])["stale"]
    assert "the PDF is older than the source's last change" in found["reasons"]
    assert found["files"]["schematic_file"].startswith("git:")
    assert found["source_version"] == "9.6.2" and found["license_file"] is None


def test_used_sources_copies_and_missing_files_are_kept_out(bench):
    old = bench / "build" / "a" / "old"
    old.mkdir(parents=True)
    truth(old / "truth.net", REFS)
    built(bench, "copy", REFS, [])
    built(bench, "same-owner", ["R5", "R6"], [])
    built(bench, "fork", ["R7", "R8"], [])
    projects = [
        Project(name="copy", license="MIT"),
        Project(name="same-owner", repo="https://github.com/used/new", license="MIT"),
        Project(name="fork", repo="https://github.com/me/fork", license="MIT"),
        Project(name="absent", license="MIT"),
        Project(name="unlicensed", license=None),
    ]
    built(bench, "unlicensed", ["R9", "R10"], [])
    forks = {"https://github.com/me/fork": "https://github.com/used/original"}
    found = records(bench, projects, forks=forks)
    assert "the same design as" in found["copy"]["reasons"][0]
    assert found["same-owner"]["reasons"] == ["owner already in corpus a"]
    assert found["fork"]["reasons"] == ["a fork of https://github.com/used/original, already used"]
    assert found["absent"]["decision"] == "missing"
    assert found["unlicensed"]["reasons"] == ["no licence recorded"]


def test_an_independent_corpus_is_held_out_whole(bench):
    with pytest.raises(ValueError, match="held out whole"):
        records(bench, [], tier="independent")
    with pytest.raises(ValueError, match="tier"):
        records(bench, [], tier="final")


def test_sealed_hashes_catch_changed_inputs_but_not_export_times(bench):
    out = built(bench, "ok", REFS, [])
    text = (out / "truth.net").read_text()
    (out / "truth.net").write_text(text.replace("(design", '(design (date "2026-11-09T22:54:18")'))
    project = Project(name="ok", license="MIT")
    sealed = json.loads(json.dumps(list(records(bench, [project]).values())))
    (out / "truth.net").write_text(text.replace("(design", '(design (date "2026-11-10T08:00:00")'))
    assert check_sealed(list(records(bench, [project]).values()), sealed) == []
    truth(out / "truth.net", [*REFS, "R3", "R4"])
    changed = check_sealed(list(records(bench, [project]).values()), sealed)
    assert changed == ["ok: truth changed"]
    assert check_sealed([], sealed) == ["ok: no longer built"]


def test_a_rendering_must_have_its_designs_netlist(bench):
    built(bench, "base", REFS, [])
    built(bench, "bw", REFS, [])
    built(bench, "v7", REFS[:4], [])
    projects = [
        Project(name="base", repo="https://github.com/me/x", license="MIT"),
        Project(
            name="bw",
            repo="https://github.com/me/x",
            license="MIT",
            export=["-b"],
            variant_of="base",
        ),
        Project(
            name="v7",
            repo="https://github.com/me/x",
            license="MIT",
            image="schem2net-kicad:7.0",
            variant_of="base",
        ),
    ]
    found = records(bench, projects)
    assert found["bw"]["decision"] == "verified"
    assert found["bw"]["export"]["options"] == ["-b"]
    assert found["v7"]["reasons"] == ["its netlist differs from base's"]
    loaded = corpus(bench, projects)
    assert loaded.split(projects[1]) == loaded.split(projects[0]) != "copy"
    assert loaded.groups["bw"] == loaded.groups["base"]
