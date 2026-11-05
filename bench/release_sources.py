"""Download pinned public CAD files and export paired inputs; never run the predictor.

Usage: python bench/release_sources.py ROOT download|export
ROOT/selected-sources.json is reviewed before either operation. Third-party
sources and generated PDFs stay in the ignored experiment directory.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from schem2net import kicad, sexpr

IMAGE = "sha256:2b3cd995d544f09ad34f04b34d046c3604b15aa98f43d381adbef50d63c95675"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def download(root, sources):
    def fetch(job):
        source, item = job
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe source path: {relative}")
        dest = root / "sources" / slug(source["name"]) / relative
        if dest.exists():
            data = dest.read_bytes()
        else:
            url = (
                f"https://raw.githubusercontent.com/{source['name']}/"
                f"{source['commit']}/{urllib.parse.quote(item['path'])}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "schem2net-release-check"})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise ValueError("file exceeds download ceiling")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["sha"]:
            raise ValueError(f"Git blob mismatch: {dest}")
        return {
            "repository": source["name"],
            "path": item["path"],
            "blob": blob,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    jobs = [(s, p) for s in sources for p in s["download"]]
    found, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(j, pool.submit(fetch, j)) for j in jobs]
        for job, future in futures:
            try:
                found.append(future.result())
            except Exception as error:
                errors.append(
                    {"repository": job[0]["name"], "path": job[1]["path"], "error": str(error)}
                )
    (root / "downloads.json").write_text(json.dumps({"files": found, "errors": errors}, indent=2))
    print(f"Downloaded and verified {len(found)} files; {len(errors)} errors", flush=True)


def links(path):
    text = path.read_text(errors="replace")
    found = re.findall(r'\(property\s+"Sheet\s*file"\s+"([^"\n]+)"', text, re.I)
    found += re.findall(r'^F1\s+"([^"\n]+\.sch)"', text, re.M | re.I)
    return [(path.parent / name).resolve() for name in found]


def source_refs(path, visited=None):
    visited = set() if visited is None else visited
    if path.resolve() in visited:
        return set()
    visited.add(path.resolve())
    text = path.read_text(errors="replace")
    if text.startswith("(kicad_sch"):
        refs = {
            p[2]
            for node in sexpr.children(sexpr.parse(text), "symbol")
            for p in sexpr.children(node, "property")
            if p[1] == "Reference"
        }
    else:
        refs = set(re.findall(r'^F 0 "([^"\n]+)"', text, re.M))
    for child in links(path):
        refs |= source_refs(child, visited)
    return {r for r in refs if not r.startswith("#")}


def roots(folder):
    sheets, children = [], set()
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in (".sch", ".kicad_sch"):
            continue
        text = path.read_text(errors="replace")
        if not text.startswith(("(kicad_sch", "EESchema Schematic")):
            continue
        sheets.append(path)
        children.update(links(path))
    return [
        p
        for p in sheets
        if p.resolve() not in children
        and not any(
            w in str(p.relative_to(folder)).lower().split("/")
            for w in ("library", "libraries", "template", "templates", "test", "tests")
        )
    ]


def export(root, sources):
    records = []
    for source in sources:
        if source["kind"] != "kicad":
            continue
        folder = (root / "sources" / slug(source["name"])).resolve()
        accepted, circuits = 0, []
        for sheet in roots(folder)[:20]:
            if accepted == 2:
                break
            name = slug(source["name"] + "/" + str(sheet.relative_to(folder)))
            out = (root / "pairs-v2" / name).resolve()
            if out.exists():
                raise FileExistsError(f"refusing to overwrite an export: {out}")
            out.mkdir(parents=True)
            record = {
                "name": name,
                "repository": source["name"],
                "commit": source["commit"],
                "group": source["group"],
                "generator": "kicad",
                "source": str(sheet.relative_to(folder)),
                "source_sha256": digest(sheet),
                "verification": "PDF and netlist exported from identical immutable source",
                "pdf": str((out / "schematic.pdf").relative_to(root.resolve())),
                "truth": str((out / "truth.net").relative_to(root.resolve())),
            }
            options = [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--tmpfs",
                "/tmp:rw,size=256m,mode=1777",
                "-e",
                "HOME=/tmp",
                "-v",
                f"{folder}:/src:ro",
                "-v",
                f"{out}:/out",
                IMAGE,
            ]
            path = "/src/" + str(sheet.relative_to(folder))
            commands = [
                options
                + [
                    "sch",
                    "export",
                    "pdf",
                    "-o",
                    "/out/schematic.pdf",
                    "--exclude-pdf-property-popups",
                    "--exclude-pdf-hierarchical-links",
                    path,
                ],
                options + ["sch", "export", "netlist", "-o", "/out/truth.net", path],
            ]
            logs = []
            try:
                for cmd in commands:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    logs.append(
                        {
                            "command": cmd,
                            "exit": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    )
                    result.check_returncode()
                    if re.search(
                        r"(symbol.*not found|failed to load|unable to load|missing sheet)",
                        result.stdout + result.stderr,
                        re.I,
                    ):
                        raise ValueError("incomplete source export; see log")
                truth = kicad.read_netlist(out / "truth.net")
                expected = source_refs(sheet)
                missing = expected - {c.ref for c in truth.components}
                if missing:
                    raise ValueError(f"source references absent from truth: {sorted(missing)}")
                nets = frozenset(frozenset(n.pins) for n in truth.nets if len(set(n.pins)) >= 2)
                if not nets:
                    raise ValueError("no connected truth nets")
                if any(len(nets & old) / len(nets | old) >= 0.9 for old in circuits):
                    raise ValueError("duplicate or near-identical revision")
                circuits.append(nets)
                record.update(
                    decision="verified",
                    pdf_sha256=digest(out / "schematic.pdf"),
                    truth_sha256=digest(out / "truth.net"),
                    components=len(truth.components),
                    connected_nets=len(nets),
                    connected_pins=sum(map(len, nets)),
                )
                accepted += 1
            except (subprocess.SubprocessError, ValueError, OSError) as error:
                record.update(decision="quarantine", reason=str(error))
            (out / "export.json").write_text(json.dumps(logs, indent=2))
            records.append(record)
            (root / "pairing-v2.json").write_text(json.dumps(records, indent=2))
            print(
                source["name"],
                sheet.relative_to(folder),
                record["decision"],
                record.get("reason", ""),
                flush=True,
            )


if __name__ == "__main__":
    base = Path(sys.argv[1]).resolve()
    selected = json.loads((base / "selected-sources.json").read_text())
    {"download": download, "export": export}[sys.argv[2]](base, selected)
