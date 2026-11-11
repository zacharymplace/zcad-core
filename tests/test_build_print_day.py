"""The print-day data: every part whose trial is open and whose slice is ready, read from its records."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-print-day.py"
STL = "solid part\nendsolid part\n"


def print_day() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_print_day", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, payload: dict[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )


def sliced(
    folder: Path,
    plate: str = "slice",
    *,
    seconds: float = 600.0,
    grams: float = 3.0,
    part: str | None = None,
    gcode: bool = True,
) -> None:
    write(
        folder / plate / "slice-summary.json",
        {
            "estimated_print_time_seconds": seconds,
            "filament_used_g": grams,
            "slicer_warning": "",
            "gcode_sha256": "f" * 64,
            "part": part,
            "source": {"git_commit": "def5678"},
        },
    )

    if gcode:
        write(folder / plate / "plate_1.gcode", "; gcode\n")


def candidate(evidence: Path, target: str, revision: str) -> Path:
    folder = evidence / target / "validation-lab" / "candidates" / revision
    write(
        folder / "candidate.json",
        {
            "candidate_id": f"{target}-corner-capture-{revision}",
            "target_id": target,
            "revision": revision,
            "git_commit": "abc1234",
            "fixture_artifact_path": f"evidence/{target}/validation-lab/candidates/{revision}/fixture.stl",
        },
    )
    write(folder / "fixture.stl", STL)
    return folder


def open_fixture_trial(folder: Path, trial: str = "trial-001") -> None:
    write(
        folder / "trials" / trial / "physical-validation.json",
        {"complete": False, "disposition": "pending"},
    )
    write(
        folder / "trials" / trial / "observations.json",
        {"board_seats_fully": {"passed": False, "notes": ""}},
    )
    write(
        folder / "trials" / trial / "measurements.json",
        {
            "board_clearance": {
                "value_mm": None,
                "nominal_mm": 0.25,
                "notes": "Smallest gap between the board edge and a capture wall.",
            }
        },
    )


def build(evidence: Path, kind: str, name: str, record: str, **extra: Any) -> Path:
    folder = evidence / kind / name
    write(folder / f"{name}.stl", STL)
    write(
        folder / record,
        {
            "design_name": name,
            "parts": {"part": {"stl_path": f"evidence/{kind}/{name}/{name}.stl"}},
            **extra,
        },
    )
    return folder


def open_trial(folder: Path, trial: str = "trial-001", **files: dict[str, Any]) -> None:
    observations = files.pop(
        "observations",
        {
            "printed_cleanly": {
                "result": "pending",
                "guidance": "It printed without warping.",
                "notes": "",
            }
        },
    )
    write(folder / "trials" / trial / "observations.json", observations)

    for name, payload in files.items():
        write(folder / "trials" / trial / f"{name}.json", payload)


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"

    # A fixture ready to print, and the revision it replaced, whose trial was left open.
    old = candidate(root, "board-a", "r001")
    open_fixture_trial(old)
    sliced(old)
    ready = candidate(root, "board-a", "r002")
    write(
        ready / "relationship.json",
        {
            "source_candidate_id": "board-a-corner-capture-r002",
            "target_candidate_id": "board-a-corner-capture-r001",
        },
    )
    open_fixture_trial(ready)
    sliced(ready, seconds=540.0, grams=3.66)

    # A group enclosure on two plates.
    group = build(root, "enclosures", "pi5-pair", "enclosure-group.json")
    open_trial(
        group,
        measurements={
            "base_length_mm": {
                "nominal_mm": 180.0,
                "value_mm": None,
                "guidance": "Calipers along the base.",
                "notes": "",
            }
        },
    )
    sliced(group, "slice/base", seconds=7668.0, grams=72.48, part="base")
    sliced(group, "slice/lid", seconds=4422.0, grams=44.98, part="lid")

    # A joint coupon: one fit rung, one snap rung.
    joint = build(root, "joints", "fit-01", "joint-coupon.json")
    open_trial(
        joint,
        observations={
            "printed_cleanly": {"result": "pending", "guidance": "Clean.", "notes": ""},
            "in_layer_0_05": {
                "reading": "pending",
                "choices": ["wont_go", "press", "slides", "loose", "skipped"],
                "orientation": "in_layer",
                "clearance_per_side_mm": 0.05,
                "guidance": "Push the reference in.",
                "notes": "",
            },
            "detent_0_30": {
                "reading": {"clicks_shut": None, "pull_force_n": None},
                "engagement_mm": 0.3,
                "dots": 1,
                "guidance": "Slide the drawer in.",
                "notes": "",
            },
        },
    )
    sliced(joint)

    # A Gridfinity bin, fitted with a baseplate.
    bin_folder = build(root, "gridfinity", "bin-1x1x3", "gridfinity.json")
    open_trial(bin_folder, fit={"mated_with": {"kind": "baseplate"}, "feel": None})
    sliced(bin_folder)

    # A coupon reprinted: its first trial recorded, its second open.
    coupon = build(root, "coupons", "petg-01", "coupon.json")
    write(
        coupon / "trials" / "trial-001" / "calibration-coupon-trial.json",
        {"disposition": None},
    )
    open_trial(coupon, "trial-002")
    sliced(coupon)

    # Left off: an open trial but no slice; a slice with no G-code; no trial at all.
    unsliced = build(root, "enclosures", "unsliced", "enclosure.json")
    open_trial(unsliced)
    no_gcode = build(root, "enclosures", "no-gcode", "enclosure.json")
    open_trial(no_gcode)
    sliced(no_gcode, gcode=False)
    build(root, "enclosures", "untried", "enclosure.json")

    # Not on the pages and not left off: a trial recorded, and an example.
    done = build(root, "enclosures", "done", "enclosure.json")
    write(
        done / "trials" / "trial-001" / "enclosure-trial.json", {"disposition": "pass"}
    )
    sliced(done)
    example = build(root, "examples/enclosures", "example", "enclosure.json")
    open_trial(example)
    sliced(example)

    return root


def prints_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in data["prints"]}


def test_every_ready_print_is_found_and_nothing_else(evidence: Path) -> None:
    data = print_day().find_prints(evidence)

    assert sorted(prints_by_id(data)) == [
        "board-a/validation-lab/candidates/r002",
        "coupons/petg-01",
        "enclosures/pi5-pair",
        "gridfinity/bin-1x1x3",
        "joints/fit-01",
    ]


def test_a_design_that_cannot_go_on_the_pages_says_why(evidence: Path) -> None:
    data = print_day().find_prints(evidence)

    assert {entry["id"]: entry["why"] for entry in data["left_off"]} == {
        "enclosures/unsliced": "not sliced",
        "enclosures/no-gcode": "sliced, but no G-code in slice",
        "enclosures/untried": "no open trial",
    }


def test_a_fixture_reads_its_checks_measurements_plate_and_choices(
    evidence: Path,
) -> None:
    fixture = prints_by_id(print_day().find_prints(evidence))[
        "board-a/validation-lab/candidates/r002"
    ]

    assert fixture["name"] == "board-a-corner-capture-r002"
    assert fixture["for"] == "board-a"
    assert fixture["commit"] == "abc1234"
    assert fixture["trial"] == (
        "evidence/board-a/validation-lab/candidates/r002/trials/trial-001"
    )
    assert fixture["checks"] == [{"name": "board_seats_fully", "guidance": ""}]
    assert fixture["measurements"] == [
        {
            "name": "board_clearance",
            "nominal_mm": 0.25,
            "guidance": "Smallest gap between the board edge and a capture wall.",
        }
    ]
    assert fixture["plates"] == [
        {
            "plate": "slice",
            "part": None,
            "minutes": 9.0,
            "grams": 3.66,
            "gcode": "evidence/board-a/validation-lab/candidates/r002/slice/plate_1.gcode",
            "gcode_sha256": "f" * 64,
            "warning": "",
        }
    ]
    assert fixture["dispositions"] == ["pass", "revise", "reject"]
    assert fixture["rungs"] == []
    assert fixture["fit"] is None


def test_a_build_on_two_plates_adds_them_up(evidence: Path) -> None:
    group = prints_by_id(print_day().find_prints(evidence))["enclosures/pi5-pair"]

    assert [plate["part"] for plate in group["plates"]] == ["base", "lid"]
    assert group["minutes"] == 201.5
    assert group["grams"] == 117.46
    assert group["commit"] == "def5678"
    assert group["dispositions"] == ["pass", "revise", "fail"]
    assert group["measurements"][0]["guidance"] == "Calipers along the base."


def test_a_joint_coupon_reads_its_rungs_apart_from_its_checks(evidence: Path) -> None:
    joint = prints_by_id(print_day().find_prints(evidence))["joints/fit-01"]

    assert [check["name"] for check in joint["checks"]] == ["printed_cleanly"]
    fit, snap = joint["rungs"]
    assert fit == {
        "name": "in_layer_0_05",
        "orientation": "in_layer",
        "clearance_per_side_mm": 0.05,
        "guidance": "Push the reference in.",
        "reads": {"choice": ["wont_go", "press", "slides", "loose", "skipped"]},
    }
    assert snap["reads"] == {"readings": ["clicks_shut", "pull_force_n"]}
    assert snap["dots"] == 1
    assert joint["dispositions"] == ["measured", "fail"]


def test_a_gridfinity_part_carries_its_fit(evidence: Path) -> None:
    part = prints_by_id(print_day().find_prints(evidence))["gridfinity/bin-1x1x3"]

    assert part["fit"] == {"mated_with": {"kind": "baseplate"}, "feel": None}


def test_a_reprint_is_on_the_pages_with_its_open_trial(evidence: Path) -> None:
    coupon = prints_by_id(print_day().find_prints(evidence))["coupons/petg-01"]

    assert coupon["trial"] == "evidence/coupons/petg-01/trials/trial-002"


def test_notes_are_read_where_present_and_their_absence_is_listed(
    evidence: Path,
) -> None:
    write(
        evidence / "enclosures" / "pi5-pair" / "print-notes.json",
        {"watch": ["The lid is worth printing only if the base passes."], "after": "x"},
    )

    data = print_day().find_prints(evidence)

    assert prints_by_id(data)["enclosures/pi5-pair"]["notes"] == {
        "watch": ["The lid is worth printing only if the base passes."],
        "have": [],
        "optional": False,
        "after": "x",
    }
    assert "enclosures/pi5-pair" not in data["without_notes"]
    assert "joints/fit-01" in data["without_notes"]


@pytest.mark.parametrize(
    ("notes", "complaint"),
    [
        ({"watch": "one line"}, "watch must be a list"),
        ({"have": [3]}, "every line of have must be text"),
        ({"optional": "yes"}, "optional must be a bool"),
        ({"order": 1}, "unknown field(s) order"),
    ],
)
def test_notes_that_do_not_read_are_refused(
    evidence: Path, notes: dict[str, Any], complaint: str
) -> None:
    write(evidence / "joints" / "fit-01" / "print-notes.json", notes)

    with pytest.raises(
        ValueError, match=complaint.replace("(", r"\(").replace(")", r"\)")
    ):
        print_day().find_prints(evidence)


def test_the_data_is_written_and_replaced(evidence: Path, tmp_path: Path) -> None:
    module = print_day()
    output = tmp_path / "print-day"

    module.build_print_day(evidence, output)
    (output / "stale.txt").write_text("old\n", encoding="utf-8")
    data = module.build_print_day(evidence, output)

    written = json.loads((output / "print-day.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == module.PRINT_DAY_SCHEMA_VERSION
    assert len(written["prints"]) == len(data["prints"]) == 5
    assert not (output / "stale.txt").exists()


def test_a_folder_that_is_not_print_day_output_is_not_replaced(
    evidence: Path, tmp_path: Path
) -> None:
    output = tmp_path / "keep"
    output.mkdir()
    (output / "mine.txt").write_text("mine\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not print-day output"):
        print_day().build_print_day(evidence, output)

    assert (output / "mine.txt").is_file()
