"""A holding nest: a tray with a floor and a wall round a part's shadow."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.nest import (
    build_nest,
    notch_sites,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.nest_core import clear, lifts_out, pocketed
from zcad_core.features.nest_file import (
    check_nest_data,
    check_nest_file,
    inspect_nest_file,
    load_nest,
    nest_template,
)
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PRINTER_PATH)


def block(width: float, depth: float, height: float) -> cq.Workplane:
    return cq.Workplane("XY").box(width, depth, height, centered=(True, True, False))


@pytest.fixture(scope="module")
def slab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 50 x 30 x 16 block."""

    path = tmp_path_factory.mktemp("slab") / "slab.step"
    cq.exporters.export(block(50, 30, 16), str(path))

    return path


@pytest.fixture(scope="module")
def mushroom(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 30 x 30 head, 4 mm thick, on a 10 x 10 stem 12 mm tall: wider at the top."""

    path = tmp_path_factory.mktemp("mushroom") / "mushroom.step"
    model = block(10, 10, 12).union(block(30, 30, 4).translate((0, 0, 12)))
    cq.exporters.export(model, str(path))

    return path


def write_nest(directory: Path, part: Path, **changes: Any) -> Path:
    data = copy.deepcopy(nest_template(part))
    data["source"] = "a block for tests"
    data["nest"]["depth_mm"] = 8.0

    for key, value in changes.items():
        if key in data["nest"] or key in ("depth_mm",):
            data["nest"][key] = value
        elif key == "features":
            data["features"] = value
        else:
            data[key] = value

    path = directory / "nest.json"
    path.write_text(json.dumps(data))

    return path


def inside(shape: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, shape.val()).Solids()
    )


def built(directory: Path, part: Path, **changes: Any) -> Any:
    report, spec, loaded = inspect_nest_file(
        write_nest(directory, part, **changes), PROFILE
    )

    assert report.valid, report.errors
    assert spec is not None and loaded is not None

    return build_nest(spec, loaded, PROFILE)


@pytest.fixture(scope="module")
def nest(slab: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    return built(tmp_path_factory.mktemp("nest"), slab)


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


# --- the file -----------------------------------------------------------------------------------


def test_the_template_names_a_part_by_its_real_hash(slab: Path) -> None:
    data = nest_template(slab)

    assert len(data["part"]["sha256"]) == 64 and data["part"]["sha256"] != "0" * 64
    assert check_nest_data(data).valid
    assert data["features"] == {"finger_notches": 2}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(file_kind="guide"), "file_kind must be"),
        (lambda d: d.update(colour="red"), "Unknown field"),
        (lambda d: d["nest"].update(depth_mm=0.1), "nest.depth_mm"),
        (lambda d: d["nest"].update(wall_mm=0.2), "nest.wall_mm"),
        (lambda d: d["nest"].update(floor_mm=99), "nest.floor_mm"),
        (lambda d: d["nest"].update(flange_mm=-1), "nest.flange_mm"),
        (lambda d: d["nest"].update(bearing="top"), "unknown fields: bearing"),
        (lambda d: d["features"].update(finger_notches=5), "outside 0 to 4"),
        (lambda d: d["features"].update(finger_notches=1.5), "whole number"),
        (lambda d: d["features"].update(grip=1), "unknown fields: grip"),
        (lambda d: d["features"].update(lip={"tabs": 9}), "features.lip.tabs"),
        (
            lambda d: (
                d["features"].update(lip={"tabs": 2}) or d["nest"].update(depth_mm=5)
            ),
            "cannot be set with a lip",
        ),
        (
            lambda d: d["features"].update(strap={"width_mm": 20, "thickness_mm": 1.5}),
            "features.strap.source",
        ),
        (lambda d: d["features"].update(label="x" * 30), "the most is 24"),
        (lambda d: d["part"].update(sha256="abc"), "part.sha256"),
        (lambda d: d.update(needs_review="unchecked"), "not reviewed"),
    ],
)
def test_a_nest_file_that_cannot_be_right_is_refused(change: Any, message: str) -> None:
    data = nest_template()
    change(data)
    report = check_nest_data(data)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_the_pocket_is_half_the_parts_height_unless_the_file_says_otherwise(
    slab: Path, tmp_path: Path
) -> None:
    data = nest_template(slab)
    data["source"] = "x"
    data["nest"].pop("depth_mm", None)
    path = tmp_path / "nest.json"
    path.write_text(json.dumps(data))
    report = check_nest_file(path, PROFILE)

    assert report.valid, report.errors
    assert report.part is not None
    assert report.part["pocket_depth_mm"] == 8.0
    assert report.part["height_mm"] == 16.0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"depth_mm": 30.0}, "deeper than the part's"),
        ({"wall_mm": 0.9}, "minimum wall"),
        ({"floor_mm": 0.9}, "minimum floor"),
    ],
)
def test_a_nest_the_part_or_the_printer_cannot_take_is_refused(
    slab: Path, tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    report = check_nest_file(write_nest(tmp_path, slab, **changes), PROFILE)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_nest_is_refused_if_its_part_has_changed(slab: Path, tmp_path: Path) -> None:
    path = write_nest(tmp_path, slab)
    other = tmp_path / "other.step"
    cq.exporters.export(block(40, 30, 16), str(other))
    data = json.loads(path.read_text())
    data["part"]["step"] = str(other)
    path.write_text(json.dumps(data))
    report = check_nest_file(path, PROFILE)

    assert not report.valid
    assert any("has changed since" in e for e in report.errors)


# --- the notch sites ----------------------------------------------------------------------------


def test_notches_go_in_the_middle_of_the_longest_stretches() -> None:
    rectangle = ((-25.0, -15.0), (25.0, -15.0), (25.0, 15.0), (-25.0, 15.0))
    sites, problems = notch_sites(rectangle, 2)

    assert not problems
    assert [round(n.stretch_mm) for n in sites] == [50, 50]
    assert sorted(n.centre for n in sites) == [(0.0, -15.0), (0.0, 15.0)]
    # Outward from the middle of the stretch, away from the outline's inside.
    by_y = {n.centre[1]: n.outward for n in sites}
    assert by_y[15.0] == pytest.approx((0.0, 1.0)) and by_y[-15.0] == pytest.approx(
        (0.0, -1.0)
    )


def test_the_outlines_direction_does_not_change_where_a_notch_faces() -> None:
    clockwise = ((-25.0, 15.0), (25.0, 15.0), (25.0, -15.0), (-25.0, -15.0))
    sites, _ = notch_sites(clockwise, 2)
    by_y = {n.centre[1]: n.outward for n in sites}

    assert by_y[15.0] == pytest.approx((0.0, 1.0)) and by_y[-15.0] == pytest.approx(
        (0.0, -1.0)
    )


def test_too_few_long_stretches_is_refused_and_counted() -> None:
    small = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    sites, problems = notch_sites(small, 1)

    assert sites == () and problems
    assert "have 1 straight stretches" not in problems[0]
    assert "has 0" in problems[0] and "at least 18 mm" in problems[0]
    assert notch_sites(small, 0) == ((), [])


# --- the solids ---------------------------------------------------------------------------------


def test_a_nest_is_one_solid_the_part_fits_and_lifts_out_of(nest: Any) -> None:
    assert nest.passed, (nest.checks, nest.problems)
    assert nest.checks == {
        "one_solid": True,
        "part_fits_pocket": True,
        "part_lifts_out": True,
        "notches_open": True,
    }
    assert nest.depth_mm == 8.0
    assert nest.clearance_mm == 0.2


def test_the_tray_has_a_floor_a_wall_a_flange_and_a_pocket(nest: Any) -> None:
    body = nest.body
    box = body.val().BoundingBox()

    # 50 mm part (its shadow is found on a grid, so a pixel or so wider), the clearance and
    # wall each side, and an 8 mm flange: 70.4 mm; the floor and the wall's 8 mm make it 10 mm tall.
    assert box.xlen == pytest.approx(50 + 2 * (0.2 + 2.0 + 8.0), abs=0.3)
    assert box.zlen == pytest.approx(2.0 + 8.0, abs=0.01)
    # The floor under the part (the part's bottom is z = -16) and its flange beyond the wall.
    assert inside(body, 0.0, 0.0, -17.0)
    assert inside(body, 25 + 0.2 + 2.0 + 4.0, 0.0, -17.0)
    assert not inside(body, 25 + 0.2 + 2.0 + 9.0, 0.0, -17.0)
    # The wall's thickness at the end of the part, and the pocket inside it.
    assert inside(body, 25 + 0.2 + 1.0, 0.0, -12.0)
    assert not inside(body, 24.0, 0.0, -12.0)
    assert not inside(body, 25 + 0.2 + 2.0 + 1.0, 0.0, -12.0)


def test_each_notch_is_cut_through_the_wall_to_the_floor(nest: Any) -> None:
    body = nest.body

    assert len(nest.notches) == 2
    # The middle of each long wall is cut away, the floor stays, and the wall beside it stays.
    assert not inside(body, 0.0, 15 + 0.2 + 1.0, -12.0)
    assert not inside(body, 0.0, -(15 + 0.2 + 1.0), -9.0)
    assert inside(body, 0.0, 15 + 0.2 + 1.0, -16.5)
    assert inside(body, 20.0, 15 + 0.2 + 1.0, -12.0)
    assert inside(body, 3.0 + 6.5, 15 + 0.2 + 1.0, -12.0)


def test_a_nest_with_no_notches_or_no_flange_leaves_them_out(
    slab: Path, tmp_path: Path
) -> None:
    plain = built(tmp_path, slab, features={"finger_notches": 0}, flange_mm=0.0)
    box = plain.body.val().BoundingBox()

    assert plain.passed and plain.notches == ()
    assert box.xlen == pytest.approx(50 + 2 * 2.2, abs=0.3)
    assert inside(plain.body, 0.0, 15 + 0.2 + 1.0, -12.0)


def test_a_part_wider_at_the_top_lifts_straight_out_of_its_pocket(
    mushroom: Path, tmp_path: Path
) -> None:
    nest = built(tmp_path, mushroom, features={"finger_notches": 2}, depth_mm=10.0)

    assert nest.passed, nest.checks
    # The pocket follows the head's shadow, so it is loose round the stem.
    assert not inside(nest.body, 14.0, 0.0, -10.0)


def test_a_block_has_room_for_a_notch_on_each_of_its_four_sides(
    slab: Path, tmp_path: Path
) -> None:
    # The block has four stretches of 18 mm or more, so four notches fit; a fifth is refused by
    # the file.
    four = built(tmp_path, slab, features={"finger_notches": 4})

    assert len(four.notches) == 4 and four.passed


def test_a_nest_that_does_not_fit_the_bed_is_refused(nest: Any) -> None:
    require_fits_bed(nest, PROFILE)

    with pytest.raises(ValueError, match="the printer's bed"):
        require_fits_bed(nest, {"build_volume_mm": {"x": 60, "y": 60, "z": 60}})


def test_it_prints_floor_down(nest: Any) -> None:
    printed = print_oriented(nest).val().BoundingBox()  # type: ignore[union-attr]

    assert printed.zmin == pytest.approx(0.0, abs=1e-6)


# --- the core -----------------------------------------------------------------------------------


def test_the_core_cuts_a_pocket_and_checks_a_part_against_it() -> None:
    outline = ((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0))
    body = pocketed(
        outline,
        clearance_mm=0.2,
        wall_mm=2.0,
        outer_z0=0.0,
        outer_z1=6.0,
        pocket_z0=2.0,
        pocket_z1=7.0,
    )
    part = block(10, 10, 4).translate((0, 0, 2)).val()
    solid = body.val()

    assert isinstance(part, cq.Shape) and isinstance(solid, cq.Shape)
    assert clear(solid, part)
    assert lifts_out(part, solid, 4.0)
    low = block(10, 10, 4).translate((0, 0, 0.5)).val()

    assert isinstance(low, cq.Shape)
    assert not clear(solid, low)


# --- the commands -------------------------------------------------------------------------------


def test_the_commands_write_check_and_build_a_nest(slab: Path, tmp_path: Path) -> None:
    nest_file = tmp_path / "nest.json"
    code, _ = run("nest", "template", "--part", str(slab), "--output", str(nest_file))
    data = json.loads(nest_file.read_text())
    data["source"] = "a block for tests"
    nest_file.write_text(json.dumps(data))

    assert code == 0
    code, report = run("nest", "check", str(nest_file))

    assert code == 0 and report["valid"] is True
    assert report["part"]["pocket_depth_mm"] == 8.0
    code, built_ = run(
        "nest",
        "build",
        "--nest-file",
        str(nest_file),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0
    assert built_["validation_status"] == "PASS"
    assert all(built_["checks"].values()) and len(built_["notches"]) == 2
    assert built_["verified"] is False
    record = json.loads((tmp_path / "out" / "nest.json").read_text())
    assert record["record_kind"] == "nest-build" and record["verified"] is False
    assert record["part"]["sha256"] == data["part"]["sha256"]
    assert len(record["parts"]["nest"]["stl_sha256"]) == 64
    assert "how well the nest holds" in record["not_claimed"]
    assert record["settings"]["finger_notches"] == 2
    assert load_nest(nest_file).finger_notches == 2


def test_the_check_command_exits_1_for_a_nest_it_cannot_use(
    slab: Path, tmp_path: Path
) -> None:
    path = write_nest(tmp_path, slab, depth_mm=30.0)
    code, report = run("nest", "check", str(path))

    assert code == 1 and report["valid"] is False


# --- phase 2: strap slots, a label and a lip -----------------------------------------------------

STRAP = {
    "width_mm": 20.0,
    "thickness_mm": 1.5,
    "source": "a hook-and-loop strap, measured",
}


def test_strap_slots_go_through_the_flange_at_each_end(
    slab: Path, tmp_path: Path
) -> None:
    nest = built(
        tmp_path, slab, features={"finger_notches": 0, "strap": STRAP}, flange_mm=10.0
    )

    assert len(nest.slots) == 2 and nest.checks["strap_slots_in_flange"]
    assert nest.passed

    for slot in nest.slots:
        # the slot is open through the floor and the flange round it is solid
        assert not inside(nest.body, slot.centre[0], slot.centre[1], -17.0)
        assert inside(nest.body, slot.centre[0], slot.centre[1] + 12.0, -17.0)


def test_a_flange_too_narrow_for_the_strap_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    path = write_nest(
        tmp_path, slab, features={"finger_notches": 0, "strap": STRAP}, flange_mm=3.0
    )
    report, _, _ = inspect_nest_file(path, PROFILE)

    assert not report.valid
    assert any("nest.flange_mm must be at least" in e for e in report.errors)


def test_a_label_stands_on_the_flange(slab: Path, tmp_path: Path) -> None:
    nest = built(tmp_path, slab, features={"finger_notches": 0, "label": "PLATE 3"})

    assert nest.label is not None and nest.label.text == "PLATE 3"
    assert nest.passed
    (tmp_path / "plain").mkdir()
    plain = built(tmp_path / "plain", slab, features={"finger_notches": 0})

    assert nest.body.val().Volume() > plain.body.val().Volume() + 1.0


def test_a_label_too_long_for_the_side_is_refused(slab: Path, tmp_path: Path) -> None:
    path = write_nest(tmp_path, slab, features={"finger_notches": 0, "label": "A" * 24})
    report, _, _ = inspect_nest_file(path, PROFILE)

    assert not report.valid and any("use shorter text" in e for e in report.errors)


def test_a_lip_takes_the_whole_height_and_hooks_over_the_part(
    slab: Path, tmp_path: Path
) -> None:
    data = nest_template(slab)
    data["features"] = {"finger_notches": 2, "lip": {"tabs": 2}}
    data["source"] = "a block for tests"
    path = tmp_path / "lip.json"
    path.write_text(json.dumps(data))
    report, spec, loaded = inspect_nest_file(path, PROFILE)

    assert report.valid, report.errors
    assert spec is not None and loaded is not None
    lipped = build_nest(spec, loaded, PROFILE)

    assert lipped.depth_mm == pytest.approx(16.0)
    assert len(lipped.tabs) == 2
    assert lipped.checks["lip_over_part"] and lipped.checks["part_lifts_out"]
    assert lipped.passed

    for tab in lipped.tabs:
        assert tab.strain <= 0.015
        # the hook is above the part's top face, overhanging the part
        x = tab.centre[0] + tab.outward[0] * (0.2 - 0.3)
        y = tab.centre[1] + tab.outward[1] * (0.2 - 0.3)

        assert inside(lipped.body, x, y, 0.3 + 0.5)


def test_a_lip_that_would_strain_too_far_is_refused(slab: Path, tmp_path: Path) -> None:
    data = nest_template(slab)
    data["features"] = {"finger_notches": 0, "lip": {"tabs": 2, "overhang_mm": 2.0}}
    data["nest"]["wall_mm"] = 4.0
    data["source"] = "a block for tests"
    path = tmp_path / "lip.json"
    path.write_text(json.dumps(data))
    report, _, _ = inspect_nest_file(path, PROFILE)

    assert not report.valid and any("would strain" in e for e in report.errors)


def test_the_build_command_reports_the_new_features(slab: Path, tmp_path: Path) -> None:
    path = write_nest(
        tmp_path,
        slab,
        features={"finger_notches": 1, "strap": STRAP, "label": "BASE"},
        flange_mm=10.0,
    )
    code, out = run(
        "nest",
        "build",
        "--nest-file",
        str(path),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0, out
    assert len(out["strap_slots"]) == 2 and out["label"]["text"] == "BASE"
    record = json.loads(Path(out["build_record"]).read_text())

    assert record["strap_slots"] and record["label"]["text"] == "BASE"
