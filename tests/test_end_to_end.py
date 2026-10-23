import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from schem2net import pdf, pipeline
from schem2net.ir import Design

from .conftest import KICAD_INK, resistor_page

KICAD = "Eeschema (KiCad 8.0)"


def _netlist(design):
    return {
        "generator": design.source.generator,
        "components": {c.ref: c.value for c in design.components},
        "nets": sorted(
            ({"name": n.name, "pins": sorted([list(p) for p in n.pins])} for n in design.nets),
            key=lambda n: n["pins"],
        ),
    }


def test_a_kicad_page_reads_as_its_netlist(tmp_path):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    expected = json.loads((Path(__file__).parent / "data" / "kicad_resistors.json").read_text())
    assert _netlist(pipeline.extract(file)) == expected


def test_a_reading_is_the_same_whatever_the_hash_seed(tmp_path):
    files = [
        resistor_page(KICAD_INK).save(tmp_path / "kicad.pdf", creator=KICAD),
        resistor_page(dict.fromkeys(KICAD_INK, (0, 0, 0))).save(tmp_path / "black.pdf"),
    ]
    code = "import sys; from schem2net import pipeline\n"
    code += "for f in sys.argv[1:]: print(pipeline.extract(f).model_dump_json())"
    outputs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run(
            [sys.executable, "-c", code, *map(str, files)],
            env=env, capture_output=True, text=True, check=True,
        )  # fmt: skip
        outputs.append(run.stdout)
    assert outputs[0] == outputs[1] and outputs[0].count("\n") == 2


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.lists(
        st.tuples(st.floats(0, 1, exclude_max=True), st.integers(0, 255)), min_size=1, max_size=8
    )
)
def test_a_damaged_pdf_is_read_or_refused_plainly(tmp_path, changes):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    data = bytearray(file.read_bytes())
    for where, value in changes:
        data[int(where * len(data))] = value
    file.write_bytes(bytes(data))
    with contextlib.suppress(pdf.InputError):
        assert isinstance(pipeline.extract(file), Design)


def test_a_page_past_the_limits_fails_alone(tmp_path, monkeypatch):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    monkeypatch.setattr(pdf, "MAX_OBJECTS", 5)
    failed = [i for i in pipeline.extract(file).issues if i.kind == "page_failed"]
    assert len(failed) == 1 and "drawing objects" in failed[0].detail


def test_a_page_read_too_long_fails_alone(tmp_path, monkeypatch):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    monkeypatch.setattr(pipeline, "PAGE_SECONDS", 0.01)
    monkeypatch.setattr(pipeline, "_read_page", lambda *args: time.sleep(1))
    failed = [i for i in pipeline.extract(file).issues if i.kind == "page_failed"]
    assert len(failed) == 1 and failed[0].detail.startswith("TimeoutError")


def test_a_file_of_too_many_pages_is_refused(tmp_path, monkeypatch):
    file = resistor_page(KICAD_INK).save(tmp_path / "r.pdf", creator=KICAD)
    monkeypatch.setattr(pdf, "MAX_PAGES", 0)
    with pytest.raises(pdf.InputError, match="pages"):
        pipeline.extract(file)
