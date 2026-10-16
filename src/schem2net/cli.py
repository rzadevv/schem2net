import base64
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated

import typer

from schem2net import __version__, fills, kicad_sch, library, pdf, pipeline, report, svg
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


@app.command()
def extract(
    file: Path,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    region: RegionOption = None,
) -> None:
    """Extract a netlist from a schematic PDF and write it as JSON."""
    design = pipeline.extract(file, region=_region(region))
    _refuse(design)
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
) -> None:
    """Write a KiCad netlist, a bill of materials or a SPICE netlist."""
    design = _load(file, _region(region))
    _refuse(design)
    text = WRITERS[to](design)
    output = output or file.with_name(_stem(file) + SUFFIXES[to])
    _write(output, text)
    typer.echo(output)
    _say(design)


@app.command()
def schematic(
    file: Annotated[Path, typer.Argument(help="A schematic PDF.")],
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Project folder.")] = None,
) -> None:
    """Write an editable KiCad project, one sheet per PDF page.

    Parts and wires go where the PDF drew them; the netlist carried in an Altium
    PDF is not used, since it has no drawing to place.
    """
    extraction = pipeline.run(file, embedded=False)
    _refuse(extraction.design)
    output = output or file.with_name(_stem(file) + "-kicad")
    root = kicad_sch.write(extraction, output, _stem(file))
    typer.echo(root)
    _say(extraction.design)


@app.command("diff")
def diff_(
    old: Annotated[Path, typer.Argument(help="Earlier revision: a PDF or JSON from extract.")],
    new: Annotated[Path, typer.Argument(help="Later revision.")],
) -> None:
    """List parts added, removed or changed in value, and pins that moved between nets."""
    from schem2net import diff as revisions

    typer.echo(revisions.render(revisions.diff(_load(old), _load(new))), nl=False)


def _load(file: Path, region: pipeline.Region | None = None) -> Design:
    if file.suffix.lower() == ".pdf":
        return pipeline.extract(file, region=region)
    return Design.load(file)


SKIPPED = {"board_page": "a board drawing", "table_page": "a table", "raster_page": "scanned"}


def _refuse(design: Design) -> None:
    """Exit with an error, before anything is written, when nothing could be read: an
    earlier output of the same name is left as it was."""
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
) -> None:
    """Write an HTML page showing the extracted nets over the schematic."""
    output = output or file.with_name(_stem(file) + ".html")
    extraction = pipeline.run(file, region=_region(region))
    _refuse(extraction.design)
    pictures = {}
    if pdf_under and not region:
        read = [result.page.number for result in extraction.pages if result.scene is not None]
        for number, png in pdf.page_pngs(file, read).items():
            pictures[number] = f"data:image/png;base64,{base64.b64encode(png).decode()}"
    _write(output, report.render(extraction, pictures))
    typer.echo(output)
    _say(extraction.design)


@app.command("serve-mcp")
def serve_mcp(
    file: Annotated[Path, typer.Argument(help="A schematic PDF, or JSON written by extract.")],
) -> None:
    """Serve a design to agents over MCP (stdio)."""
    try:
        from schem2net import mcp_server
    except ImportError:
        typer.echo('The MCP server needs the mcp package: install "schem2net[mcp]"', err=True)
        raise typer.Exit(1) from None
    mcp_server.build(_load(file)).run()


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
) -> None:
    """Index part libraries, from which the pins a PDF leaves unnumbered and the pins
    stacked under one drawn pin are numbered. KiCad installs its own, as in
    /usr/share/kicad/symbols, or get https://gitlab.com/kicad/libraries/kicad-symbols;
    Eagle libraries come from the part makers, such as SparkFun's on GitHub. Each kind
    found replaces the index of that kind."""
    found = {"kicad": library.index(folder), "eagle": library.index_eagle(folder)}
    for kind, parts in found.items():
        if parts:
            path = library.default_path(kind)
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


@app.command(hidden=True)
def bench(
    corpus: CorpusName = "a",
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    sample: Annotated[int | None, typer.Option(help="Score a fixed random sample.")] = None,
    bench_dir: BenchDir = Path("bench"),
    json_out: Annotated[Path | None, typer.Option("--json", help="Write metrics as JSON.")] = None,
    drawing_only: Annotated[
        bool, typer.Option(help="Ignore netlists carried in the PDF, such as Altium bookmarks.")
    ] = False,
    workers: Annotated[int, typer.Option(help="designs read at once")] = 2,
) -> None:
    """Score the extractor against a built corpus."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import runner
    from schem2net.bench.score import Counts, summary

    extract = partial(pipeline.extract, embedded=not drawing_only)
    results = runner.run(
        corpora.load(corpus, bench_dir),
        split=split,
        sample=sample,
        extract=extract,
        workers=workers,
    )
    if not results:
        typer.echo("nothing to score; run build-corpus first", err=True)
        raise typer.Exit(1)

    total = sum((counts for _, counts in results), Counts())
    columns = ["pin_accuracy", "signal_pin_accuracy", "net_exact", "connection_f1"]
    typer.echo(f"{'design':32} {'pins':>6} " + " ".join(f"{c[:12]:>12}" for c in columns))
    for name, counts in [*results, ("TOTAL", total)]:
        metrics = counts.metrics()
        typer.echo(
            f"{name[:32]:32} {counts.pins:>6} " + " ".join(_fmt(metrics[c]) for c in columns)
        )

    if json_out:
        report = {
            "corpus": corpus,
            "split": split,
            "total": summary([counts for _, counts in results]),
            "designs": {name: asdict(counts) for name, counts in results},
        }
        json_out.write_text(json.dumps(report, indent=2))


@app.command("bench-compare", hidden=True)
def bench_compare(before: Path, after: Path) -> None:
    """Compare two bench runs design by design. Fails when pin accuracy is surely lower
    or silent errors are higher."""
    from schem2net.bench.score import Counts, compare

    runs = [json.loads(path.read_text())["designs"] for path in (before, after)]
    names = sorted(runs[0].keys() & runs[1].keys())
    for path, run in zip((before, after), runs, strict=True):
        if left := sorted(run.keys() - set(names)):
            typer.echo(f"{path}: {len(left)} designs not in the other run: {', '.join(left)}")
    if not names:
        typer.echo("no designs in common", err=True)
        raise typer.Exit(1)
    changes = compare(*([Counts(**run[n]) for n in names] for run in runs))
    typer.echo(f"{'metric':32} {'before':>8} {'after':>8} {'change':>8}  95% interval")
    for name, (first, second, change, low, high) in changes.items():
        typer.echo(f"{name:32} {first:8.4f} {second:8.4f} {change:+8.4f}  {low:+.4f} {high:+.4f}")
    pins, silent = changes.get("pin_accuracy"), changes.get("silent_error_rate")
    failed = []
    if pins and pins[4] <= GATE["pin_accuracy"]:
        failed.append("pin accuracy is lower")
    if silent and silent[2] > GATE["silent_error_rate"]:
        failed.append("silent errors are higher")
    if pins and pins[3] > 0:
        typer.echo("pin accuracy is higher")
    for line in failed:
        typer.echo(line, err=True)
    if failed:
        raise typer.Exit(1)


# A run passes when the interval of the pin accuracy change reaches above -0.002 and
# silent errors rise by no more than 0.001.
GATE = {"pin_accuracy": -0.002, "silent_error_rate": 0.001}


@app.command("build-font", hidden=True)
def build_font(
    corpus: CorpusName = "c",
    bench_dir: BenchDir = Path("bench"),
    out_dir: Annotated[Path, typer.Option("-o", "--out-dir")] = Path("src/schem2net/profiles"),
) -> None:
    """Learn Eagle's glyph shapes, stroked and outlined, from a corpus (dev split)."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import font

    loaded = corpora.load(corpus, bench_dir)
    dirs = [
        loaded.build_dir(p)
        for p in loaded.projects
        if loaded.is_built(p) and loaded.split(p) == "dev"
    ]
    cache = bench_dir / "out" / f"font-samples-{corpus}.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        found = [(c, [tuple(map(tuple, seg)) for seg in s]) for c, s in saved["strokes"]]
        filled = [(c, fills.from_json(s)) for c, s in saved["fills"]]
    else:
        jobs = [(d / "schematic.sch", d / "schematic.pdf") for d in dirs]
        with ProcessPoolExecutor(max_workers=3) as pool:  # each holds whole PDFs in memory
            got = list(pool.map(font.samples_of, jobs))
        found = [s for stroked, _ in got for s in stroked]
        filled = [s for _, outlined in got for s in outlined]
        cache.parent.mkdir(parents=True, exist_ok=True)
        saved = {"strokes": found, "fills": [(c, fills.to_json(s)) for c, s in filled]}
        cache.write_text(json.dumps(saved))
    table = font.build(found)
    # Then glyphs too rare to place by position, from lines missing only them.
    shapes = [
        (e["char"], [tuple(map(tuple, seg)) for seg in sh]) for e in table for sh in e["shapes"]
    ]
    jobs = [(d / "schematic.sch", d / "schematic.pdf", shapes) for d in dirs]
    with ProcessPoolExecutor(max_workers=3) as pool:
        found += [s for got in pool.map(font.gap_samples_of, jobs) for s in got]
    table = font.build(found)
    font.write(table, out_dir / "eagle_font.json")
    filled_table = font.build_fills(filled)
    font.write(filled_table, out_dir / "eagle_fills.json")
    typer.echo(
        f"{len(table)} stroked characters from {len(found)} glyphs, "
        f"{len(filled_table)} outlined from {len(filled)}, in {len(dirs)} designs"
    )


@app.command("build-roles", hidden=True)
def build_roles(
    bench_dir: BenchDir = Path("bench"),
    output: Annotated[Path, typer.Option("-o", "--output")] = Path(
        "src/schem2net/profiles/roles.npz"
    ),
) -> None:
    """Learn path and text roles from the colour pages of each corpus's dev split, for
    reading pages printed in black. Needs scikit-learn (the dev dependencies)."""
    import numpy as np

    from schem2net.bench import corpus as corpora
    from schem2net.bench import roles as role_examples

    generators = {"a": "kicad", "b": "altium", "c": "eagle", "e": "easyeda", "f": "orcad"}
    jobs = []
    for name, generator in generators.items():
        try:
            loaded = corpora.load(name, bench_dir)
        except FileNotFoundError:
            continue
        jobs += [
            (generator, loaded.build_dir(p) / "schematic.pdf")
            for p in loaded.projects
            if loaded.is_built(p) and loaded.split(p) == "dev"
        ]
    examples: dict[str, list] = {}
    with ProcessPoolExecutor(max_workers=3) as pool:  # each holds whole PDFs in memory
        for (generator, _), pages in zip(jobs, pool.map(role_examples.rows, jobs), strict=True):
            examples.setdefault(generator, []).append(pages)
    with output.open("wb") as f:
        np.savez_compressed(f, **role_examples.train(examples))
    counts = ", ".join(
        f"{g} {sum(len(e[1]) for d in designs for e in d)}" for g, designs in examples.items()
    )
    typer.echo(f"{output}: learned from paths of {counts}")


@app.command("build-designators", hidden=True)
def build_designators(
    bench_dir: BenchDir = Path("bench"),
    output: Annotated[Path, typer.Option("-o", "--output")] = Path(
        "src/schem2net/profiles/designators.npz"
    ),
    workers: Annotated[int, typer.Option(help="designs read at once")] = 2,
) -> None:
    """Learn which texts are designators from the dev split of every corpus, whose truth
    netlists say which texts name parts. Needs scikit-learn (the dev dependencies)."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import designators as designator_examples

    designs = []
    for name in "abcde":
        try:
            loaded = corpora.load(name, bench_dir)
        except FileNotFoundError:
            continue
        designs += [
            loaded.build_dir(p)
            for p in loaded.projects
            if loaded.is_built(p) and loaded.split(p) == "dev"
        ]
    with ProcessPoolExecutor(max_workers=workers) as pool:  # each holds whole PDFs in memory
        examples = [e for found in pool.map(designator_examples.rows, designs) for e in found]
    designator_examples.save(designator_examples.train(examples), output)
    counts = Counter()
    for generator, _, labels in examples:
        counts[generator] += int((labels >= 0).sum())
    typer.echo(f"{output}: learned from {len(designs)} designs, texts {dict(counts)}")


@app.command("bench-schematic", hidden=True)
def bench_schematic(
    corpus: CorpusName = "a",
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    bench_dir: BenchDir = Path("bench"),
    work: Annotated[Path, typer.Option(help="Where to write the projects.")] = Path("bench/out"),
) -> None:
    """Check the KiCad schematic export: same netlist read back, and ERC errors."""
    from schem2net.bench import corpus as corpora
    from schem2net.bench import roundtrip

    loaded = corpora.load(corpus, bench_dir)
    projects = [
        p
        for p in loaded.projects
        if loaded.is_built(p) and (split == "all" or loaded.split(p) == split)
    ]
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
