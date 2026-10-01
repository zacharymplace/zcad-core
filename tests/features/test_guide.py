"""A drill guide's file, the part it names, and the nest and plate built for it."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.features.guide import (
    build_guide,
    guide_record,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.guide_file import (
    GuideSpec,
    check_guide_data,
    guide_template,
    inspect_guide_file,
    load_guide,
    load_part,
)
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def block(
    width: float,
    depth: float,
    height: float,
    at: tuple[float, float, float] = (0, 0, 0),
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(width, depth, height, centered=(True, True, False))
        .translate(at)
    )


def step_of(directory: Path, name: str, model: cq.Workplane) -> Path:
    path = directory / name
    cq.exporters.export(model, str(path))

    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_guide(directory: Path, part: Path, **changes: Any) -> Path:
    data = guide_template(part)
    data.update(changes)
    path = directory / "guide.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    return path


@pytest.fixture(scope="module")
def bracket(tmp_path_factory: pytest.TempPathFactory) -> Path:
    plate = block(60, 40, 12).edges("|Z").fillet(5)
    plate = plate.faces(">Z").workplane().pushPoints([(-18, 0), (18, 0)]).hole(6)

    return step_of(
        tmp_path_factory.mktemp("part"),
        "bracket.step",
        plate.union(block(16, 10, 12, at=(0, 25, 0))),
    )


def inside(shape: cq.Shape, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, shape).isInside(cq.Vector(x, y, z)))


def template() -> dict[str, Any]:
    return copy.deepcopy(guide_template())


# --- the file ---------------------------------------------------------------


def test_the_template_is_valid() -> None:
    report = check_guide_data(template())

    assert report.valid
    assert report.warnings == ()


def test_the_template_names_a_part_by_its_real_hash(bracket: Path) -> None:
    data = guide_template(bracket)

    assert data["part"]["sha256"] == sha(bracket)
    assert data["part"]["step"] == str(bracket)


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.update(schema_version="9.0.0"), "schema_version"),
        (lambda d: d.update(units="inch"), "units must be 'mm'"),
        (lambda d: d.update(identifier="has space"), "identifier"),
        (lambda d: d.update(needs_review=["part"]), "not reviewed"),
        (lambda d: d.update(bogus=1), "Unknown field"),
        (lambda d: d.pop("part"), "part is missing"),
        (lambda d: d.pop("nest"), "nest is missing"),
        (lambda d: d["part"].update(sha256="abc"), "part.sha256"),
        (lambda d: d["part"].update(step=""), "part.step"),
        (lambda d: d["part"].update(solid_index=0), "solid_index"),
        (lambda d: d["nest"].update(depth_mm=0.1), "nest.depth_mm"),
        (lambda d: d["nest"].update(depth_mm="deep"), "must be a number"),
        (lambda d: d["nest"].update(wall_mm=0.1), "nest.wall_mm"),
        (lambda d: d["nest"].update(bearing="ledge"), "later release"),
        (lambda d: d["plate"].update(thickness_mm=0.2), "plate.thickness_mm"),
        (lambda d: d.update(bores=[{"x_mm": 0}]), "bores[0].identifier"),
    ],
)
def test_what_cannot_be_right_is_refused(change: Any, expect: str) -> None:
    data = template()
    change(data)
    report = check_guide_data(data)

    assert not report.valid
    assert any(expect in error for error in report.errors)


def test_a_guide_with_no_source_is_warned_of() -> None:
    data = template()
    del data["source"]

    assert any("No source" in w for w in check_guide_data(data).warnings)


def test_a_non_object_is_refused() -> None:
    assert not check_guide_data([1]).valid


# --- the part -------------------------------------------------------------------


def test_the_part_comes_in_the_guides_frame(bracket: Path, tmp_path: Path) -> None:
    path = write_guide(tmp_path, bracket)
    spec = load_guide(path)
    part = load_part(spec)
    box = part.shape.BoundingBox()

    assert box.zmax == pytest.approx(0, abs=0.05)
    assert box.zmin == pytest.approx(-12, abs=0.05)
    assert (box.xmin + box.xmax, box.ymin + box.ymax) == pytest.approx((0, 0), abs=0.05)
    assert part.height_mm == pytest.approx(12)
    assert part.silhouette.top_share > 0.9


def test_a_part_that_has_changed_is_refused(bracket: Path, tmp_path: Path) -> None:
    other = step_of(tmp_path, "bracket.step", block(10, 10, 10))
    data = guide_template(bracket)
    data["part"]["step"] = other.name
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="has changed since the guide file"):
        load_part(load_guide(path))


def test_a_missing_part_is_refused(tmp_path: Path) -> None:
    data = guide_template()
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="STEP file is missing"):
        load_part(load_guide(path))


def test_a_solid_that_is_not_there_is_refused(bracket: Path, tmp_path: Path) -> None:
    data = guide_template(bracket)
    data["part"].update(step=str(bracket), solid_index=5)
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="the model has 1 solids"):
        load_part(load_guide(path))


def inspect(tmp_path: Path, part: Path, **nest: Any) -> Any:
    data = guide_template(part)
    data["nest"].update(nest)
    path = tmp_path / "guide.json"
    path.write_text(json.dumps(data))

    return inspect_guide_file(path, PROFILE)


def test_a_good_part_is_summarised(bracket: Path, tmp_path: Path) -> None:
    report, spec, part = inspect(tmp_path, bracket)

    assert report.valid, report.errors
    assert isinstance(spec, GuideSpec) and part is not None
    assert report.part is not None
    assert report.part["height_mm"] == pytest.approx(12)
    assert report.part["solids"] == 1


def test_a_nest_deeper_than_the_part_is_refused(bracket: Path, tmp_path: Path) -> None:
    report, _, _ = inspect(tmp_path, bracket, depth_mm=20.0)

    assert any("deeper than the part" in e for e in report.errors)


def test_a_shallow_nest_is_warned_of(bracket: Path, tmp_path: Path) -> None:
    report, _, _ = inspect(tmp_path, bracket, depth_mm=1.0)

    assert report.valid
    assert any("barely locates" in w for w in report.warnings)


def test_a_part_with_no_flat_top_is_refused(tmp_path: Path) -> None:
    ball = step_of(tmp_path, "ball.step", cq.Workplane("XY").sphere(15))
    report, _, _ = inspect(tmp_path, ball, depth_mm=10.0)

    assert any("no flat top" in e for e in report.errors)


def test_a_model_of_several_solids_is_warned_of(tmp_path: Path) -> None:
    both = block(40, 40, 6).union(block(10, 10, 6, at=(0, 0, 6)), clean=False)
    pair = cq.Workplane("XY").add(
        [
            cq.Solid.makeBox(40, 40, 6, pnt=cq.Vector(-20, -20, 0)),
            cq.Solid.makeBox(30, 30, 4, pnt=cq.Vector(-15, -15, 6)),
        ]
    )
    step = step_of(tmp_path, "pair.step", pair)
    report, _, _ = inspect(tmp_path, step, depth_mm=5.0)

    assert both is not None
    assert report.valid, report.errors
    assert any("solids" in w and "solid_index" in w for w in report.warnings)


def test_a_part_that_falls_in_pieces_is_refused(tmp_path: Path) -> None:
    pair = cq.Workplane("XY").add(
        [
            cq.Solid.makeBox(10, 10, 6, pnt=cq.Vector(0, 0, 0)),
            cq.Solid.makeBox(10, 10, 6, pnt=cq.Vector(40, 0, 0)),
        ]
    )
    step = step_of(tmp_path, "apart.step", pair)
    report, _, _ = inspect(tmp_path, step, depth_mm=5.0)

    assert any("separate pieces" in e for e in report.errors)


# --- the nest and plate ------------------------------------------------------------


@pytest.fixture(scope="module")
def built(bracket: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("guide")
    report, spec, part = inspect(directory, bracket)
    assert spec is not None and part is not None

    return build_guide(spec, part, PROFILE), report


def test_the_guide_passes_its_checks(built: Any) -> None:
    guide, _ = built

    assert guide.passed
    assert guide.checks == {
        "one_solid": True,
        "part_fits_pocket": True,
        "part_lifts_out": True,
        "bores_open": True,
        "bit_reaches_depth": True,
    }


def test_the_guide_is_the_shadow_widened_by_the_clearance_and_the_wall(
    built: Any,
) -> None:
    guide, _ = built
    width, depth, height = guide.size_mm

    # The part is 60 x 50 mm: a side clearance of 0.2 and a wall of 2.0 each way.
    assert width == pytest.approx(60 + 2 * 2.2, abs=0.4)
    assert depth == pytest.approx(50 + 2 * 2.2, abs=0.4)
    assert height == pytest.approx(8 + 6)
    assert guide.clearance_mm == 0.2


def test_the_plate_bears_on_the_part_and_the_nest_surrounds_it(built: Any) -> None:
    guide, _ = built
    solid = guide.body.val()
    assert isinstance(solid, cq.Shape)

    # Plate material just above the part's top; a nest wall beside the part;
    # and nothing inside the pocket where the part goes.
    assert inside(solid, 10, 5, 3.0)
    # The template's bore leaves a hole where the drill goes.
    assert not inside(solid, 0, 0, 3.0)
    assert inside(solid, -31.2, 0, -4.0)
    assert not inside(solid, 0, 0, -4.0)


def test_an_undercut_part_still_lifts_out() -> None:
    mushroom = block(10, 10, 20).union(block(40, 30, 5, at=(0, 0, 20)))
    directory = Path(__import__("tempfile").mkdtemp())
    step = step_of(directory, "mushroom.step", mushroom)
    _, spec, part = inspect(directory, step, depth_mm=10.0)
    assert spec is not None and part is not None
    guide = build_guide(spec, part, PROFILE)

    assert guide.checks["part_lifts_out"]
    assert guide.passed


def test_the_guide_prints_plate_down(built: Any) -> None:
    guide, _ = built
    turned = print_oriented(guide).val()

    assert isinstance(turned, cq.Shape)
    box = turned.BoundingBox()
    # The plate is now at the bottom: solid right across the nest's footprint.
    assert inside(turned, 10, 5, box.zmin + 0.5)
    assert not inside(turned, 0, 0, box.zmax - 0.5)


def test_a_thin_wall_or_plate_is_refused(bracket: Path, tmp_path: Path) -> None:
    _, spec, part = inspect(tmp_path, bracket)
    assert spec is not None and part is not None

    with pytest.raises(ValueError, match="minimum wall"):
        build_guide(GuideSpec(**{**spec.__dict__, "nest_wall_mm": 1.0}), part, PROFILE)

    with pytest.raises(ValueError, match="plate.thickness_mm"):
        build_guide(
            GuideSpec(**{**spec.__dict__, "plate_thickness_mm": 1.2 - 0.01}),
            part,
            PROFILE,
        )


def test_a_profile_without_a_clearance_is_refused(
    bracket: Path, tmp_path: Path
) -> None:
    _, spec, part = inspect(tmp_path, bracket)
    assert spec is not None and part is not None

    with pytest.raises(ValueError, match="sliding_clearance_per_side"):
        build_guide(spec, part, {"tolerances_mm": {}})


def test_a_guide_too_big_for_the_bed_is_refused(tmp_path: Path) -> None:
    big = step_of(tmp_path, "big.step", block(200, 100, 10))
    _, spec, part = inspect(tmp_path, big, depth_mm=5.0)
    assert spec is not None and part is not None
    guide = build_guide(spec, part, PROFILE)

    with pytest.raises(ValueError, match="printer's bed"):
        require_fits_bed(guide, PROFILE)


def test_the_record_names_the_part_by_hash_and_claims_nothing(
    built: Any, bracket: Path
) -> None:
    guide, _ = built
    record = guide_record(guide, {})

    assert record["verified"] is False
    assert [b["identifier"] for b in record["bores"]] == ["B1"]
    assert record["bushing"] is None
    assert record["part"]["sha256"] == sha(bracket)
    assert record["nest"]["clearance_per_side_mm"] == 0.2
    assert record["tolerance_status"] == "provisional"
    # Play is a bound from the profile, and the record says it is no accuracy.
    assert "not a measured positional accuracy" in record["play_note"]
    assert "accuracy_mm" not in json.dumps(record)
