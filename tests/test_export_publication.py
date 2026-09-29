"""Whole-set staging and rollback must preserve prior export bytes."""

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts, publication


def snapshot(path: Path) -> dict[str, bytes] | None:
    return {p.name: p.read_bytes() for p in path.iterdir()} if path.exists() else None


def setup_request(tmp_path: Path, existing: bool) -> ExportRequest:
    output = tmp_path / "out"
    if existing:
        output.mkdir()
        for name in ("box-a.step", "box-a.stl", "box-a.metadata.json", "other.txt"):
            (output / name).write_bytes(f"old {name}".encode())
    return ExportRequest(
        "box",
        "box",
        {"a": cq.Workplane().box(2, 3, 4), "b": cq.Workplane().box(3, 4, 5)},
        output,
        tmp_path,
    )


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["stl", "metadata"])
def test_preparation_failure_leaves_destination_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    failure: str,
) -> None:
    req = setup_request(tmp_path, existing)
    before = snapshot(req.output_directory)
    if failure == "stl":
        original_export = cq.exporters.export

        def broken_export(model: Any, filename: str, *args: Any, **kwargs: Any) -> Any:
            if filename.endswith("box-b.stl"):
                raise OSError("STL write failed")
            return original_export(model, filename, *args, **kwargs)

        monkeypatch.setattr(cq.exporters, "export", broken_export)
    else:
        original_write = Path.write_text

        def broken_write(path: Path, *args: Any, **kwargs: Any) -> int:
            if path.name == "box-b.metadata.json":
                raise OSError("metadata write failed")
            return original_write(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", broken_write)
    with pytest.raises(OSError):
        export_parts(req)
    assert snapshot(req.output_directory) == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failed_replace", [1, 2, 4, 6])
def test_publication_failure_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    failed_replace: int,
) -> None:
    req = setup_request(tmp_path, existing)
    before = snapshot(req.output_directory)
    original = publication.os.replace
    count = 0

    def broken(src: str | Path, dst: str | Path) -> None:
        nonlocal count
        if Path(src).parent.name == "incoming":
            count += 1
            if count == failed_replace:
                raise OSError("publication failed")
        return original(src, dst)

    monkeypatch.setattr(publication.os, "replace", broken)
    with pytest.raises(OSError):
        export_parts(req)
    assert snapshot(req.output_directory) == before
    assert not list(tmp_path.glob(".zcad-publish-*"))


def test_success_preserves_unrelated_files_and_final_paths(tmp_path: Path) -> None:
    req = setup_request(tmp_path, True)
    result = export_parts(req)
    assert (req.output_directory / "other.txt").read_bytes() == b"old other.txt"
    assert len(list(req.output_directory.iterdir())) == 7
    for part in result.parts:
        record = json.loads(part.metadata_path.read_text())
        assert record["outputs"]["step"] == str(part.step_path)
        assert record["outputs"]["stl"] == str(part.stl_path)
        assert part.step_path.parent == req.output_directory


def test_rollback_failure_retains_recovery_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    output = tmp_path / "out"
    output.mkdir()
    for name in ("a", "b"):
        (staged / name).write_bytes(b"new")
        (output / name).write_bytes(b"old")
    original = publication.os.replace

    def broken(src: str | Path, dst: str | Path) -> None:
        if Path(src).name == "b" or Path(src).parent.name == "backup":
            raise OSError("disk unavailable")
        return original(src, dst)

    monkeypatch.setattr(publication.os, "replace", broken)
    with pytest.raises(RuntimeError, match="recovery files retained"):
        publication.publish_files(staged, output)
    recovery = list(tmp_path.glob(".zcad-publish-*"))
    assert len(recovery) == 1
    assert (recovery[0] / "backup/a").read_bytes() == b"old"


def test_symlink_target_is_rejected(tmp_path: Path) -> None:
    staged = tmp_path / "stage"
    staged.mkdir()
    (staged / "a").write_bytes(b"new")
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    (output / "a").symlink_to(outside)
    with pytest.raises(ValueError, match="regular file"):
        publication.publish_files(staged, output)
    assert outside.read_bytes() == b"keep"
