"""Print records for PCB test fixtures: starting and completing a trial, what a
build needs to be verified, and the measured accuracy a profile pools."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.pcb_fixture_file import fixture_template
from zcad_core.features.pcb_fixture_trial import (
    FixtureTrialDisposition,
    complete_fixture_trial,
    fixture_verification,
    start_fixture_trial,
)
from zcad_core.hardware import board_template
from zcad_core.profiles.fixture_accuracy import (
    derive_fixture_profile,
    load_fixture_profile,
    write_fixture_profile,
)

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def write_board(directory: Path) -> Path:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = [
        {
            "identifier": "HEADER",
            "center_x_mm": 0,
            "center_y_mm": -5,
            "width_mm": 20,
            "depth_mm": 3,
            "height_mm": 8.5,
            "bottom_offset_from_board_top_mm": 0.0,
        }
    ]
    data["test_points"] = [
        {"identifier": "TP1", "x_mm": -8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
        {"identifier": "TP2", "x_mm": 8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
        {"identifier": "TP3", "x_mm": 0.0, "y_mm": 5.0, "pad_diameter_mm": 3.0},
    ]
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def build(
    directory: Path, *extra: str, closure: str = "screws"
) -> tuple[Path, dict[str, Any]]:
    """Build the example fixture and give back its build record and the CLI's
    output."""

    board = write_board(directory)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["closure"] = closure
    path = directory / "fixture.json"
    path.write_text(json.dumps(data))
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(
            [
                "fixture",
                "build",
                "--fixture-file",
                str(path),
                "--output-directory",
                str(directory / "out"),
                "--printer-profile",
                str(PRINTER_PROFILE),
                *extra,
            ]
        )

    assert code == 0
    output = json.loads(out.getvalue())

    return Path(output["build_record"]), output


def record_of(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def fill(
    trial: Path,
    *,
    result: str = "pass",
    contact: bool = True,
    offsets: dict[str, tuple[float, float]] | None = None,
) -> None:
    """Fill a trial's templates: every check ``result``, every point's contact,
    and each tip found ``offsets`` from its pad's centre (a quarter millimetre
    by default)."""

    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())

    for name, entry in measurements["points"].items():
        dx, dy = (offsets or {}).get(name, (0.25, -0.1))
        entry["contact"] = contact
        entry["offset_x_mm"] = dx
        entry["offset_y_mm"] = dy

    (trial / "measurements.json").write_text(json.dumps(measurements))


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory.mktemp("built"))[0]


def fresh(tmp_path: Path) -> tuple[Path, Path]:
    """A new build and a new trial of it, filled in to pass."""

    record, _ = build(tmp_path)
    trial = start_fixture_trial(record)
    fill(trial)

    return record, trial


# --- starting a trial ---------------------------------------------------------------


def test_a_trial_lists_every_check_and_every_probed_point(built: Path) -> None:
    trial = start_fixture_trial(built)
    names = set(json.loads((trial / "observations.json").read_text()))
    template = json.loads((trial / "measurements.json").read_text())

    assert names == {
        "board_seats_in_nest",
        "board_releases",
        "plate_seats_on_rim",
        "plate_stays_down",
        "pins_travel_freely",
    }
    assert set(template["points"]) == {"TP1", "TP2", "TP3"}
    assert template["points"]["TP1"]["slack_mm"] == 1.2
    assert template["points"]["TP1"]["contact"] is None
    assert "board's own frame" in template["frame"]


def test_each_trial_gets_the_next_number(built: Path) -> None:
    first = start_fixture_trial(built).name
    second = start_fixture_trial(built).name

    assert first != second
    assert second > first


# --- completing it ------------------------------------------------------------------


def test_a_filled_in_trial_is_recorded_with_each_points_offset_and_slack_used(
    tmp_path: Path,
) -> None:
    _, trial = fresh(tmp_path)
    path = complete_fixture_trial(
        trial,
        disposition=FixtureTrialDisposition.PASS,
        material_profile_id="petg",
        notes="first print",
    )
    record = record_of(path)
    tp1 = next(p for p in record["points"] if p["identifier"] == "TP1")

    assert record["passed"] is True
    assert record["material_profile_id"] == "petg"
    assert record["printer_profile_id"] == "bambu-lab-a1-mini"
    assert tp1["offset_mm"] == {"dx": 0.25, "dy": -0.1, "radial": 0.269}
    # 0.269 mm of a 1.2 mm slack.
    assert tp1["share_of_slack"] == pytest.approx(0.224, abs=0.001)
    assert tp1["assumed_misalignment_mm"] > tp1["offset_mm"]["radial"]
    assert record["summary"]["points_in_contact"] == 3
    assert record["summary"]["offsets_measured"] == 3
    assert record["summary"]["offsets_over_slack"] == 0
    assert record["notes"] == "first print"


def test_a_completed_trial_is_never_overwritten(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    complete_fixture_trial(
        trial,
        disposition=FixtureTrialDisposition.PASS,
        material_profile_id="petg",
    )

    with pytest.raises(FileExistsError, match="already completed"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_trial_must_answer_every_check(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    observations = json.loads((trial / "observations.json").read_text())
    observations["plate_stays_down"]["result"] = "pending"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="must be pass or fail"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_passing_trial_cannot_have_a_failed_check(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    observations = json.loads((trial / "observations.json").read_text())
    observations["board_releases"]["result"] = "fail"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_passing_trial_has_every_point_in_contact(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["points"]["TP2"]["contact"] = False
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match=r"every point in contact; missed: \['TP2'\]"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_passing_trial_answers_contact_for_every_point(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["points"]["TP3"]["contact"] = None
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match=r"not answered: \['TP3'\]"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_failed_trial_may_leave_offsets_unmeasured(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())

    for entry in measurements["points"].values():
        entry["offset_x_mm"] = entry["offset_y_mm"] = None

    measurements["points"]["TP2"]["contact"] = False
    (trial / "measurements.json").write_text(json.dumps(measurements))
    path = complete_fixture_trial(
        trial,
        disposition=FixtureTrialDisposition.FAIL,
        material_profile_id="petg",
    )
    record = record_of(path)

    assert record["passed"] is False
    assert record["summary"]["offsets_measured"] == 0
    assert record["summary"]["points_in_contact"] == 2


def test_an_inconclusive_trial_needs_something_to_go_on(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())

    for entry in measurements["points"].values():
        entry["contact"] = None
        entry["offset_x_mm"] = entry["offset_y_mm"] = None

    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="needs at least one offset"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.INCONCLUSIVE,
            material_profile_id="petg",
        )


def test_half_an_offset_is_refused(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["points"]["TP1"]["offset_y_mm"] = None
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="both offset_x_mm and offset_y_mm"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_point_the_fixture_does_not_probe_is_refused(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["points"]["TP9"] = {"contact": True}
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="does not probe: \\['TP9'\\]"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_contact_that_is_not_true_or_false_is_refused(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["points"]["TP1"]["contact"] = "yes"
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(TypeError, match="contact must be true or false"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_an_offset_beyond_the_slack_is_counted(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    fill(trial, offsets={"TP1": (1.5, 0.0)})
    path = complete_fixture_trial(
        trial,
        disposition=FixtureTrialDisposition.PASS,
        material_profile_id="petg",
    )
    record = record_of(path)

    assert record["summary"]["offsets_over_slack"] == 1
    assert record["summary"]["max_radial_mm"] == 1.5


def test_trials_past_the_slack_pass_but_do_not_verify_the_fixture(
    tmp_path: Path,
) -> None:
    # A tip past its pad's slack made contact by luck: the trial passes and its
    # offsets pool, but it does not vouch for the fixture.
    built, trial = fresh(tmp_path)
    fill(trial, offsets={"TP1": (1.5, 0.0)})
    complete_fixture_trial(
        trial, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )
    second = start_fixture_trial(built)
    fill(second, offsets={"TP1": (1.5, 0.0)})
    complete_fixture_trial(
        second, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )
    status = fixture_verification(built)

    assert status["passing_trials"] == 2
    assert status["passing_within_slack"] == 0
    assert status["verified"] is False


def test_a_part_changed_since_it_was_built_is_refused(tmp_path: Path) -> None:
    record, trial = fresh(tmp_path)
    stl = Path(record_of(record)["parts"]["plate"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="printed plate no longer matches"):
        complete_fixture_trial(
            trial,
            disposition=FixtureTrialDisposition.PASS,
            material_profile_id="petg",
        )


# --- verification ----------------------------------------------------------------------


def test_two_passing_trials_of_one_build_verify_it(tmp_path: Path) -> None:
    record, first = fresh(tmp_path)
    complete_fixture_trial(
        first, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )

    assert fixture_verification(record)["verified"] is False

    second = start_fixture_trial(record)
    fill(second)
    complete_fixture_trial(
        second, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )
    status = fixture_verification(record)

    assert status["verified"] is True
    assert status["passing_trials"] == 2
    assert status["trials"][0]["points_in_contact"] == 3


def test_a_failed_trial_does_not_count_toward_verification(tmp_path: Path) -> None:
    record, first = fresh(tmp_path)
    complete_fixture_trial(
        first, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )
    second = start_fixture_trial(record)
    fill(second, contact=False)
    complete_fixture_trial(
        second, disposition=FixtureTrialDisposition.FAIL, material_profile_id="petg"
    )

    assert fixture_verification(record)["passing_trials"] == 1


def test_trials_of_an_older_build_no_longer_count(tmp_path: Path) -> None:
    record, trial = fresh(tmp_path)
    complete_fixture_trial(
        trial, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )
    # Any change to the record, as a rebuild would make.
    data = record_of(record)
    data["identifier"] = data["identifier"] + "-b"
    record.write_text(json.dumps(data))
    status = fixture_verification(record)

    assert status["passing_trials"] == 0
    assert status["trials"][0]["of_this_build"] is False


# --- the accuracy profile ------------------------------------------------------------


def two_passing(root: Path, offsets: tuple[float, float] = (0.25, -0.1)) -> None:
    for name in ("a", "b"):
        directory = root / name
        directory.mkdir(parents=True)
        record, _ = build(directory)
        trial = start_fixture_trial(record)
        fill(trial, offsets={p: offsets for p in ("TP1", "TP2", "TP3")})
        complete_fixture_trial(
            trial, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
        )


def test_a_profile_pools_the_offsets_of_passing_trials(tmp_path: Path) -> None:
    two_passing(tmp_path)
    profile = derive_fixture_profile(
        tmp_path, printer_profile_id="bambu-lab-a1-mini", material_profile_id="petg"
    )
    position = profile["figures"]["position"]

    assert profile["version"] == 1 and profile["trials"] == 2
    assert position["samples"] == 6
    assert position["max"] == pytest.approx(0.269)
    assert position["bias_mm"] == [0.25, -0.1]
    assert profile["figures"]["contact"] == {"points": 6, "in_contact": 6}
    assert profile["figures"]["max_share_of_slack"] == pytest.approx(0.224, abs=0.001)


def test_a_profile_needs_two_passing_trials(tmp_path: Path) -> None:
    _, trial = fresh(tmp_path)
    complete_fixture_trial(
        trial, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )

    with pytest.raises(ValueError, match="needs at least 2"):
        derive_fixture_profile(
            tmp_path,
            printer_profile_id="bambu-lab-a1-mini",
            material_profile_id="petg",
        )


def test_trials_of_another_material_are_not_pooled(tmp_path: Path) -> None:
    two_passing(tmp_path)

    with pytest.raises(ValueError, match="0 passing fixture trial"):
        derive_fixture_profile(
            tmp_path,
            printer_profile_id="bambu-lab-a1-mini",
            material_profile_id="pla",
        )


def test_a_profile_only_moves_to_the_next_version(tmp_path: Path) -> None:
    two_passing(tmp_path / "evidence")
    first = derive_fixture_profile(
        tmp_path / "evidence",
        printer_profile_id="bambu-lab-a1-mini",
        material_profile_id="petg",
    )
    path = tmp_path / "profiles" / "p.json"
    write_fixture_profile(first, path)

    with pytest.raises(FileExistsError, match="next version"):
        write_fixture_profile(first, path)

    second = derive_fixture_profile(
        tmp_path / "evidence",
        printer_profile_id="bambu-lab-a1-mini",
        material_profile_id="petg",
        previous=first,
    )
    write_fixture_profile(second, path)

    assert load_fixture_profile(path).payload["version"] == 2
    assert load_fixture_profile(path).payload["history"][0]["version"] == 1


# --- a build given the profile ---------------------------------------------------------


def profile_path(tmp_path: Path, offsets: tuple[float, float]) -> Path:
    two_passing(tmp_path / "evidence", offsets)
    path = tmp_path / "profile.json"
    write_fixture_profile(
        derive_fixture_profile(
            tmp_path / "evidence",
            printer_profile_id="bambu-lab-a1-mini",
            material_profile_id="petg",
        ),
        path,
    )

    return path


def test_a_build_reports_the_measured_offsets_beside_the_sum(tmp_path: Path) -> None:
    profile = profile_path(tmp_path, (0.25, -0.1))
    directory = tmp_path / "next"
    directory.mkdir()
    record, output = build(directory, "--accuracy-profile", str(profile))
    measured = output["measured_accuracy"]

    assert measured["described"].endswith("2 passing trials")
    assert "not a guarantee" in measured["note"]
    assert all(not p["measured_max_exceeds_slack"] for p in measured["points"])
    assert all(not p["measured_max_exceeds_assumed"] for p in measured["points"])
    assert measured["warnings"] == []

    stored = record_of(record)

    assert stored["material_profile_id"] == "petg"
    assert stored["measured_accuracy"]["profile"]["sha256"]
    assert stored["verified"] is False


def test_a_measured_offset_over_the_slack_is_warned_of(tmp_path: Path) -> None:
    profile = profile_path(tmp_path, (1.4, 0.0))
    directory = tmp_path / "next"
    directory.mkdir()
    _, output = build(directory, "--accuracy-profile", str(profile))

    assert any("more than this pad's" in w for w in output["warnings"])
    assert all(
        p["measured_max_exceeds_slack"] for p in output["measured_accuracy"]["points"]
    )


def test_a_profile_for_another_material_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    profile = profile_path(tmp_path, (0.25, -0.1))
    directory = tmp_path / "next"
    directory.mkdir()
    board = write_board(directory)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    (directory / "fixture.json").write_text(json.dumps(data))
    capsys.readouterr()
    code = main(
        [
            "fixture",
            "build",
            "--fixture-file",
            str(directory / "fixture.json"),
            "--output-directory",
            str(directory / "out"),
            "--printer-profile",
            str(PRINTER_PROFILE),
            "--accuracy-profile",
            str(profile),
            "--material-profile",
            "pla",
        ]
    )

    assert code == 1
    assert "accuracy profile is for petg" in capsys.readouterr().err


# --- the commands --------------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_commands_take_a_fixture_from_build_to_verified(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    record, _ = build(tmp_path)
    capsys.readouterr()

    for number in (1, 2):
        _, started = run(
            capsys, "fixture", "trial", "start", "--build-record", str(record)
        )
        trial = Path(started["trial"])
        fill(trial)
        code, completed = run(
            capsys,
            "fixture",
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--disposition",
            "pass",
        )

        assert code == 0
        assert completed["summary"]["points_in_contact"] == 3

        code, status = run(capsys, "fixture", "status", "--build-record", str(record))

        assert code == (0 if number == 2 else 1)
        assert status["verified"] is (number == 2)


def test_the_derive_command_writes_a_profile(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    two_passing(tmp_path / "evidence")
    capsys.readouterr()
    output = tmp_path / "profiles" / "fixtures.json"
    code, result = run(
        capsys,
        "fixture",
        "derive",
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--output",
        str(output),
    )

    assert code == 0 and output.is_file()
    assert result["version"] == 1 and result["trials"] == 2


def test_a_hinged_fixtures_trial_adds_the_swing_check(tmp_path: Path) -> None:
    record, _ = build(tmp_path, closure="hinge")
    trial = start_fixture_trial(record)
    names = set(json.loads((trial / "observations.json").read_text()))

    assert "plate_swings_free" in names and len(names) == 6

    fill(trial)
    path = complete_fixture_trial(
        trial, disposition=FixtureTrialDisposition.PASS, material_profile_id="petg"
    )

    assert record_of(path)["passed"] is True
    assert "plate_swings_free" in {o["check"] for o in record_of(path)["observations"]}
