"""Admit a built design only on evidence that its PDF, source and truth are one design.

Nothing here reads the extractor's output, so eligibility cannot favour designs it reads
well: the evidence is the source, the truth netlist, the PDF's own text layer and
metadata, and the repository's history. See docs/benchmark.md, "Verifying a corpus".
"""

import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pypdfium2 as pdfium

from schem2net import kicad
from schem2net.bench import corpus as corpora
from schem2net.bench.score import score
from schem2net.refdes import split_ref

TIERS = ("exploratory", "development", "independent")
REF_COVERAGE = 0.95  # of the truth's designators, printed in the PDF's text
EXTRA_REFS = 0.05  # designators printed that the truth lacks, beyond 3
NAME_COVERAGE = 0.8  # of the truth's chosen net names, printed
# Names a tool makes up for an unnamed net: KiCad, Eagle, Altium, OrCAD, EasyEDA.
AUTO_NAME = re.compile(r"^(Net-\(|unconnected-\(|N\$\d+$|Net[A-Z]+\w*_\w+$|N\d{3,}$|\$)")
TOKEN = re.compile(r"[^\s,;:(){}<>\"']+")


def verify(corpus: corpora.Corpus, references: list[Path], github=None) -> list[dict]:
    """A record for each project of the corpus: what it is, its files' hashes, the
    evidence that its PDF and truth are one design, and whether it is admitted."""
    tier = corpus.tier
    if tier not in TIERS:
        raise ValueError(f"tier {tier!r} is not one of {', '.join(TIERS)}")
    if tier == "independent" and corpus.holdout_share != 1.0:
        raise ValueError("an independent corpus is held out whole: holdout_share = 1.0")
    seen = ledger(corpus.root, corpus.name)
    others = {
        str(out): nets
        for out, nets in reference_nets(references).items()
        if corpus.root / "build" / corpus.name not in out.parents
    }
    return [
        _check(corpus, p, seen, others, github or _fork_of)
        for p in sorted(corpus.projects, key=lambda p: p.name)
    ]


def ledger(root: Path, own: str) -> dict[str, str]:
    """Repositories already used, as normalised URLs, with where: every other corpus
    manifest and the November 5 panel."""
    found = {}
    for path in sorted(root.glob("corpus_*.toml")):
        name = path.stem.removeprefix("corpus_")
        if name == own:
            continue
        for p in tomllib.loads(path.read_text())["project"]:
            for key in ("repo", "zip_url", "pdf_url"):
                if p.get(key):
                    found.setdefault(_normal(p[key]), f"corpus {name}")
    panel = root / "release-2026-11-05-panel.json"
    if panel.exists():
        for row in json.loads(panel.read_text()):
            found.setdefault(_normal("https://github.com/" + row["repository"]), "Nov 5 panel")
    return found


def reference_nets(dirs: list[Path]) -> dict[Path, frozenset]:
    """The true nets of every built design under these folders."""
    return {
        truth.parent: corpora._true_nets(truth.parent)
        for d in dirs
        for truth in sorted(d.rglob("truth.net"))
    }


def check_sealed(records: list[dict], sealed: list[dict]) -> list[str]:
    """Inputs that changed since the corpus was sealed."""
    before = {r["name"]: r.get("files", {}) for r in sealed}
    return [
        f"{r['name']}: {label} changed"
        for r in records
        for label, digest in r.get("files", {}).items()
        if r["name"] in before and before[r["name"]].get(label, digest) != digest
    ] + [f"{name}: no longer built" for name in before.keys() - {r["name"] for r in records}]


def _check(corpus, project, seen, others, fork_of) -> dict:
    out = corpus.build_dir(project)
    record = {
        "name": project.name,
        "tier": corpus.tier,
        "generator": generator(project),
        "group": corpus.groups.get(project.name) if corpus.is_built(project) else None,
        "repo": project.repo or project.zip_url,
        "commit": project.commit,
        "license": project.license,
    }
    blocking, notes = [], []
    record["reasons"], record["notes"] = blocking, notes
    if not corpus.is_built(project):
        blocking.append("not built: no schematic.pdf or truth.net")
        record["decision"] = "missing"
        return record

    files = {"pdf": content_sha(out / "schematic.pdf"), "truth": content_sha(out / "truth.net")}
    if (out / "board.net").exists():
        files["board"] = content_sha(out / "board.net")
    clone = _clone(corpus, project)
    for label, path in _sources(project).items():
        files[label] = _blob(clone, project.commit, path) if clone else None
    record["files"] = files

    _lineage(project, seen, fork_of, record, blocking, notes)
    truth = kicad.read_netlist(out / "truth.net")
    nets = corpora._true_nets(out)
    if not nets:
        blocking.append("the truth has no connected nets")
    near = max(((corpora._jaccard(nets, n), k) for k, n in others.items()), default=(0.0, None))
    record["closest"] = {"design": near[1], "shared_nets": round(near[0], 3)}
    if near[0] >= corpora.SAME_DESIGN:
        blocking.append(f"the same design as {near[1]} ({near[0]:.0%} of nets)")

    if not project.license:
        blocking.append("no licence recorded")
    elif project.license.lower() in ("none", "noassertion"):
        notes.append("no licence: score locally, never redistribute")
    if clone and project.license:
        record["license_file"] = _license_file(clone, project.commit)

    doc = pdfium.PdfDocument(out / "schematic.pdf")
    try:
        meta = doc.get_metadata_dict(skip_empty=True)
        text = " ".join(page.get_textpage().get_text_range() for page in doc)
        pages = len(doc)
    finally:
        doc.close()
    record["pdf"] = {
        "producer": meta.get("Producer"),
        "creator": meta.get("Creator"),
        "created": meta.get("CreationDate"),
        "pages": pages,
    }
    record["source_version"] = _version(clone, project)
    sheets = _sheets(out)
    record["sheets"] = sheets
    if sheets and pages < sheets:
        blocking.append(f"the PDF has {pages} pages for {sheets} sheets")

    tokens = TOKEN.findall(text)
    record["evidence"] = _evidence(project, out, truth, tokens, clone, record, blocking, notes)
    if corpus.tier == "independent" and record["evidence"] == "revision only":
        blocking.append("no text layer to check the PDF against its truth")
    record["decision"] = "quarantine" if blocking else "verified"
    return record


def _evidence(project, out, truth, tokens, clone, record, blocking, notes) -> str:
    """How the PDF is known to show the truth's design: exported from the source with
    it, carrying the schematic's own netlist, or agreeing in printed text."""
    carried = (out / "board.net").exists() and content_sha(out / "truth.net") != content_sha(
        out / "board.net"
    )
    if carried:
        board = kicad.read_netlist(out / "board.net")
        agree = score(truth, board).metrics()["pin_accuracy"] or 0.0
        record["board_agreement"] = round(agree, 3)
        notes.append("the PDF carries its netlist: read it drawing-only")
    elif project.pcb:
        notes.append("truth from the board, which can drift from the drawing")
    if not project.pdf and not project.pdf_url and not project.pcb:
        record["export"] = {"image": corpora.IMAGE, "pdf": corpora.EXPORT_PDF[3:]}
        return "export"

    if clone and project.pdf:
        changed = {
            label: _last_change(clone, project.commit, path)
            for label, path in _sources(project).items()
        }
        record["last_changed"] = changed
        pdf_time = changed.get("pdf_file")
        if pdf_time and any(t and t > pdf_time for k, t in changed.items() if k != "pdf_file"):
            blocking.append("the PDF is older than the source's last change")

    refs = {c.ref for c in truth.components if not c.ref.startswith("#")}
    printed, spent = _joined(tokens, refs)
    if not (printed & refs) and len(tokens) < 3 * max(len(refs), 1):
        notes.append("the PDF has no usable text layer")
        return "carried netlist" if carried else "revision only"

    found = refs & (printed | {_base(t) for t in printed})
    prefixes = {m.group(1) for r in refs if (m := split_ref(r))}
    extra = sorted(
        {
            t
            for i, t in enumerate(tokens)
            if i not in spent
            and _base(t) not in refs
            and (m := split_ref(t))
            and m.group(1) in prefixes
            and not m.group(3)
        }
    )
    names = {_short(n.name) for n in truth.nets if n.name and not AUTO_NAME.match(_short(n.name))}
    buses = {t.split("[", 1)[0] for t in printed if "[" in t}
    named = {n for n in names if n in printed or n.rstrip("0123456789") in buses - {""}}
    record["text"] = {
        "refs": len(refs),
        "refs_printed": round(len(found) / len(refs), 3) if refs else None,
        "refs_missing": sorted(refs - found)[:20],
        "refs_extra": extra[:20],
        "names": len(names),
        "names_printed": round(len(named) / len(names), 3) if names else None,
    }
    if refs and len(found) < REF_COVERAGE * len(refs):
        blocking.append(f"{len(refs) - len(found)} of {len(refs)} designators not in the PDF")
    if len(extra) > max(3, EXTRA_REFS * len(refs)):
        blocking.append(f"the PDF names {len(extra)} parts the truth lacks")
    if names and len(named) < NAME_COVERAGE * len(names):
        blocking.append(f"{len(names) - len(named)} of {len(names)} net names not in the PDF")
    return "carried netlist" if carried else "text"


def _lineage(project, seen, fork_of, record, blocking, notes) -> None:
    """Not a repository, owner or fork parent an earlier set used."""
    if not project.repo:
        return
    repo = _normal(project.repo)
    owners = {_owner(r): where for r, where in seen.items() if _owner(r)}
    if repo in seen:
        blocking.append(f"repository already in {seen[repo]}")
    elif _owner(repo) in owners:
        blocking.append(f"owner already in {owners[_owner(repo)]}")
    parent = fork_of(repo)
    record["fork_of"] = parent
    if parent == "unchecked":
        notes.append("fork status unchecked")
        if record["tier"] == "independent":
            blocking.append("fork status unchecked")
    elif parent and (_normal(parent) in seen or _owner(_normal(parent)) in owners):
        blocking.append(f"a fork of {parent}, already used")


def generator(project) -> str:
    if project.eagle:
        return "eagle"
    if project.easyeda:
        return "easyeda"
    if project.pcb:
        return "orcad" if project.pcb.lower().endswith(".brd") else "altium"
    return "kicad"


def _sources(project) -> dict[str, str]:
    """Repository files the design comes from, by label."""
    found = {
        "schematic_file": project.schematic or project.eagle or project.easyeda,
        "pdf_file": project.pdf if project.repo else None,
        "pcb_file": project.pcb if project.repo else None,
    }
    return {k: v for k, v in found.items() if v}


def _sheets(out: Path) -> int | None:
    """Sheets the truth says the design has, where its format says."""
    if (out / "schematic.sch").exists():
        return len(re.findall(r"<sheet>", (out / "schematic.sch").read_text(errors="replace")))
    found = re.findall(r"\(sheet \(number ", (out / "truth.net").read_text(errors="replace"))
    return len(found) or None


def _version(clone, project) -> str | None:
    path = project.schematic or project.eagle or project.easyeda
    if not (clone and path):
        return None
    head = _git(clone, "show", f"{project.commit}:{path}")[:200_000]
    for pattern in (
        r'\(generator_version "([^"]+)"',
        r"\(version (\d+)\)",
        r'<eagle version="([^"]+)"',
        r'"editorVersion"\s*:\s*"([^"]+)"',
    ):
        if m := re.search(pattern, head):
            return m.group(1)
    return None


def _license_file(clone, commit) -> dict | None:
    names = _git(clone, "ls-tree", "--name-only", commit).split()
    for name in names:
        if re.match(r"(licen[cs]e|copying)", name, re.I):
            return {"path": name, "blob": _blob(clone, commit, name)}
    return None


def _fork_of(repo: str) -> str | None:
    """The repository a GitHub repository was forked from, "unchecked" if unknown."""
    if not repo.startswith("https://github.com/"):
        return None
    name = repo.removeprefix("https://github.com/")
    try:
        found = subprocess.run(
            ["gh", "api", f"repos/{name}", "--jq", "[.fork, .source.html_url // null]"],
            check=True, capture_output=True, text=True, timeout=60,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return "unchecked"
    fork, source = json.loads(found.stdout)
    return source if fork else None


def _clone(corpus, project) -> Path | None:
    if not project.repo:
        return None
    slug = re.sub(r"[^A-Za-z0-9]+", "_", project.repo.removeprefix("https://github.com/"))
    for d in (corpus.root / "cache" / project.name, corpus.root / "cache" / "repos" / slug):
        if (d / ".git").exists():
            return d
    return None


def _blob(clone: Path, commit: str, path: str) -> str:
    return "git:" + _git(clone, "rev-parse", f"{commit}:{path}").strip()


def _last_change(clone: Path, commit: str, path: str) -> int | None:
    found = _git(clone, "log", "-1", "--format=%ct", commit, "--", path).strip()
    return int(found) if found else None


def _git(clone: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(clone), *args], check=True, capture_output=True, text=True,
        errors="replace",
    ).stdout  # fmt: skip


def content_sha(path: Path) -> str:
    """Of the file's content, without the export time KiCad writes into PDFs and
    netlists, so a design exported twice from one source hashes alike."""
    data = re.sub(rb"(/(?:CreationDate|ModDate)\s*)\([^)]*\)", rb"\1()", path.read_bytes())
    return hashlib.sha256(re.sub(rb'\(date "[^"]*"\)', b'(date "")', data)).hexdigest()


def _normal(url: str) -> str:
    return url.lower().rstrip("/").removesuffix(".git")


def _owner(url: str) -> str | None:
    parts = url.split("/")
    return (
        "/".join(parts[2:4]) if url.startswith("https://github.com/") and len(parts) > 4 else None
    )


def _short(name: str) -> str:
    """A net name as printed: KiCad's sheet path dropped."""
    return name.rsplit("/", 1)[-1]


def _base(token: str) -> str:
    """A designator without the unit printed after it: U1 of U1A, IC2 of IC2G$1."""
    m = split_ref(token)
    return m.group(1) + m.group(2) if m else token


def _joined(tokens: list[str], refs: set[str]) -> tuple[set[str], set[int]]:
    """The printed words, with runs of up to three short neighbours joined, as a PDF
    can store turned text a letter or two at a time ("R1", "0" for R10); and where a
    joined run spells a designator, the positions it took."""
    found, spent = set(tokens), set()
    for i in range(len(tokens)):
        for n in (2, 3):
            run = tokens[i : i + n]
            if len(run) == n and all(len(t) <= 3 for t in run):
                word = "".join(run)
                found.add(word)
                if _base(word) in refs:
                    spent.update(range(i, i + n))
    return found, spent
