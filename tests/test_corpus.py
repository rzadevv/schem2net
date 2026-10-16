import pytest

from schem2net import export
from schem2net.bench.corpus import Corpus, Project
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
    assert sum(corpus.splits[p.name] == "holdout" for p in projects) >= 2
    with pytest.raises(ValueError):
        corpus.in_split(projects[0], "holdout")
    monkeypatch.setenv("SCHEM2NET_HOLDOUT", "1")
    assert any(corpus.in_split(p, "holdout") for p in projects)
