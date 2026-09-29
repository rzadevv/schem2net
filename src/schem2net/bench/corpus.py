"""Benchmark corpora: KiCad projects rendered to (PDF, netlist) pairs.

Manifests list projects by reference only (repo URL and commit, or a demo that
ships with KiCad). Nothing third-party is stored in this repository.
"""

import hashlib
import os
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

IMAGE = "schem2net-kicad:10.0.6"
KICAD_DEMOS = "/usr/share/kicad/demos"
SPARSE_PATTERNS = ["*.kicad_sch", "*.kicad_pro", "*.kicad_sym", "*.kicad_wks", "sym-lib-table"]
EXPORT_PDF = [
    "sch", "export", "pdf", "-o", "/out/schematic.pdf",
    "--exclude-pdf-property-popups", "--exclude-pdf-hierarchical-links",
]  # fmt: skip
EXPORT_NETLIST = ["sch", "export", "netlist", "-o", "/out/truth.net"]


@dataclass(frozen=True)
class Project:
    name: str
    schematic: str  # root sheet, relative to the repo or to the KiCad demos
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
            if project.repo:
                src = _checkout(project, corpus.root / "cache" / project.name)
                mounts = ["-v", f"{src.resolve()}:/src"]
                schematic = f"/src/{project.schematic}"
            else:
                mounts = []
                schematic = f"{KICAD_DEMOS}/{project.schematic}"
            mounts += ["-v", f"{out.resolve()}:/out"]
            _kicad_cli(image, mounts, [*EXPORT_PDF, schematic])
            _kicad_cli(image, mounts, [*EXPORT_NETLIST, schematic])
            log(f"built {project.name}")
        except subprocess.CalledProcessError as e:
            failed.append(project.name)
            log(f"failed {project.name}: {(e.stderr or e.stdout or '').strip()}")
    return failed


def _checkout(project: Project, dest: Path) -> Path:
    if not dest.exists():
        _run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", project.repo, str(dest)])
        _run(["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS])
    _run(["git", "-C", str(dest), "checkout", "--quiet", project.commit])
    return dest


def _kicad_cli(image: str, mounts: list[str], args: list[str]) -> None:
    user = f"{os.getuid()}:{os.getgid()}"
    _run(["docker", "run", "--rm", "--user", user, *mounts, image, *args])


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)
