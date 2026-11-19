"""Validate external IR without losing supported extraction diagnostics."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from schem2net import ir
from schem2net.ir import SCHEMA, Design, Net


@pytest.fixture
def payload():
    return {
        "schema": SCHEMA,
        "source": {"file": "board.pdf"},
        "components": [
            {"ref": "R1", "pins": [{"num": "1"}, {"num": "2"}]},
            {"ref": "R2", "pins": [{"num": "1"}, {"num": "2"}]},
        ],
        "nets": [
            {"id": "n1", "pins": [["R1", "1"], ["R2", "1"]]},
            {"id": "n2", "pins": [["R1", "2"], ["R2", "2"]]},
        ],
    }


INVALID = [
    ({"schema": "schem2net/ir@999"}, "schema"),
    ({"nets": [{"id": "n1"}, {"id": "n1"}]}, "net IDs"),
    ({"nets": [{"id": ""}]}, "net IDs"),
    ({"components": [{"ref": "R1"}, {"ref": "R1"}]}, "component references"),
    ({"components": [{"ref": ""}]}, "component references"),
    ({"nets": [{"id": "n1", "pins": [["UNKNOWN", "1"]]}]}, "unknown components"),
    ({"issues": [{"kind": "example", "net": "absent"}]}, "unknown nets"),
    ({"nets": [{"id": "n1", "confidence": 2.0}]}, "confidence"),
]


@pytest.mark.parametrize("replacement,reason", INVALID)
def test_loading_invalid_ir_explains_the_problem(tmp_path, payload, replacement, reason):
    file = tmp_path / "board.ir.json"
    file.write_text(json.dumps(payload | replacement))
    with pytest.raises(ValueError, match=reason):
        Design.load(file)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_confidence_requires_a_finite_evidence_weight(confidence):
    with pytest.raises(ValueError, match="confidence"):
        Net(id="n1", confidence=confidence)


@pytest.mark.parametrize("raw", [b"{", b"\xff"])
def test_loading_malformed_ir_is_a_plain_input_error(tmp_path, raw):
    file = tmp_path / "board.ir.json"
    file.write_bytes(raw)
    with pytest.raises(ValueError, match="invalid design JSON"):
        Design.load(file)


@pytest.mark.parametrize("replacement,reason", INVALID)
def test_cli_refuses_invalid_ir_without_replacing_output(tmp_path, payload, replacement, reason):
    file, output = tmp_path / "board.ir.json", tmp_path / "board.net"
    file.write_text(json.dumps(payload | replacement))
    output.write_text("existing netlist")
    result = subprocess.run(
        [sys.executable, "-c", "from schem2net.cli import main; main()",
         "export", str(file), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert result.returncode == 1
    assert str(file) in result.stderr and reason in result.stderr
    assert "Traceback" not in result.stderr
    assert output.read_text() == "existing netlist"


@pytest.mark.parametrize("raw", [b"{", b"\xff"])
def test_cli_refuses_malformed_ir_plainly(tmp_path, raw):
    file, output = tmp_path / "board.ir.json", tmp_path / "board.net"
    file.write_bytes(raw)
    output.write_text("existing netlist")
    result = subprocess.run(
        [sys.executable, "-c", "from schem2net.cli import main; main()",
         "export", str(file), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert result.returncode == 1 and "invalid design JSON" in result.stderr
    assert "Traceback" not in result.stderr and output.read_text() == "existing netlist"


def test_loading_keeps_repeated_units_and_reported_pin_conflicts(tmp_path, payload):
    file = tmp_path / "board.ir.json"
    payload["components"][0]["units"] = ["A", "B"]
    payload["components"][0]["pins"].append({"num": "1"})
    payload["nets"][1]["pins"][0] = ["R1", "1"]
    payload["issues"] = [{"kind": "duplicate_pin", "pins": [["R1", "1"]], "net": "n1"}]
    expected = Design.model_validate(payload)
    expected.save(file)
    assert Design.load(file) == expected


def test_loading_legacy_ir_without_a_schema_uses_the_current_default(tmp_path, payload):
    file = tmp_path / "board.ir.json"
    del payload["schema"]
    file.write_text(json.dumps(payload))
    assert Design.load(file).schema_ == SCHEMA


def test_concurrent_saves_each_finish_with_a_complete_design(tmp_path, payload, monkeypatch):
    file = tmp_path / "board.ir.json"
    first = Design.model_validate(payload)
    second = Design.model_validate(payload | {"source": {"file": "other.pdf"}})
    ready, replace = Barrier(2), ir.os.replace

    def overlap(source, target):
        if target == file:
            ready.wait(timeout=10)
        replace(source, target)

    monkeypatch.setattr(ir.os, "replace", overlap)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda design: design.save(file), [first, second]))
    assert Design.load(file) in (first, second)
    assert set(tmp_path.iterdir()) == {file}


def test_a_failed_save_preserves_the_output_and_cleans_its_temporary_file(
    tmp_path, payload, monkeypatch
):
    file = tmp_path / "board.ir.json"
    design = Design.model_validate(payload)
    design.save(file)
    before = file.read_bytes()

    def fail(source, target):
        raise OSError("replacement failed")

    monkeypatch.setattr(ir.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        design.save(file)
    assert file.read_bytes() == before
    assert set(tmp_path.iterdir()) == {file}


def test_saving_supports_a_long_output_filename(tmp_path, payload):
    file = tmp_path / ("a" * 220 + ".json")
    design = Design.model_validate(payload)
    design.save(file)
    assert Design.load(file) == design
    assert set(tmp_path.iterdir()) == {file}
