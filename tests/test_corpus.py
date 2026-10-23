import hashlib
import zipfile

import pytest

from schem2net import export
from schem2net.bench.corpus import Corpus, Project, _unzipped
from schem2net.ir import Component, Design, Net, Pin, Source


def test_revisions_copies_and_near_copies_are_split_together(tmp_path, monkeypatch):
    def board(name, repo, nets):
        out = tmp_path / "build" / "x" / name
        out.mkdir(parents=True)
        (out / "schematic.pdf").write_bytes(b"")
        refs = sorted({ref for net in nets for ref, _ in net})
        design = Design(
            source=Source(file="x"),
            components=[Component(ref=r, pins=[Pin(num="1"), Pin(num="2")]) for r in refs],
            nets=[Net(id=str(i), name=f"N{i}", pins=pins) for i, pins in enumerate(nets)],
        )
        (out / "truth.net").write_text(export.kicad_netlist(design))
        return Project(name=name, repo=repo)

    def nets(*refs):
        return [[(r, "1"), (r, "2")] for r in refs]

    many = [f"R{k}" for k in range(20)]
    projects = [
        board("a-rev1", "r/a", nets("R1", "R2")),
        board("a-rev2", "r/a", nets("R1", "R3")),
        board("b", "r/b", nets("R1", "R2")),  # the same nets as a-rev1
        board("c", "r/c", nets(*many)),
        board("d", "r/d", nets(*many[:19], "X1")),  # 19 of its 21 nets as c's
        *[board(f"e{k}", f"r/e{k}", nets(f"E{k}")) for k in range(12)],
    ]
    corpus = Corpus(name="x", root=tmp_path, test_share=0.5, projects=projects)
    split = corpus.split
    assert split(projects[0]) == split(projects[1]) and split(projects[2]) == "copy"
    assert split(projects[3]) == split(projects[4])
    assert corpus.groups["c"] == corpus.groups["d"] != corpus.groups["e0"]
    dev = [p for p in projects if split(p) == "dev"]
    assert len({corpus.fold(p) for p in dev}) > 1
    for p in dev:
        assert all(
            corpus.fold(q) == corpus.fold(p)
            for q in dev
            if corpus.groups[q.name] == corpus.groups[p.name]
        )
    assert sum(corpus.splits[p.name] == "holdout" for p in projects) >= 2
    with pytest.raises(ValueError):
        corpus.in_split(projects[0], "holdout")
    monkeypatch.setenv("SCHEM2NET_HOLDOUT", "1")
    assert any(corpus.in_split(p, "holdout") for p in projects)


def test_a_design_package_is_read_once_and_checked(tmp_path):
    package = tmp_path / "design.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("docs/board.pdf", b"%PDF")
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    project = Project(name="p", zip_url=package.as_uri(), sha256=sha)
    found = _unzipped(project, tmp_path / "cache", "docs/board.pdf")
    assert found.read_bytes() == b"%PDF"
    wrong = Project(name="q", zip_url=package.as_uri(), sha256="0" * 64)
    with pytest.raises(ValueError, match="sha256"):
        _unzipped(wrong, tmp_path / "cache", "docs/board.pdf")


def test_a_corpus_may_be_held_out_whole(tmp_path):
    projects = [Project(name=f"p{k}", repo=f"r/{k}") for k in range(5)]
    held = Corpus(name="x", root=tmp_path, test_share=0.5, projects=projects, holdout_share=1.0)
    assert set(held.splits.values()) == {"holdout"}
