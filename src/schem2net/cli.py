import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated

import typer

from schem2net import __version__, kicad_sch, library, pdf, pipeline, report, svg
from schem2net import export as exporters
from schem2net.ir import LOW_CONFIDENCE, Design

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _version(shown: bool) -> None:
    if shown:
        typer.echo(f"schem2net {__version__}")
        raise typer.Exit()


@app.callback()
def _options(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
) -> None:
    """Recover netlists from vector schematic PDFs."""


def main() -> None:
    """The command line, with input it cannot read told in a line rather than a traceback."""
    try:
        app()
    except pdf.InputError as e:
        typer.echo(f"schem2net: {e}", err=True)
        raise SystemExit(1) from None
    except (FileNotFoundError, IsADirectoryError) as e:
        typer.echo(f"schem2net: {e.filename or e}: no such file", err=True)
        raise SystemExit(1) from None


BenchDir = Annotated[Path, typer.Option(help="Directory holding the corpus manifests.")]
RegionOption = Annotated[
    str | None,
    typer.Option(help='Read only part of a page: "PAGE:X0,Y0,X1,Y1" in mm from its top left.'),
]
CorpusName = Annotated[str, typer.Argument(help="Corpus name, e.g. a.")]
LibraryOption = Annotated[
    Path | None,
    typer.Option(
        "--library",
        envvar="SCHEM2NET_LIBRARY",
        help="Folder of part library indexes written by index-library; none is read without.",
    ),
]
StrictOption = Annotated[
    bool, typer.Option(help="Fail, writing nothing, when any page could not be read.")
]


@app.command()
def extract(
    file: Path,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    region: RegionOption = None,
    library_dir: LibraryOption = None,
    strict: StrictOption = False,
) -> None:
    """Extract a netlist from a schematic PDF and write it as JSON."""
    design = pipeline.extract(file, region=_region(region), library_dir=library_dir)
    _refuse(design, strict)
    output = output or file.with_name(_stem(file) + ".ir.json")
    design.save(output)
    typer.echo(f"{output}: {len(design.components)} components, {len(design.nets)} nets")
    _say(design)


class Format(StrEnum):
    kicad_net = "kicad-net"
    bom = "bom"
    spice = "spice"


SUFFIXES = {Format.kicad_net: ".net", Format.bom: ".bom.csv", Format.spice: ".cir"}
WRITERS = {
    Format.kicad_net: exporters.kicad_netlist,
    Format.bom: exporters.bom_csv,
    Format.spice: exporters.spice_netlist,
}


@app.command()
def export(
    file: Annotated[Path, typer.Argument(help="A schematic PDF, or JSON written by extract.")],
    to: Annotated[Format, typer.Option(help="Output format.")] = Format.kicad_net,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    region: RegionOption = None,
    library_dir: LibraryOption = None,
    strict: StrictOption = False,
) -> None:
    """Write a KiCad netlist, a bill of materials or a SPICE netlist."""
    design = _load(file, _region(region), library_dir)
    _refuse(design, strict)
    text = WRITERS[to](design)
    output = output or file.with_name(_stem(file) + SUFFIXES[to])
    _write(output, text)
    typer.echo(output)
    _say(design)


@app.command()
def schematic(
    file: Annotated[Path, typer.Argument(help="A schematic PDF.")],
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Project folder.")] = None,
    library_dir: LibraryOption = None,
    strict: StrictOption = False,
) -> None:
    """Write an editable KiCad project, one sheet per PDF page.

    Parts and wires go where the PDF drew them; the netlist carried in an Altium
    PDF is not used, since it has no drawing to place.
    """
    extraction = pipeline.run(file, embedded=False, library_dir=library_dir)
    _refuse(extraction.design, strict)
    output = output or file.with_name(_stem(file) + "-kicad")
    root = kicad_sch.write(extraction, output, _stem(file))
    typer.echo(root)
    _say(extraction.design)


@app.command("diff")
def diff_(
    old: Annotated[Path, typer.Argument(help="Earlier revision: a PDF or JSON from extract.")],
    new: Annotated[Path, typer.Argument(help="Later revision.")],
    library_dir: LibraryOption = None,
) -> None:
    """List parts added, removed or changed in value, and pins that moved between nets."""
    from schem2net import diff as revisions

    typer.echo(
        revisions.render(
            revisions.diff(_load(old, None, library_dir), _load(new, None, library_dir))
        ),
        nl=False,
    )


def _load(
    file: Path, region: pipeline.Region | None = None, library_dir: Path | None = None
) -> Design:
    if file.suffix.lower() == ".pdf":
        return pipeline.extract(file, region=region, library_dir=library_dir)
    return Design.load(file)


SKIPPED = {"board_page": "a board drawing", "table_page": "a table", "raster_page": "scanned"}


def _refuse(design: Design, strict: bool = False) -> None:
    """Exit with an error, before anything is written, when nothing could be read: an
    earlier output of the same name is left as it was. A PDF of no known tool exits 2;
    one in which no part was found, or with `strict` a page could not be read, exits 3."""
    failed = strict and any(i.kind == "page_failed" for i in design.issues)
    unknown = any(i.kind == "no_profile" for i in design.issues)
    if (not design.components and not unknown) or failed:
        _say(design)
        why = "a page could not be read" if failed else "no part was found on any page"
        typer.echo(f"{design.source.file}: {why}. Nothing was written.", err=True)
        raise typer.Exit(3)
    for issue in design.issues:
        if issue.kind == "no_profile":
            typer.echo(
                f"{design.source.file}: not drawn by a tool schem2net reads (the PDF says: "
                f"{issue.detail}); it reads PDFs from KiCad, Altium, Eagle, EasyEDA and OrCAD. "
                "Nothing was extracted.",
                err=True,
            )
            raise typer.Exit(2)


def _stem(file: Path) -> str:
    """The name to give outputs: board.rev2.pdf and board.rev2.ir.json give board.rev2."""
    for suffix in (".ir.json", ".pdf", ".json"):
        if file.name.lower().endswith(suffix):
            return file.name[: -len(suffix)]
    return file.stem


def _write(path: Path, text: str) -> None:
    """Write the whole file or nothing, so a run that fails leaves an earlier one as it was."""
    part = path.with_name(f".{path.name}.part")
    part.write_text(text)
    os.replace(part, path)


def _say(design: Design) -> None:
    """Tell the reader what could not be read, and what to check."""
    issues = design.issues
    for issue in issues:
        if issue.kind == "generator_guessed":
            typer.echo(
                f"{design.source.file}: the PDF does not say what drew it, and its colours "
                f"are none schem2net knows; read as {issue.detail}, the reading that joined "
                "the most pins. Check it with care.",
                err=True,
            )
    for issue in issues:
        if issue.kind in SKIPPED:
            typer.echo(f"page {issue.page} skipped: {SKIPPED[issue.kind]}", err=True)
        elif issue.kind == "page_failed":
            typer.echo(f"page {issue.page} could not be read ({issue.detail})", err=True)
    # A guessed pad sits on its net as firmly as a printed one: the net's confidence
    # weighs the wiring, not which pad it is, so the guess is told apart.
    guessed = sorted(
        {f"{ref}.{num}" for i in issues if i.kind == "pin_number_guessed" for ref, num in i.pins},
        key=exporters._natural,
    )
    if guessed:
        more = f" and {len(guessed) - 6} more" if len(guessed) > 6 else ""
        some = "1 pad number is" if len(guessed) == 1 else f"{len(guessed)} pad numbers are"
        typer.echo(
            f"{some} not printed but guessed ({', '.join(guessed[:6])}{more}); "
            "exported netlists use them as real pads, so check them before laying out a board.",
            err=True,
        )
    doubtful = [n for n in design.nets if n.confidence < LOW_CONFIDENCE]
    worth = [i for i in issues if i.kind not in SKIPPED]
    if doubtful or worth:
        typer.echo(
            f"{len(doubtful)} doubtful nets and {len(worth)} issues to check; "
            "`schem2net report` shows where.",
            err=True,
        )


def _region(text: str | None) -> pipeline.Region | None:
    if not text:
        return None
    try:
        return pipeline.Region.parse(text)
    except ValueError:
        raise typer.BadParameter(
            f'"{text}": give PAGE:X0,Y0,X1,Y1 in mm, as 2:10,20,150,100', param_hint="--region"
        ) from None


@app.command("report")
def report_(
    file: Path,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    region: RegionOption = None,
    pdf_under: Annotated[
        bool, typer.Option("--pdf/--no-pdf", help="Draw the nets over the pages as printed.")
    ] = True,
    library_dir: LibraryOption = None,
    strict: StrictOption = False,
) -> None:
    """Write an HTML page showing the extracted nets over the schematic."""
    output = output or file.with_name(_stem(file) + ".html")
    extraction = pipeline.run(file, region=_region(region), library_dir=library_dir)
    _refuse(extraction.design, strict)
    pictures = report.pictures(file, extraction) if pdf_under and not region else {}
    _write(output, report.render(extraction, pictures))
    typer.echo(output)
    _say(extraction.design)


@app.command("serve-mcp")
def serve_mcp(
    file: Annotated[Path, typer.Argument(help="A schematic PDF, or JSON written by extract.")],
    library_dir: LibraryOption = None,
) -> None:
    """Serve a design to agents over MCP (stdio)."""
    try:
        from schem2net import mcp_server
    except ImportError:
        typer.echo('The MCP server needs the mcp package: install "schem2net[mcp]"', err=True)
        raise typer.Exit(1) from None
    mcp_server.build(_load(file, None, library_dir)).run()


@app.command()
def draw(
    file: Path,
    page: Annotated[int, typer.Option(help="Page number, starting at 1.")] = 1,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Draw the primitives of one page as SVG."""
    doc = pdf.read(file)
    if not 1 <= page <= len(doc.pages):
        raise typer.BadParameter(f"the PDF has {len(doc.pages)} pages")
    output = output or file.with_name(f"{file.stem}.p{page}.svg")
    output.write_text(svg.render(doc.pages[page - 1]))
    typer.echo(output)


@app.command("index-library")
def index_library(
    folder: Annotated[
        Path, typer.Argument(help="Symbol libraries: KiCad .kicad_sym, Eagle .lbr, or folders.")
    ],
    output: Annotated[Path, typer.Option("-o", "--output", help="Folder to write the indexes to.")],
) -> None:
    """Index part libraries, from which the pins a PDF leaves unnumbered and the pins
    stacked under one drawn pin are numbered. KiCad installs its own, as in
    /usr/share/kicad/symbols, or get https://gitlab.com/kicad/libraries/kicad-symbols;
    Eagle libraries come from the part makers, such as SparkFun's on GitHub. Each kind
    found replaces the index of that kind in the output folder, which extract and the
    other commands then read with --library."""
    found = {"kicad": library.index(folder), "eagle": library.index_eagle(folder)}
    for kind, parts in found.items():
        if parts:
            path = library.path(output, kind)
            library.save(parts, path)
            typer.echo(f"{path}: {sum(len(v) for v in parts.values())} {kind} symbols")
    if not any(found.values()):
        typer.echo(f"no KiCad or Eagle libraries under {folder}", err=True)
        raise typer.Exit(1)


@app.command("build-corpus", hidden=True)
def build_corpus(corpus: CorpusName = "a", bench_dir: BenchDir = Path("bench")) -> None:
    """Render corpus projects to (PDF, netlist) pairs with kicad-cli in Docker."""
    from schem2net.bench import corpus as corpora

    failed = corpora.build(corpora.load(corpus, bench_dir), log=typer.echo)
    if failed:
        typer.echo(f"{len(failed)} projects failed: {', '.join(failed)}", err=True)
        raise typer.Exit(1)


@app.command("verify-corpus", hidden=True)
def verify_corpus(
    corpus: CorpusName,
    bench_dir: BenchDir = Path("bench"),
    against: Annotated[
        list[Path] | None,
        typer.Option(help="More built designs to check for copies; bench/build is always."),
    ] = None,
    seal: Annotated[bool, typer.Option(help="Write the record even if inputs changed.")] = False,
) -> None:
    """Check each built design's PDF, source and truth are one design, without reading
    the extractor's output, and record the evidence in bench/verified_<corpus>.json."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import verify

    loaded = corpora.load(corpus, bench_dir)
    found = verify.verify(loaded, [bench_dir / "build", *(against or [])])
    records = found["designs"]
    path = bench_dir / f"verified_{corpus}.json"
    changed = verify.check_sealed(found, json.loads(path.read_text())) if path.exists() else []
    for line in changed:
        typer.echo(line, err=True)
    for r in records:
        typer.echo(f"{r['decision']:10} {r['generator']:8} {r['name']}: {'; '.join(r['reasons'])}")
    if changed and not seal:
        typer.echo(f"the corpus changed since {path} was written; --seal to accept", err=True)
        raise typer.Exit(1)
    path.write_text(json.dumps(found, indent=1) + "\n")
    admitted = sum(r["decision"] == "verified" for r in records)
    typer.echo(f"{admitted} of {len(records)} verified; {path}")


@app.command(hidden=True)
def evaluate(
    corpus: CorpusName,
    out: Annotated[Path, typer.Argument(help="Where predictions are written, once each.")],
    bench_dir: BenchDir = Path("bench"),
    workers: Annotated[int, typer.Option(help="designs read at once")] = 2,
    library_dir: LibraryOption = None,
    python: Annotated[
        str, typer.Option(help="Read with the schem2net installed for this Python.")
    ] = sys.executable,
) -> None:
    """Read each verified design of a corpus in a process of its own, then score the
    saved predictions into OUT/report.json, by design, generator and group."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import evaluate as evaluation

    loaded = corpora.load(corpus, bench_dir)
    try:
        evaluation.extract(loaded, out, workers, library_dir, python)
        found = evaluation.report(loaded, out)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    (out / "report.json").write_text(json.dumps(found, indent=1) + "\n")
    columns = ["pin_accuracy", "net_exact", "connection_f1", "silent_error_rate"]
    typer.echo(
        f"{'generator':10} {'designs':>7} {'groups':>6} "
        + " ".join(f"{c[:12]:>12}" for c in columns)
    )
    every = {**found["size"], "total": found["total"]}
    for name, g in [*found["by_generator"].items(), ("all", every)]:
        cells = " ".join(_fmt(g["total"][c]) for c in columns)
        typer.echo(f"{name:10} {g['designs']:>7} {g['groups']:>6} {cells}")
    failed = [n for n, e in found["extra"].items() if "failed" in e]
    if failed:
        typer.echo(f"{len(failed)} designs failed: {', '.join(failed)}", err=True)


@app.command(hidden=True)
def bench(
    corpus: CorpusName = "a",
    split: Annotated[str, typer.Option(help="dev, test, holdout, or all: dev and test.")] = "dev",
    sample: Annotated[int | None, typer.Option(help="Score a fixed random sample.")] = None,
    bench_dir: BenchDir = Path("bench"),
    json_out: Annotated[Path | None, typer.Option("--json", help="Write metrics as JSON.")] = None,
    drawing_only: Annotated[
        bool, typer.Option(help="Ignore netlists carried in the PDF, such as Altium bookmarks.")
    ] = False,
    workers: Annotated[int, typer.Option(help="designs read at once")] = 2,
    library_dir: LibraryOption = None,
    explain: Annotated[
        bool, typer.Option(help="Show where the pins went, and error by confidence.")
    ] = False,
    folds: Annotated[
        Path | None,
        typer.Option(help="Read each dev design with the models of its fold in this folder."),
    ] = None,
) -> None:
    """Score the extractor against a built corpus."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import explain as explained
    from schem2net.bench import runner
    from schem2net.bench.score import Counts, intervals, score, summary

    if folds and not (folds / "fold-0").is_dir():
        raise typer.BadParameter(f"{folds} has no fold-0; make the folds with build-models")
    extract = partial(pipeline.extract, embedded=not drawing_only, library_dir=library_dir)
    loaded = corpora.load(corpus, bench_dir)
    results = runner.run(
        loaded,
        split=split,
        sample=sample,
        extract=extract,
        workers=workers,
        judge=explained.judge if explain else score,
        folds=folds,
    )
    if not results:
        typer.echo("nothing to score; run build-corpus first", err=True)
        raise typer.Exit(1)
    if explain:
        for line in explained.report([(name, found) for name, (_, found) in results]):
            typer.echo(line)
        typer.echo()
        results = [(name, counts) for name, (counts, _) in results]

    total = sum((counts for _, counts in results), Counts())
    columns = ["pin_accuracy", "signal_pin_accuracy", "net_exact", "connection_f1"]
    typer.echo(f"{'design':32} {'pins':>6} " + " ".join(f"{c[:12]:>12}" for c in columns))
    for name, counts in [*results, ("TOTAL", total)]:
        metrics = counts.metrics()
        typer.echo(
            f"{name[:32]:32} {counts.pins:>6} " + " ".join(_fmt(metrics[c]) for c in columns)
        )

    failed = [name for name, counts in results if counts.pages_failed]
    if failed:
        typer.echo(f"pages failed in {len(failed)} designs: {', '.join(failed)}", err=True)
    groups = [loaded.groups[name] for name, _ in results]
    typer.echo(f"{len(results)} designs in {len(set(groups))} groups")

    if json_out:
        report = {
            "corpus": corpus,
            "split": split,
            "folds": str(folds) if folds else None,
            "total": summary([counts for _, counts in results]),
            "intervals": intervals([counts for _, counts in results], groups),
            "designs": {name: asdict(counts) for name, counts in results},
            "groups": dict(zip((name for name, _ in results), groups, strict=True)),
        }
        json_out.write_text(json.dumps(report, indent=2))


@app.command("bench-compare", hidden=True)
def bench_compare(before: Path, after: Path) -> None:
    """Compare two bench runs design by design. Fails when pin accuracy is surely lower
    or silent errors are higher."""
    from schem2net.bench.score import Counts, compare, verdict

    loaded = [json.loads(path.read_text()) for path in (before, after)]
    runs = [run["designs"] for run in loaded]
    names = sorted(runs[0].keys() & runs[1].keys())
    for path, run in zip((before, after), runs, strict=True):
        if left := sorted(run.keys() - set(names)):
            typer.echo(f"{path}: {len(left)} designs not in the other run: {', '.join(left)}")
    if runs[0].keys() != runs[1].keys():
        typer.echo("cannot compare runs with different designs", err=True)
        raise typer.Exit(1)
    if not names:
        typer.echo("no designs in common", err=True)
        raise typer.Exit(1)
    # Two `evaluate` readings compare only under one seal, on one platform, both with the
    # same library or none; never with a `bench` run.
    probes = [run.get("run") for run in loaded]
    if any(probes) and not all(probes):
        typer.echo("cannot compare an evaluate reading with a bench run", err=True)
        raise typer.Exit(1)
    if all(probes):
        from schem2net.bench.reader import LEARNED

        deps = [p.get("dependencies", {}) for p in probes]
        libs = [{k: v for k, v in p.get("files", {}).items() if k not in LEARNED} for p in probes]
        apart = [k for k in ("seal", "python", "machine", "pdfium", "fonts", "embedded")
                 if probes[0].get(k) != probes[1].get(k)]  # fmt: skip
        apart += [d for d in deps[0].keys() | deps[1].keys() if deps[0].get(d) != deps[1].get(d)]
        apart += ["library"] * (libs[0] != libs[1])
        if apart:
            typer.echo(f"cannot compare runs read apart: {', '.join(sorted(apart))}", err=True)
            raise typer.Exit(1)
    # Runs written before groups were kept count each design as a group of its own.
    known = loaded[1].get("groups") or loaded[0].get("groups") or {}
    groups = [known.get(n, n) for n in names]
    counts = [[Counts(**run[n]) for n in names] for run in runs]
    changes = compare(*counts, groups)
    typer.echo(f"{len(names)} designs in {len(set(groups))} groups")
    typer.echo(f"{'metric':32} {'before':>8} {'after':>8} {'change':>8}  95% interval")
    for name, (first, second, change, low, high) in changes.items():
        typer.echo(f"{name:32} {first:8.4f} {second:8.4f} {change:+8.4f}  {low:+.4f} {high:+.4f}")
    pins, silent = changes.get("pin_accuracy"), changes.get("silent_error_rate")
    failed = []
    if pins and pins[4] <= GATE["pin_accuracy"]:
        failed.append("pin accuracy is lower")
    if silent and silent[2] > GATE["silent_error_rate"]:
        failed.append("silent errors are higher")
    if sum(c.pages_failed for c in counts[1]) > sum(c.pages_failed for c in counts[0]):
        failed.append("more pages failed")
    if pins and pins[3] > 0:
        typer.echo("pin accuracy is higher")
    if pins and silent:
        for name, outcome in verdict(changes).items():
            typer.echo(f"protocol: {name}: {outcome}")
    for line in failed:
        typer.echo(line, err=True)
    if failed:
        raise typer.Exit(1)


# A run passes when the interval of the pin accuracy change reaches above -0.002 and
# silent errors rise by no more than 0.001.
GATE = {"pin_accuracy": -0.002, "silent_error_rate": 0.001}


@app.command("build-models", hidden=True)
def build_models(
    kinds: Annotated[
        list[str] | None, typer.Argument(help="roles, designators, groups, font; all if none.")
    ] = None,
    bench_dir: BenchDir = Path("bench"),
    out_dir: Annotated[Path, typer.Option("-o", "--out-dir")] = Path("src/schem2net/profiles"),
    folds: Annotated[
        bool, typer.Option(help="Learn each fold's models without its designs, into fold-K.")
    ] = False,
    workers: Annotated[int, typer.Option(help="designs read at once")] = 2,
) -> None:
    """Learn the files of profiles/ from the dev split of each corpus. Needs scikit-learn
    (the dev dependencies)."""
    from schem2net.bench import learn

    unknown = sorted(set(kinds or ()) - learn.KINDS.keys())
    if unknown:
        raise typer.BadParameter(f"no such kind: {', '.join(unknown)}")
    for line in learn.learn(kinds or list(learn.KINDS), bench_dir, out_dir, workers, folds):
        typer.echo(line)


@app.command("bench-schematic", hidden=True)
def bench_schematic(
    corpus: CorpusName = "a",
    split: Annotated[str, typer.Option(help="dev, test, holdout, or all: dev and test.")] = "dev",
    bench_dir: BenchDir = Path("bench"),
    work: Annotated[Path, typer.Option(help="Where to write the projects.")] = Path("bench/out"),
) -> None:
    """Check the KiCad schematic export: same netlist read back, and ERC errors."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import roundtrip

    loaded = corpora.load(corpus, bench_dir)
    projects = [p for p in loaded.projects if loaded.in_split(p, split)]
    exact, clean, errors = 0, 0, Counter()
    for project in sorted(projects, key=lambda p: p.name):
        pdf_file = loaded.build_dir(project) / "schematic.pdf"
        result = roundtrip.check(pdf_file, work / corpus / project.name)
        exact += result.pin_accuracy == 1.0
        clean += not result.erc_errors
        errors += result.erc_errors
        found = ", ".join(f"{n} {k}" for k, n in result.erc_errors.most_common()) or "clean"
        typer.echo(f"{project.name[:32]:32} {_fmt(result.pin_accuracy)}  {found}")
    typer.echo(f"{len(projects)} designs: {exact} read back exactly, {clean} without ERC errors")
    typer.echo(", ".join(f"{n} {k}" for k, n in errors.most_common()))


def _fmt(value: float | None) -> str:
    return f"{'-':>12}" if value is None else f"{value:>12.3f}"
