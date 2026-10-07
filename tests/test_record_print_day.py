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


def test_a_coupon_is_found_recorded_and_skipped_when_it_did_not_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = recorder()
    build = tmp_path / "coupons" / "c1"
    trial = build / "trials" / "trial-001"
    trial.mkdir(parents=True)
    (build / "coupon.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def run(arguments: list[str]) -> dict[str, object]:
        calls.append(arguments)
        return {"trial_record": str(trial / "calibration-coupon-trial.json")}

    monkeypatch.setattr(module, "_run", run)
    answers = tmp_path / "answers"
    answers.mkdir()

    def answer(disposition: str, value: float | None):  # type: ignore[no-untyped-def]
        return read(
            answers,
            {
                "candidate_id": "c1",
                "observations": {
                    "printed_cleanly": {"passed": True, "notes": ""},
                    "features_open": {"passed": True, "notes": ""},
                },
                "measurements": {
                    "slot_1_height_mm": {"value_mm": value, "nominal_mm": 1.0}
                },
                "disposition": disposition,
                "operator_notes": "",
            },
        )

    assert module.find_print(tmp_path, "c1") == ("coupon", build)
    # It did not print: nothing to measure, so nothing to record.
    assert module.plan(answer("fail", None), tmp_path)[1].startswith(
        "skip: the coupon did not print"
    )
    assert module.plan(answer("measured", None), tmp_path)[1].startswith("skip:")

    measured = answer("measured", 0.9)
    assert module.plan(measured, tmp_path) == ("coupon", "record", build)
    module.record_coupon(measured, build)

    assert calls[0][:3] == ["coupon", "trial", "complete"]
    written = json.loads((trial / "measurements.json").read_text(encoding="utf-8"))
    assert written["slot_1_height_mm"]["value_mm"] == 0.9
    (trial / "calibration-coupon-trial.json").write_text("{}", encoding="utf-8")
    assert module.plan(measured, tmp_path)[1] == "already recorded"


def test_a_gridfinity_bin_is_recorded_with_what_it_was_fitted_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from zcad_core.cli import main

    module = recorder()
    name = "gridfinity-bin-1x1x2"
    build = tmp_path / "gridfinity" / name
    command = ["gridfinity", "bin", "--units", "1x1", "--height", "2", "--no-lip"]
    assert main([*command, "--output-directory", str(build)]) == 0
    assert (
        main(
            [
                "gridfinity",
                "trial",
                "start",
                "--build-record",
                str(build / "gridfinity.json"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    answers = tmp_path / "answers"
    answers.mkdir()

    def answer(**fit: object):  # type: ignore[no-untyped-def]
        return read(
            answers,
            {
                "candidate_id": name,
                "observations": {
                    check: {"passed": True, "notes": ""}
                    for check in ("printed_cleanly", "seats_flat", "lifts_out")
                },
                "measurements": {
                    "overall_width_mm": {"value_mm": 41.4, "nominal_mm": 41.5}
                },
                "disposition": "pass",
                "operator_notes": "",
                "fit": fit,
            },
        )

    assert module.find_print(tmp_path, name) == ("gridfinity", build)
    assert module.plan(answer(), tmp_path)[1] == (
        "skip: a pass must name what the part was fitted with"
    )

    fitted = answer(
        mated_with={
            "kind": "baseplate",
            "made_by": "another generator",
            "name": "Gridfinity Rebuilt 2x2 baseplate",
        },
        feel="right",
        seats_flat=True,
    )
    assert module.plan(fitted, tmp_path) == ("gridfinity", "record", build)
    result = module.record_gridfinity(fitted, build)

    assert result["verification"]["passing_with_another_generator"] == 1
    trial = json.loads(Path(result["trial_record"]).read_text(encoding="utf-8"))
    assert trial["fit"]["feel"] == "right"
    assert trial["measurements"][0]["value_mm"] == 41.4
    assert module.plan(fitted, tmp_path)[1] == "already recorded"


def coupon_record(root: Path, name: str, hole_mm: float, survived_to: float) -> None:
    trial = root / "coupons" / name / "trials" / "trial-001"
    trial.mkdir(parents=True)
    (trial / "calibration-coupon-trial.json").write_text(
        json.dumps(
            {
                "printer_profile_id": "bambu-lab-a1-mini",
                "material_profile_id": "petg",
                "hole_compensation_mm": 0.0,
                "tongue_orientation": "across_layers",
                "measurements": [
                    {
                        "name": "screw_hole_1_diameter_mm",
                        "kind": "hole",
                        "figure": "hole_shortfall_mm",
                        "nominal_mm": 3.4,
                        "value_mm": hole_mm,
                    }
                ],
                "tongues": [
                    {"name": f"t{s}", "strain": s, "survived": s <= survived_to}
                    for s in (0.01, 0.015, 0.02, 0.03)
                ],
            }
        ),
        encoding="utf-8",
    )


def test_the_profile_preview_says_what_would_change_and_writes_nothing(
    tmp_path: Path,
) -> None:
    module = recorder()
    evidence = tmp_path / "evidence"
    current = tmp_path / "profile.json"

    def preview() -> dict[str, object]:
        result: dict[str, object] = module.profile_preview(
            evidence,
            printer_profile_id="bambu-lab-a1-mini",
            material_profile_id="petg",
            profile_path=current,
        )
        return result

    coupon_record(evidence, "c1", 3.25, 0.02)
    not_yet = preview()
    assert not_yet["ready"] is False
    assert "needs at least 2" in str(not_yet["reason"])

    coupon_record(evidence, "c2", 3.35, 0.015)
    ready = preview()

    assert ready["ready"] is True
    assert ready["version"] == 1
    assert ready["trials"] == 2
    assert ready["changes"] == {
        "hole_shortfall_mm": {"from": None, "to": 0.1},
        "strain_limit": {"from": None, "to": 0.015},
    }
    assert str(ready["write_with"]).startswith("zcad-validation compensation derive")
    assert not current.exists()
