"""Writing a guide file from a master part's holes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.guide import build_guide
from zcad_core.features.guide_file import check_guide_data, inspect_guide_file
from zcad_core.features.guide_import import import_guide
from zcad_core.profiles import load_printer_profile

PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PROFILE_PATH)


def block(width: float, depth: float, height: float) -> cq.Workplane:
    return cq.Workplane("XY").box(width, depth, height, centered=(True, True, False))


def step_of(directory: Path, name: str, model: cq.Workplane) -> Path:
    path = directory / name
    cq.exporters.export(model, str(path))

    return path


@pytest.fixture(scope="module")
def master(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 60 x 40 x 10 plate with three 5 mm holes and one 8 mm hole."""

    plate = block(60, 40, 10)
    plate = (
        plate.faces(">Z")
        .workplane()
        .pushPoints([(-20, -10), (20, -10), (0, 12)])
        .hole(5)
    )
    plate = plate.faces(">Z").workplane().pushPoints([(-20, 12)]).hole(8)

    return step_of(tmp_path_factory.mktemp("master"), "master.step", plate)


@pytest.fixture(scope="module")
def blank(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return step_of(tmp_path_factory.mktemp("blank"), "blank.step", block(60, 40, 12))


def holes(data: dict[str, Any]) -> dict[str, tuple[float, float, float | None]]:
    return {
        b["identifier"]: (b["x_mm"], b["y_mm"], b.get("diameter_mm"))
        for b in data["bores"]
    }


def test_each_round_through_hole_becomes_a_bore(master: Path, blank: Path) -> None:
    imported = import_guide(master, target=blank)
    found = sorted(holes(imported.data).values())

    assert imported.report["holes"] == 4
    assert imported.report["hole_diameters_mm"] == {"5.00": 3, "8.00": 1}
    assert [(x, y) for x, y, _ in found] == [
        (-20.0, -10.0),
        (-20.0, 12.0),
        (0.0, 12.0),
        (20.0, -10.0),
    ]


def test_the_commonest_size_is_the_drill_and_others_say_theirs(
    master: Path, blank: Path
) -> None:
    imported = import_guide(master, target=blank)

    assert imported.data["drill"]["diameter_mm"] == 5.0
    assert imported.report["drill_diameter_mm"] == 5.0
    sizes = {name: size for name, (_, _, size) in holes(imported.data).items()}

    assert sorted(v for v in sizes.values() if v is not None) == [8.0]


def test_the_file_is_refused_until_the_drill_is_set(master: Path, blank: Path) -> None:
    imported = import_guide(master, target=blank)
    report = check_guide_data(imported.data)

    assert imported.data["needs_review"]
    assert any("not reviewed" in error for error in report.errors)


def test_a_reviewed_file_builds_with_the_holes_where_they_were(
    master: Path, blank: Path, tmp_path: Path
) -> None:
    data = import_guide(master, target=blank).data
    del data["needs_review"]
    data["drill"]["chuck_diameter_mm"] = 14.0
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data))
    report, spec, part = inspect_guide_file(path, PROFILE)

    assert report.valid, report.errors
    assert spec is not None and part is not None

    guide = build_guide(spec, part, PROFILE)

    assert guide.passed, (guide.checks, guide.problems)
    assert len(guide.bores) == 4


def test_the_source_names_the_master_by_hash(master: Path, blank: Path) -> None:
    imported = import_guide(master, target=blank)

    assert imported.report["master"]["sha256"] in imported.data["source"]
    assert "not checked against the real part" in imported.data["source"]
    assert imported.data["part"]["sha256"] != imported.report["master"]["sha256"]


def test_an_offset_moves_every_hole(master: Path, blank: Path) -> None:
    plain = holes(import_guide(master, target=blank).data)
    moved = holes(import_guide(master, target=blank, offset_mm=(2.5, -1.0)).data)

    for name, (x, y, _) in plain.items():
        assert moved[name][:2] == (pytest.approx(x + 2.5), pytest.approx(y - 1.0))


def test_holes_off_the_target_are_listed_and_need_review(
    master: Path, tmp_path: Path
) -> None:
    small = step_of(tmp_path, "small.step", block(30, 40, 12))
    imported = import_guide(master, target=small)

    # The target is 30 mm wide: the holes at x = +-20 fall off it, the one at 0
    # does not.
    off = {name for name, (x, _, _) in holes(imported.data).items() if abs(x) > 15}

    assert off
    assert set(imported.report["outside_target"]) == off
    assert any(
        "fall outside the target" in note for note in imported.data["needs_review"]
    )


def test_a_part_that_is_its_own_master_is_re_drilled(master: Path) -> None:
    imported = import_guide(master)

    assert imported.data["part"]["step"] == str(master)
    assert imported.report["holes"] == 4
    assert imported.report["outside_target"] == []


def test_a_master_with_no_holes_is_refused(blank: Path) -> None:
    with pytest.raises(ValueError, match="no round through-hole"):
        import_guide(blank)


def test_a_small_hole_is_found_when_the_minimum_is_lowered(tmp_path: Path) -> None:
    plate = block(40, 40, 8).faces(">Z").workplane().hole(1.2)
    step = step_of(tmp_path, "pin.step", plate)

    with pytest.raises(ValueError, match="no round through-hole"):
        import_guide(step)

    assert import_guide(step, minimum_hole_mm=1.0).report["holes"] == 1


def test_a_master_solid_that_is_not_there_is_refused(master: Path) -> None:
    with pytest.raises(ValueError, match="must be 1 to 1"):
        import_guide(master, master_solid_index=4)


def test_the_largest_solid_is_the_master_in_a_model_of_several(tmp_path: Path) -> None:
    plate = block(60, 40, 10).faces(">Z").workplane().hole(6).val()
    pin = cq.Solid.makeBox(5, 5, 5, pnt=cq.Vector(100, 100, 0))
    assert isinstance(plate, cq.Shape)
    both = cq.Workplane("XY").add([plate, pin])
    step = step_of(tmp_path, "pair.step", both)
    imported = import_guide(step)

    assert imported.report["holes"] == 1
    assert imported.data["part"]["solid_index"] == imported.report["master_solid_index"]


def test_a_part_with_no_flat_top_is_given_a_ledge_nest(
    master: Path, tmp_path: Path
) -> None:
    base = cq.Workplane("XY").circle(20).extrude(10)
    dome = base.union(cq.Workplane("XY").sphere(12).translate((0, 0, 10)))
    step = step_of(tmp_path, "dome.step", dome)
    imported = import_guide(master, target=step)

    assert imported.data["nest"]["bearing"] == "ledge"
    assert imported.data["nest"]["gap_mm"] == 1.0
    assert any("ledge nest" in note for note in imported.data["needs_review"])


# --- the command ------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_command_writes_the_file_and_says_what_to_review(
    capsys: pytest.CaptureFixture[str], master: Path, blank: Path, tmp_path: Path
) -> None:
    output = tmp_path / "guide.json"
    exit_code, report = run(
        capsys,
        "guide",
        "import",
        "--holes-from",
        str(master),
        "--part",
        str(blank),
        "--output",
        str(output),
        "--offset",
        "1.5,-2",
    )

    assert exit_code == 0
    assert report["written"] == str(output)
    assert report["holes"] == 4
    assert report["offset_mm"] == [1.5, -2.0]
    assert report["needs_review"]
    assert json.loads(output.read_text())["bores"]


def test_the_command_does_not_overwrite(
    capsys: pytest.CaptureFixture[str], master: Path, tmp_path: Path
) -> None:
    output = tmp_path / "guide.json"
    output.write_text("{}")

    assert (
        main(["guide", "import", "--holes-from", str(master), "--output", str(output)])
        == 1
    )
    capsys.readouterr()


def test_a_bad_offset_is_refused(
    capsys: pytest.CaptureFixture[str], master: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "guide",
                "import",
                "--holes-from",
                str(master),
                "--output",
                str(tmp_path / "g.json"),
                "--offset",
                "left",
            ]
        )

    assert "is not X,Y" in capsys.readouterr().err
