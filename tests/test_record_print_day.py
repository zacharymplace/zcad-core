"""The print-day recorder that turns checklist answers into trial records."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record-print-day.py"


def recorder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_print_day", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up while the module is still loading.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def answer(**changes: object) -> dict[str, object]:
    return {
        "candidate_id": "board-corner-capture-r001",
        "observations": {"print_completed": {"passed": True, "notes": ""}},
        "measurements": {
            "vertical_play": {"value_mm": 0.8, "nominal_mm": 0.85, "notes": ""},
            "board_clearance": {"value_mm": None, "nominal_mm": 0.25, "notes": ""},
        },
        "disposition": "pass",
        "operator_notes": "",
        **changes,
    }


def read(tmp_path: Path, payload: dict[str, object]):  # type: ignore[no-untyped-def]
    (tmp_path / "print.json").write_text(json.dumps(payload), encoding="utf-8")
    (only,) = recorder().read_answers(tmp_path)
    return only


def test_a_finished_answer_keeps_only_what_was_measured(tmp_path: Path) -> None:
    finished = read(tmp_path, answer())

    assert finished.unfinished() is None
    assert list(finished.measured) == ["vertical_play"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"observations": {"print_completed": {"passed": None, "notes": ""}}},
            "unanswered checks: print_completed",
        ),
        ({"disposition": ""}, "no disposition"),
        (
            {
                "observations": {"print_completed": {"passed": False, "notes": ""}},
            },
            "a pass with failed checks: print_completed",
        ),
        ({"disposition": "revise", "measurements": {}}, "a revise needs at least one"),
    ],
)
def test_unfinished_answers_say_why(
    tmp_path: Path, changes: dict[str, object], reason: str
) -> None:
    assert reason in (read(tmp_path, answer(**changes)).unfinished() or "")


def test_giving_up_needs_no_measurement(tmp_path: Path) -> None:
    for disposition in ("reject", "fail"):
        given_up = read(tmp_path, answer(disposition=disposition, measurements={}))
        assert given_up.unfinished() is None


def test_prints_are_found_by_id(tmp_path: Path) -> None:
    module = recorder()
    candidate = tmp_path / "board" / "validation-lab" / "candidates" / "r001"
    candidate.mkdir(parents=True)
    (candidate / "candidate.json").write_text(
        json.dumps({"candidate_id": "board-corner-capture-r001"}), encoding="utf-8"
    )
    enclosure = tmp_path / "enclosures" / "case"
    enclosure.mkdir(parents=True)
    (enclosure / "enclosure.json").write_text("{}", encoding="utf-8")

    assert module.find_print(tmp_path, "board-corner-capture-r001") == (
        "fixture",
        candidate,
    )
    assert module.find_print(tmp_path, "case") == ("enclosure", enclosure)
    group = tmp_path / "enclosures" / "pair"
    group.mkdir(parents=True)
    (group / "enclosure-group.json").write_text("{}", encoding="utf-8")
    assert module.find_print(tmp_path, "pair") == ("group", group)
    with pytest.raises(FileNotFoundError, match="No fixture candidate or enclosure"):
        module.find_print(tmp_path, "nothing")


def test_a_group_enclosure_is_completed_as_a_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = recorder()
    build = tmp_path / "enclosures" / "pair"
    trial = build / "trials" / "trial-001"
    trial.mkdir(parents=True)
    (build / "enclosure-group.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def run(arguments: list[str]) -> dict[str, object]:
        calls.append(arguments)
        return {"trial_record": str(trial / "enclosure-group-trial.json")}

    monkeypatch.setattr(module, "_run", run)
    answers = tmp_path / "answers"
    answers.mkdir()
    finished = read(
        answers,
        {
            "candidate_id": "pair",
            "observations": {"bay_1_board_seats": {"passed": True, "notes": ""}},
            "measurements": {"base_height_mm": {"value_mm": 25.3, "nominal_mm": 25.4}},
            "disposition": "pass",
            "operator_notes": "",
        },
    )

    assert module.plan(finished, tmp_path) == ("group", "record", build)
    module.record_enclosure(finished, build, "enclosure-group")

    assert calls[0][:3] == ["enclosure-group", "trial", "complete"]
    written = json.loads((trial / "observations.json").read_text(encoding="utf-8"))
    assert written == {"bay_1_board_seats": {"result": "pass", "notes": ""}}
    # Once its record exists, the group is never recorded again.
    (trial / "enclosure-group-trial.json").write_text("{}", encoding="utf-8")
    assert module.plan(finished, tmp_path)[1] == "already recorded"
