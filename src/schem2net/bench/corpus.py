"""Benchmark corpora: schematic PDFs paired with their true netlists.

A project is either a KiCad schematic, rendered to a PDF and a netlist with
kicad-cli, a published PDF paired with the board file it was made with, whose
pads give the netlist, or a published PDF of an Eagle schematic, whose .sch
gives the netlist. Manifests list projects by reference only (repo
URL and commit, or a demo that ships with KiCad). Nothing third-party is
stored in this repository.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from schem2net import bookmarks, eagle, easyeda, export, kicad
from schem2net.bench.score import score

IMAGE = "schem2net-kicad:10.0.6"
KICAD_DEMOS = "/usr/share/kicad/demos"
SPARSE_PATTERNS = ["*.kicad_sch", "*.kicad_pro", "*.kicad_sym", "*.kicad_wks", "sym-lib-table"]
EXPORT_PDF = [
    "sch", "export", "pdf", "-o", "/out/schematic.pdf",
    "--exclude-pdf-property-popups", "--exclude-pdf-hierarchical-links",
]  # fmt: skip
EXPORT_NETLIST = ["sch", "export", "netlist", "-o", "/out/truth.net"]
PCB_NETLIST = Path(__file__).with_name("pcb_netlist.py")


@dataclass(frozen=True)
class Project:
    name: str
    schematic: str | None = None  # KiCad root sheet, in the repo or the KiCad demos
    pdf: str | None = None  # a published schematic PDF, in the repo
    pcb: str | None = None  # the board file the PDF belongs to
    eagle: str | None = None  # an Eagle schematic in the repo
    easyeda: str | None = None  # an EasyEDA (Std) schematic in the repo
    pdf_url: str | None = None  # where its published PDF is
    repo: str | None = None
    commit: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class Corpus:
    name: str
    root: Path  # bench directory
    test_share: float
    projects: list[Project]

    def split(self, project: Project) -> str:
        """Fixed dev/test assignment derived from the project name."""
        digest = hashlib.sha256(project.name.encode()).digest()
        return "test" if digest[0] < 256 * self.test_share else "dev"

    def build_dir(self, project: Project) -> Path:
        return self.root / "build" / self.name / project.name

    def is_built(self, project: Project) -> bool:
        out = self.build_dir(project)
        return (out / "schematic.pdf").exists() and (out / "truth.net").exists()


def load(name: str, root: Path = Path("bench")) -> Corpus:
    data = tomllib.loads((root / f"corpus_{name}.toml").read_text())
    projects = [Project(**p) for p in data["project"]]
    return Corpus(name=name, root=root, test_share=data["test_share"], projects=projects)


def build(corpus: Corpus, image: str = IMAGE, log: Callable[[str], None] = print) -> list[str]:
    """Render every project that is not built yet. Returns the names that failed."""
    failed = []
    for project in corpus.projects:
        if corpus.is_built(project):
            continue
        out = corpus.build_dir(project)
        out.mkdir(parents=True, exist_ok=True)
        try:
            if project.pcb:
                note = _build_from_board(project, corpus.root / "cache" / "repos", out, image)
                log(f"built {project.name}: {note}")
                continue
            if project.eagle or project.easyeda:
                _build_from_eagle(project, corpus.root / "cache" / "repos", out)
                log(f"built {project.name}")
                continue
            if project.repo and project.pdf:  # a published PDF; the schematic gives the truth
                src = _checkout(project, corpus.root / "cache" / project.name)
                shutil.copyfile(src / project.pdf, out / "schematic.pdf")
                mounts = ["-v", f"{src.resolve()}:/src", "-v", f"{out.resolve()}:/out"]
                _docker(image, mounts, [*EXPORT_NETLIST, f"/src/{project.schematic}"])
                log(f"built {project.name}")
                continue
            if project.repo:
                src = _checkout(project, corpus.root / "cache" / project.name)
                mounts = ["-v", f"{src.resolve()}:/src"]
                schematic = f"/src/{project.schematic}"
            else:
                mounts = []
                schematic = f"{KICAD_DEMOS}/{project.schematic}"
            mounts += ["-v", f"{out.resolve()}:/out"]
            _docker(image, mounts, [*EXPORT_PDF, schematic])
            _docker(image, mounts, [*EXPORT_NETLIST, schematic])
            log(f"built {project.name}")
        except subprocess.CalledProcessError as e:
            failed.append(project.name)
            log(f"failed {project.name}: {(e.stderr or e.stdout or '').strip()}")
    return failed


def _build_from_board(project: Project, cache: Path, out: Path, image: str) -> str:
    repo = cache / re.sub(r"[^A-Za-z0-9]+", "_", project.repo.removeprefix("https://github.com/"))
    if not repo.exists():
        _run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", project.repo, str(repo)])
    files = repo.with_name(repo.name + "-files") / project.commit
    pdf, pcb = (_show(repo, project.commit, path, files) for path in (project.pdf, project.pcb))
    shutil.copyfile(pdf, out / "schematic.pdf")
    mounts = ["-v", f"{pcb.parent.resolve()}:/w", "-v", f"{out.resolve()}:/out"]
    mounts += ["-v", f"{PCB_NETLIST.parent.resolve()}:/tools:ro", "--entrypoint", "python3"]
    _docker(image, mounts, [f"/tools/{PCB_NETLIST.name}", f"/w/{pcb.name}", "/out/board.net"])
    return _choose_truth(out)


def _build_from_eagle(project: Project, cache: Path, out: Path) -> None:
    """An Eagle or EasyEDA schematic in a repository, with its published PDF."""
    repo = cache / re.sub(r"[^A-Za-z0-9]+", "_", project.repo.removeprefix("https://github.com/"))
    if not repo.exists():
        _run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", project.repo, str(repo)])
    files = repo.with_name(repo.name + "-files") / project.commit
    source = _show(repo, project.commit, project.eagle or project.easyeda, files)
    shutil.copyfile(source, out / ("schematic.sch" if project.eagle else "schematic.json"))
    if project.pdf:  # exported next to the schematic, in the same commit
        shutil.copyfile(_show(repo, project.commit, project.pdf, files), out / "schematic.pdf")
    else:
        request = urllib.request.Request(project.pdf_url, headers={"User-Agent": "schem2net"})
        with urllib.request.urlopen(request, timeout=120) as response:
            (out / "schematic.pdf").write_bytes(response.read())
    truth = eagle.read(source) if project.eagle else easyeda.read(source)
    (out / "truth.net").write_text(export.kicad_netlist(truth))


def _choose_truth(out: Path) -> str:
    """Prefer the netlist the PDF carries, which is the schematic's own; else the board's.

    The board can drift from the drawing between revisions, so it is only a
    cross-check when the PDF has its own netlist. Returns how the two agree.
    """
    board = kicad.read_netlist(out / "board.net")
    carried = bookmarks.read(out / "schematic.pdf", board.source)
    if carried is None:
        shutil.copyfile(out / "board.net", out / "truth.net")
        return "truth from the board"
    (out / "truth.net").write_text(export.kicad_netlist(carried))
    agreement = score(carried, board).metrics()["pin_accuracy"]
    return f"truth from the PDF's netlist, board agrees on {agreement:.0%} of pins"


def _show(repo: Path, commit: str, path: str, dest: Path) -> Path:
    """Write one file of a commit, fetching only that file."""
    out = dest / path
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{path}"], check=True, capture_output=True
        )
        out.write_bytes(blob.stdout)
    return out


def _checkout(project: Project, dest: Path) -> Path:
    if not dest.exists():
        _run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", project.repo, str(dest)])
        patterns = SPARSE_PATTERNS + ([project.pdf] if project.pdf else [])
        _run(["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *patterns])
    _run(["git", "-C", str(dest), "checkout", "--quiet", project.commit])
    return dest


def _docker(image: str, options: list[str], args: list[str]) -> None:
    user = f"{os.getuid()}:{os.getgid()}"
    _run(["docker", "run", "--rm", "--user", user, *options, image, *args])


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)
