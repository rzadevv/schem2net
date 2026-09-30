import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from schem2net import export as exporters
from schem2net import pdf, pipeline, report, svg
from schem2net.bench import corpus as corpora
from schem2net.bench import runner
from schem2net.bench.score import Counts
from schem2net.ir import Design

app = typer.Typer(no_args_is_help=True, add_completion=False)

BenchDir = Annotated[Path, typer.Option(help="Directory holding the corpus manifests.")]
CorpusName = Annotated[str, typer.Argument(help="Corpus name, e.g. a.")]


@app.command()
def extract(
    file: Path,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Extract a netlist from a schematic PDF and write it as JSON."""
    design = pipeline.extract(file)
    output = output or file.with_suffix(".ir.json")
    design.save(output)
    typer.echo(
        f"{output}: {len(design.components)} components, "
        f"{len(design.nets)} nets, {len(design.issues)} issues"
    )


class Format(StrEnum):
    kicad_net = "kicad-net"
    bom = "bom"


SUFFIXES = {Format.kicad_net: ".net", Format.bom: ".bom.csv"}


@app.command()
def export(
    file: Annotated[Path, typer.Argument(help="A schematic PDF, or JSON written by extract.")],
    to: Annotated[Format, typer.Option(help="Output format.")] = Format.kicad_net,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Write a KiCad netlist or a bill of materials."""
    design = _load(file)
    text = exporters.kicad_netlist(design) if to == Format.kicad_net else exporters.bom_csv(design)
    output = output or file.with_name(file.name.split(".")[0] + SUFFIXES[to])
    output.write_text(text)
    typer.echo(output)


def _load(file: Path) -> Design:
    if file.suffix.lower() == ".pdf":
        return pipeline.extract(file)
    return Design.load(file)


@app.command("report")
def report_(
    file: Path,
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Write an HTML page showing the extracted nets over the schematic."""
    output = output or file.with_suffix(".html")
    output.write_text(report.render(pipeline.run(file)))
    typer.echo(output)


@app.command("serve-mcp")
def serve_mcp(
    file: Annotated[Path, typer.Argument(help="A schematic PDF, or JSON written by extract.")],
) -> None:
    """Serve a design to agents over MCP (stdio)."""
    try:
        from schem2net import mcp_server
    except ImportError:
        typer.echo('The MCP server needs: pip install "schem2net[mcp]"', err=True)
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


@app.command("build-corpus")
def build_corpus(corpus: CorpusName = "a", bench_dir: BenchDir = Path("bench")) -> None:
    """Render corpus projects to (PDF, netlist) pairs with kicad-cli in Docker."""
    failed = corpora.build(corpora.load(corpus, bench_dir), log=typer.echo)
    if failed:
        typer.echo(f"{len(failed)} projects failed: {', '.join(failed)}", err=True)
        raise typer.Exit(1)


@app.command()
def bench(
    corpus: CorpusName = "a",
    split: Annotated[str, typer.Option(help="dev, test or all.")] = "dev",
    sample: Annotated[int | None, typer.Option(help="Score a fixed random sample.")] = None,
    bench_dir: BenchDir = Path("bench"),
    json_out: Annotated[Path | None, typer.Option("--json", help="Write metrics as JSON.")] = None,
) -> None:
    """Score the extractor against a built corpus."""
    results = runner.run(corpora.load(corpus, bench_dir), split=split, sample=sample)
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
            "total": total.metrics(),
            "designs": {name: counts.metrics() for name, counts in results},
        }
        json_out.write_text(json.dumps(report, indent=2))


def _fmt(value: float | None) -> str:
    return f"{'-':>12}" if value is None else f"{value:>12.3f}"
