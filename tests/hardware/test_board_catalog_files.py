"""Board files in the catalog's data directory, and promoting one on its trials."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.cli.enclosure import _revision_board_file
from zcad_core.features.board_promotion import promote_board
from zcad_core.hardware import board_template, get_board
from zcad_core.hardware.electronics import boards
from zcad_core.hardware.electronics.board_file import (
    catalog_filename,
    check_board_data,
    load_catalog_boards,
)
from zcad_core.hardware.electronics.boards import (
    BOARD_DATA_DIRECTORY,
    build_board_catalog,
)

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def template(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(board_template())
    data.update(changes)

    return data


def write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")

    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the shipped data directory -------------------------------------------


def test_every_shipped_board_file_is_clean_and_verified() -> None:
    for board in load_catalog_boards(BOARD_DATA_DIRECTORY):
        assert board.warnings == (), board.identifier
        assert board.verified, board.identifier
        assert board.catalog


def test_the_catalog_still_holds_the_coded_boards() -> None:
    assert "RASPBERRY_PI_PICO_2" in boards.list_boards()


# --- loading a data directory ------------------------------------------------


def test_a_file_in_the_directory_joins_the_catalog(tmp_path: Path) -> None:
    write(
        tmp_path / "boards/example-board.json",
        template(verified_by="two trials, by hand"),
    )
    catalog = build_board_catalog(tmp_path / "boards")
    board = catalog.get("example_board")

    assert "EXAMPLE_BOARD" in catalog.identifiers()
    assert "RASPBERRY_PI_PICO_2" in catalog.identifiers()
    assert board.board_width_mm == 30.0


def test_a_missing_directory_adds_nothing(tmp_path: Path) -> None:
    catalog = build_board_catalog(tmp_path / "none")

    assert "EXAMPLE_BOARD" not in catalog.identifiers()


def test_a_catalogued_board_is_verified_only_if_it_says_by_what(
    tmp_path: Path,
) -> None:
    write(tmp_path / "example-board.json", template())
    write(
        tmp_path / "other-board.json",
        template(identifier="OTHER_BOARD", verified_by="two passing trials"),
    )
    found = {b.identifier: b for b in load_catalog_boards(tmp_path)}

    assert found["EXAMPLE_BOARD"].verified is False
    assert found["OTHER_BOARD"].verified is True
    assert found["OTHER_BOARD"].provenance()["kind"] == "catalog"
    assert "path" not in found["OTHER_BOARD"].provenance()
    assert found["OTHER_BOARD"].provenance()["verified_by"] == "two passing trials"


def test_a_file_not_named_for_its_board_is_refused(tmp_path: Path) -> None:
    write(tmp_path / "wrong.json", template())

    with pytest.raises(ValueError, match="example-board.json"):
        load_catalog_boards(tmp_path)


def test_an_invalid_file_is_refused(tmp_path: Path) -> None:
    write(tmp_path / "example-board.json", template(units="inch"))

    with pytest.raises(ValueError, match="units"):
        load_catalog_boards(tmp_path)


def test_an_unreviewed_file_is_refused(tmp_path: Path) -> None:
    write(tmp_path / "example-board.json", template(needs_review=["connector"]))

    with pytest.raises(ValueError, match="not reviewed"):
        load_catalog_boards(tmp_path)


def test_a_board_already_in_the_catalog_is_refused(tmp_path: Path) -> None:
    write(
        tmp_path / catalog_filename("RASPBERRY_PI_PICO_2"),
        template(identifier="RASPBERRY_PI_PICO_2"),
    )

    with pytest.raises(ValueError, match="already in the board catalog"):
        build_board_catalog(tmp_path)


def test_verified_by_must_say_something() -> None:
    assert not check_board_data(template(verified_by=" ")).valid


def test_a_users_own_file_is_never_verified_by_its_own_claim(
    tmp_path: Path,
) -> None:
    from zcad_core.hardware import load_board

    path = write(tmp_path / "mine.json", template(verified_by="trust me"))

    assert load_board(path).verified is False


# --- building from a catalogued data board --------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_a_catalogued_data_board_builds_and_is_recorded_as_catalog(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "boards/example-board.json",
        template(verified_by="two passing trials"),
    )
    monkeypatch.setattr(
        boards, "BOARD_CATALOG", build_board_catalog(tmp_path / "boards")
    )
    exit_code, output = run(
        capsys,
        "enclosure",
        "build",
        "--board",
        "example_board",
        "--output-directory",
        str(tmp_path / "out"),
        "--printer-profile",
        str(PRINTER_PROFILE),
    )

    assert exit_code == 0
    assert output["board"]["kind"] == "catalog"
    assert output["board"]["verified"] is True
    assert "path" not in output["board"]


def test_a_revision_refuses_a_catalog_board_that_has_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write(tmp_path / "example-board.json", template(verified_by="trials"))
    catalog = build_board_catalog(tmp_path)
    monkeypatch.setattr(boards, "BOARD_CATALOG", catalog)
    source = {
        "kind": "catalog",
        "identifier": "EXAMPLE_BOARD",
        "sha256": get_board("EXAMPLE_BOARD").origin.sha256,  # type: ignore[attr-defined]
    }

    assert _revision_board_file({"board_source": source}) is None

    with pytest.raises(ValueError, match="has changed"):
        _revision_board_file({"board_source": {**source, "sha256": "0" * 64}})


def test_a_coded_board_has_no_hash_to_check() -> None:
    source = {"kind": "catalog", "identifier": "RASPBERRY_PI_PICO_2"}

    assert _revision_board_file({"board_source": source}) is None


# --- promotion --------------------------------------------------------------


class Trials:
    """A board file built into an enclosure, with trial records to promote on."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.board = write(root / "board.json", template())
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            exit_code = main(
                [
                    "enclosure",
                    "build",
                    "--board-file",
                    str(self.board),
                    "--output-directory",
                    str(root / "build"),
                    "--printer-profile",
                    str(PRINTER_PROFILE),
                ]
            )

        assert exit_code == 0
        self.build_record = Path(json.loads(out.getvalue())["build_record"])

    def record(self, name: str, *, passed: bool = True, **changes: Any) -> Path:
        path = self.root / name / "enclosure-trial.json"
        data: dict[str, Any] = {
            "passed": passed,
            "trial_id": name,
            "design_name": "example-board-enclosure",
            "build_record_path": str(self.build_record),
            "build_record_sha256": sha(self.build_record),
            "printer_profile_id": "bambu-lab-a1-mini",
            "material_profile_id": "petg",
            "completed_at_utc": "2026-11-02T10:00:00+00:00",
            **changes,
        }

        return write(path, data)


@pytest.fixture(scope="module")
def trials(tmp_path_factory: pytest.TempPathFactory) -> Trials:
    return Trials(tmp_path_factory.mktemp("trials"))


def two(trials: Trials) -> list[Path]:
    return [trials.record("trial-001"), trials.record("trial-002")]


def test_two_passing_trials_promote_a_board(trials: Trials, tmp_path: Path) -> None:
    target = promote_board(trials.board, two(trials), tmp_path / "boards")

    assert target.name == "example-board.json"

    promoted = json.loads(target.read_text())

    assert "2 passing trials" in promoted["verified_by"]
    assert sha(trials.board) in promoted["verified_by"]
    assert "trial-001" in promoted["verified_by"]
    assert {k: v for k, v in promoted.items() if k != "verified_by"} == template()

    board = build_board_catalog(tmp_path / "boards").get("EXAMPLE_BOARD")

    assert board.verified is True  # type: ignore[attr-defined]


def test_one_trial_is_not_enough(trials: Trials, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs 2 passing trials"):
        promote_board(trials.board, two(trials)[:1], tmp_path)


def test_the_same_trial_twice_is_one_trial(trials: Trials, tmp_path: Path) -> None:
    record = trials.record("trial-001")

    with pytest.raises(ValueError, match="1 given"):
        promote_board(trials.board, [record, record], tmp_path)


def test_a_failed_trial_does_not_count(trials: Trials, tmp_path: Path) -> None:
    records = [trials.record("trial-001"), trials.record("trial-002", passed=False)]

    with pytest.raises(ValueError, match="not a passing trial"):
        promote_board(trials.board, records, tmp_path)


def test_trials_of_another_version_of_the_file_do_not_count(
    trials: Trials, tmp_path: Path
) -> None:
    edited = write(tmp_path / "edited.json", template(name="Edited"))

    with pytest.raises(ValueError, match="different version"):
        promote_board(edited, two(trials), tmp_path / "boards")


def test_a_build_record_changed_since_its_trial_is_refused(
    trials: Trials, tmp_path: Path
) -> None:
    records = [
        trials.record("trial-001"),
        trials.record("trial-002", build_record_sha256="0" * 64),
    ]

    with pytest.raises(ValueError, match="has changed since the trial"):
        promote_board(trials.board, records, tmp_path / "boards")


def test_a_file_with_warnings_is_refused(trials: Trials, tmp_path: Path) -> None:
    data = template()
    del data["mounting_holes"]
    path = write(tmp_path / "board.json", data)

    with pytest.raises(ValueError, match="no warnings"):
        promote_board(path, two(trials), tmp_path / "boards")


def test_a_board_the_catalog_already_has_is_refused(
    trials: Trials, tmp_path: Path
) -> None:
    path = write(tmp_path / "board.json", template(identifier="RASPBERRY_PI_PICO_2"))

    with pytest.raises(ValueError, match="already in the board catalog"):
        promote_board(path, two(trials), tmp_path / "boards")


def test_an_existing_file_is_not_overwritten(trials: Trials, tmp_path: Path) -> None:
    promote_board(trials.board, two(trials), tmp_path / "boards")

    with pytest.raises(FileExistsError):
        promote_board(trials.board, two(trials), tmp_path / "boards")


def test_the_command_promotes_into_a_directory(
    capsys: pytest.CaptureFixture[str], trials: Trials, tmp_path: Path
) -> None:
    records = two(trials)
    exit_code, output = run(
        capsys,
        "board",
        "promote",
        str(trials.board),
        "--trial-record",
        str(records[0]),
        "--trial-record",
        str(records[1]),
        "--catalog-directory",
        str(tmp_path / "boards"),
    )

    assert exit_code == 0
    assert Path(output["written"]).name == "example-board.json"
