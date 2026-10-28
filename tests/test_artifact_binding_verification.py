"""Read-only verification of existing artifact bindings, not geometry validity."""

import hashlib
import json
from pathlib import Path

import pytest

from zcad_core.exporters import verify_artifact_bindings


def fixture_export(directory: Path) -> tuple[Path, dict]:
    directory.mkdir()
    bindings = {}
    for kind in ("step", "stl"):
        data = f"synthetic {kind} bytes".encode()
        (directory / f"part.{kind}").write_bytes(data)
        bindings[kind] = {
            "filename": f"part.{kind}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
    record = {
        "schema_version": "1.0",
        "artifacts": bindings,
        "outputs": {"step": "/historical/part.step", "stl": "/historical/part.stl"},
        "producer": {"git_commit": "core"},
        "git_commit": "consumer",
    }
    path = directory / "part.metadata.json"
    path.write_text(json.dumps(record))
    return path, record


def test_matches_relocated_bytes_without_writing_or_requiring_cad_validity(
    tmp_path: Path,
) -> None:
    metadata, record = fixture_export(tmp_path / "export")
    before = {p.name: p.read_bytes() for p in metadata.parent.iterdir()}
    destination = tmp_path / "moved"
    metadata.parent.rename(destination)
    checks = verify_artifact_bindings(destination / metadata.name)
    assert [c.kind for c in checks] == ["step", "stl"]
    assert [c.status for c in checks] == ["matched", "matched"]
    assert all(c.expected_sha256 == c.actual_sha256 for c in checks)
    assert all(c.expected_size_bytes == c.actual_size_bytes for c in checks)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == before
    assert json.loads((destination / metadata.name).read_text()) == record


@pytest.mark.parametrize("change", ["same-size", "size", "missing"])
def test_independent_artifact_failures(tmp_path: Path, change: str) -> None:
    metadata, _ = fixture_export(tmp_path / "export")
    artifact = metadata.parent / "part.step"
    if change == "missing":
        artifact.unlink()
    elif change == "same-size":
        artifact.write_bytes(b"x" * artifact.stat().st_size)
    else:
        artifact.write_bytes(b"changed size")
    step, stl = verify_artifact_bindings(metadata)
    assert step.status == ("missing" if change == "missing" else "mismatched")
    assert stl.status == "matched"


@pytest.mark.parametrize(
    "content", ["{}", "[]", "null", "{", '{"artifacts":null}', '{"artifacts":{}}']
)
def test_legacy_and_malformed_metadata_never_pass(tmp_path: Path, content: str) -> None:
    metadata = tmp_path / "part.metadata.json"
    metadata.write_text(content)
    assert all(c.status == "not-verifiable" for c in verify_artifact_bindings(metadata))


def test_missing_and_non_utf8_metadata(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    assert all(c.status == "not-verifiable" for c in verify_artifact_bindings(path))
    path.write_bytes(b"\xff")
    assert all(c.status == "not-verifiable" for c in verify_artifact_bindings(path))


@pytest.mark.parametrize(
    "filename",
    ["../outside", "/outside", "..\\outside", "C:outside", ".", "..", "", "a\x00b"],
)
def test_unsafe_filenames_are_rejected(tmp_path: Path, filename: str) -> None:
    metadata, record = fixture_export(tmp_path / "export")
    record["artifacts"]["step"]["filename"] = filename
    metadata.write_text(json.dumps(record))
    step, stl = verify_artifact_bindings(metadata)
    assert step.status == "not-verifiable"
    assert "basename" in step.reason
    assert stl.status == "matched"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "A" * 64),
        ("sha256", "bad"),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("size_bytes", 2.5),
        ("filename", 42),
    ],
)
def test_malformed_bindings_are_not_mismatches(
    tmp_path: Path, field: str, value: object
) -> None:
    metadata, record = fixture_export(tmp_path / "export")
    record["artifacts"]["step"][field] = value
    metadata.write_text(json.dumps(record))
    assert verify_artifact_bindings(metadata)[0].status == "not-verifiable"


@pytest.mark.parametrize("target", ["outside", "sibling", "missing", "directory"])
def test_symlinks_and_directories_are_not_read(tmp_path: Path, target: str) -> None:
    metadata, _ = fixture_export(tmp_path / "export")
    artifact = metadata.parent / "part.step"
    artifact.unlink()
    if target == "directory":
        artifact.mkdir()
    else:
        destination = tmp_path / target
        if target == "sibling":
            destination = metadata.parent / "part.stl"
        elif target == "outside":
            destination.write_text("private")
        artifact.symlink_to(destination)
    assert verify_artifact_bindings(metadata)[0].status == "not-verifiable"


def test_reorganized_bundle_does_not_follow_outputs(tmp_path: Path) -> None:
    metadata, record = fixture_export(tmp_path / "export")
    step = metadata.parent / "part.step"
    moved = tmp_path / "part.step"
    step.rename(moved)
    record["outputs"]["step"] = str(moved)
    record["bundle_output_path_base"] = "bundle_root"
    metadata.write_text(json.dumps(record))
    assert verify_artifact_bindings(metadata)[0].status == "missing"
