"""zcad-validation export verify."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from zcad_core.cli import main


def write_export(directory: Path, stem: str = "part") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    bindings = {}

    for kind in ("step", "stl"):
        data = f"synthetic {stem} {kind} bytes".encode()
        (directory / f"{stem}.{kind}").write_bytes(data)
        bindings[kind] = {
            "filename": f"{stem}.{kind}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }

    metadata = directory / f"{stem}.metadata.json"
    metadata.write_text(json.dumps({"artifacts": bindings}), encoding="utf-8")

    return metadata


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_verify_finds_every_part_and_passes_when_all_bytes_match(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    base = write_export(tmp_path / "handoff", "base")
    lid = write_export(tmp_path / "handoff" / "nested", "lid")
    before = snapshot(tmp_path)

    exit_code = main(["export", "verify", str(tmp_path / "handoff")])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["all_matched"]
    assert output["counts"] == {"matched": 4}
    assert [part["metadata"] for part in output["parts"]] == [str(base), str(lid)]
    assert [a["kind"] for a in output["parts"][0]["artifacts"]] == ["step", "stl"]
    assert snapshot(tmp_path) == before


def test_verify_fails_and_names_the_artifact_that_changed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    metadata = write_export(tmp_path / "handoff")
    (tmp_path / "handoff" / "part.stl").write_bytes(b"edited after export")
    (tmp_path / "handoff" / "part.step").unlink()

    exit_code = main(["export", "verify", str(metadata)])
    output = json.loads(capsys.readouterr().out)
    step, stl = output["parts"][0]["artifacts"]

    assert exit_code == 1
    assert not output["all_matched"]
    assert output["counts"] == {"missing": 1, "mismatched": 1}
    assert (step["kind"], step["status"]) == ("step", "missing")
    assert (stl["kind"], stl["status"]) == ("stl", "mismatched")
    assert stl["expected_sha256"] != stl["actual_sha256"]


def test_verify_never_passes_metadata_that_records_no_bindings(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    legacy = tmp_path / "legacy.metadata.json"
    legacy.write_text(json.dumps({"outputs": {"stl": "part.stl"}}), encoding="utf-8")

    exit_code = main(["export", "verify", str(legacy)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["counts"] == {"not-verifiable": 2}


def test_verify_checks_a_file_named_twice_only_once(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    metadata = write_export(tmp_path / "handoff")

    assert main(["export", "verify", str(metadata), str(tmp_path / "handoff")]) == 0
    assert len(json.loads(capsys.readouterr().out)["parts"]) == 1


@pytest.mark.parametrize("name", ["absent.metadata.json", "empty"])
def test_verify_refuses_a_path_with_no_metadata(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, name: str
) -> None:
    (tmp_path / "empty").mkdir()

    assert main(["export", "verify", str(tmp_path / name)]) == 1
    assert "metadata" in capsys.readouterr().err
