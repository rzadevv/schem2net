"""Installed CLI/MCP checks. With no arguments, create a disposable test fixture."""

import asyncio
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


def check_distributions(folder=Path("dist")):
    """Reject local/untracked files accidentally included by the build backend."""
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0"))
    archive = next(folder.glob("schem2net-*.tar.gz"))
    wheel = next(folder.glob("schem2net-*.whl"))
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if member.isdir():
                continue
            path = member.name.partition("/")[2]
            assert member.isfile() and path in tracked | {"PKG-INFO"}, member.name
    with zipfile.ZipFile(wheel) as package:
        for path in package.namelist():
            if path.startswith("schem2net/"):
                assert "src/" + path in tracked, path
            else:
                assert path.split("/")[0].endswith(".dist-info"), path
    print("Wheel and sdist contain only project files and generated package metadata")


async def mcp_check(cli, ir):
    from mcp.client import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=str(cli), args=["serve-mcp", str(ir)])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        listed = await session.list_tools()
        assert {t.name for t in listed.tools} == {
            "list_components",
            "get_net",
            "pins_of",
            "trace",
            "low_confidence",
            "issues",
            "bom",
        }
        result = await session.call_tool("list_components", {"prefix": "R"})
        assert not result.is_error and "R1" in result.model_dump_json()
        net = await session.call_tool("get_net", {"name_or_pin": "R1.1"})
        assert not net.is_error and "R1" in net.model_dump_json()
        return {
            "initialize": initialized.model_dump(mode="json"),
            "tools": [t.name for t in listed.tools],
            "components": result.model_dump(mode="json"),
            "net": net.model_dump(mode="json"),
        }


def main(root):
    from schem2net import kicad, pipeline
    from schem2net.ir import Design

    cli = Path(sys.executable).with_name("schem2net")
    out = root / f"python-{sys.version_info.major}.{sys.version_info.minor}"
    out.mkdir()
    fixture = root / "resistors.pdf"
    ir = out / "cli.json"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "SCHEM2NET_LIBRARY")}
    runs = []

    def command(*args, expected=0):
        result = subprocess.run(
            [str(cli), *map(str, args)], env=env, text=True, capture_output=True, timeout=30
        )
        runs.append(
            {
                "args": list(map(str, args)),
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        assert result.returncode == expected, runs[-1]
        assert "Traceback" not in result.stderr

    command("--version")
    command("extract", fixture, "-o", ir)
    first = Design.load(ir)
    assert len(first.components) == 3 and len(first.nets) == 2
    for fmt, suffix in (("kicad-net", "net"), ("bom", "csv"), ("spice", "cir")):
        target = out / ("export." + suffix)
        command("export", ir, "--to", fmt, "-o", target)
        assert target.stat().st_size > 20
    assert len(kicad.read_netlist(out / "export.net").components) == 3
    command("schematic", fixture, "-o", out / "project")
    assert list((out / "project").glob("*.kicad_sch"))
    broken = out / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    command("extract", broken, "-o", ir, expected=1)
    assert Design.load(ir) == first  # A refused file must preserve an earlier output.
    command("extract", out / "missing.pdf", expected=1)
    # Existing fixtures, separate processes and hash seeds; no panel prediction is repeated.
    outputs = []
    for seed in ("1", "927"):
        code = (
            "from schem2net import pipeline; import sys; "
            "print(pipeline.extract(sys.argv[1]).model_dump_json())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(fixture)],
            env={**env, "PYTHONHASHSEED": seed},
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert "/site-packages/schem2net/" in pipeline.__file__
    mcp = asyncio.run(asyncio.wait_for(mcp_check(cli, ir), timeout=30))
    (out / "checks.json").write_text(
        json.dumps(
            {
                "python": sys.version,
                "package": pipeline.__file__,
                "runs": runs,
                "determinism": True,
                "mcp": mcp,
            },
            indent=2,
        )
    )
    print(sys.version.split()[0], "installed CLI, exports, errors, determinism and MCP passed")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(Path(sys.argv[1]).resolve())
    else:
        from tests.conftest import KICAD_INK, resistor_page

        with TemporaryDirectory(prefix="schem2net-smoke-") as folder:
            root = Path(folder)
            resistor_page(KICAD_INK).save(root / "resistors.pdf", creator="Eeschema (KiCad 8.0)")
            main(root)
