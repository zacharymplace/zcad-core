"""zcad-validation slice check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.cli import main


def write_summary(directory: Path, source: dict[str, object] | None) -> Path:
    directory.mkdir(parents=True)
    summary = directory / "slice-summary.json"
    payload: dict[str, object] = {"schema_version": "1.2.0"}

    if source is not None:
        payload["source"] = source

    summary.write_text(json.dumps(payload), encoding="utf-8")

    return summary


def test_check_finds_every_summary_and_fails_on_one_it_cannot_vouch_for(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    base = write_summary(tmp_path / "slice" / "base", None)
    lid = write_summary(
        tmp_path / "slice" / "lid",
        {"git_commit": "0" * 40, "uncommitted_changes": False},
    )

    exit_code = main(["slice", "check", str(tmp_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert not output["all_current"]
    assert [entry["summary"] for entry in output["slices"]] == [str(base), str(lid)]
    assert [entry["status"] for entry in output["slices"]] == ["unknown", "unknown"]
    assert "no source commit" in output["slices"][0]["reason"]


def test_check_refuses_a_path_with_no_summary(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["slice", "check", str(tmp_path)]) == 1
    assert "No slice-summary.json under" in capsys.readouterr().err
