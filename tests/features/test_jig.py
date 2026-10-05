"""An insert jig: a nest round a part with a plate and a bore over each insert."""

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
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_file import load_part_file
from zcad_core.features.jig import (
    bore_diameter_mm,
    build_jig,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.jig_file import (
    check_jig_data,
    check_jig_file,
    inspect_jig_file,
    jig_template,
)
from zcad_core.features.jig_holes import part_holes
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PRINTER_PATH)
IRON = {
    "tip_diameter_mm": 4.0,
    "shoulder_diameter_mm": 9.0,
    "tip_length_mm": 6.0,
    "source": "measured with calipers on the bench iron",
}


def block(width: float, depth: float, height: float) -> cq.Workplane:
    return cq.Workplane("XY").box(width, depth, height, centered=(True, True, False))


@pytest.fixture(scope="module")
def slab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 50 x 30 x 16 block."""

    path = tmp_path_factory.mktemp("slab") / "slab.step"
    cq.exporters.export(block(50, 30, 16), str(path))

    return path


def write_jig(directory: Path, part: Path, **changes: Any) -> Path:
    data = copy.deepcopy(jig_template(part))
    data["source"] = "a block for tests"
    data["iron"] = dict(IRON)
    data["inserts"] = [
        {"id": "I1", "x_mm": -10.0, "y_mm": 0.0},
        {"id": "I2", "x_mm": 10.0, "y_mm": 0.0},
    ]

    for key, value in changes.items():
        if key in ("depth_mm", "wall_mm", "depth_below_face_mm"):
            data["jig"][key] = value
        else:
            data[key] = value

    path = directory / "jig.json"
    path.write_text(json.dumps(data))

    return path


def built(directory: Path, part: Path, **changes: Any) -> Any:
    report, spec, loaded = inspect_jig_file(
        write_jig(directory, part, **changes), PROFILE
    )

    assert report.valid, report.errors
    assert spec is not None and loaded is not None

    return build_jig(spec, loaded, PROFILE)


def inside(shape: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, shape.val()).Solids()
    )


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


# --- the file -----------------------------------------------------------------------------------


def test_the_template_is_refused_until_the_irons_source_is_replaced(slab: Path) -> None:
    report = check_jig_data(jig_template(slab))

    assert not report.valid
    assert any("iron.source is still the example's" in e for e in report.errors)
    assert len(report.errors) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(file_kind="nest"), "file_kind must be"),
        (lambda d: d.update(colour="red"), "Unknown field"),
        (lambda d: d["jig"].update(depth_mm=0.1), "jig.depth_mm"),
        (lambda d: d["jig"].update(wall_mm=0.2), "jig.wall_mm"),
        (lambda d: d["jig"].update(bearing="top"), "unknown fields: bearing"),
        (lambda d: d["insert"].update(size="M9"), "not a catalogued fastener"),
        (lambda d: d["iron"].pop("source"), "iron.source is needed"),
        (lambda d: d["iron"].update(source="  "), "iron.source is needed"),
        (lambda d: d["iron"].update(tip_diameter_mm=20), "iron.tip_diameter_mm"),
        (
            lambda d: d["iron"].update(shoulder_diameter_mm=3.0),
            "must be wider than the tip",
        ),
        (lambda d: d.update(inserts=[]), "at least one insert"),
        (
            lambda d: d["inserts"].append({"id": "I1", "x_mm": 1, "y_mm": 1}),
            "used twice",
        ),
        (lambda d: d["inserts"][0].update(x_mm="left"), "x_mm must be a number"),
        (lambda d: d["inserts"][0].update(colour=1), "unknown fields: colour"),
        (lambda d: d.update(needs_review="unchecked"), "not reviewed"),
    ],
)
def test_a_jig_file_that_cannot_be_right_is_refused(change: Any, message: str) -> None:
    data = copy.deepcopy(jig_template())
    data["iron"]["source"] = "measured"
    change(data)
    report = check_jig_data(data)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_changed_part_is_refused(slab: Path, tmp_path: Path) -> None:
    path = write_jig(tmp_path, slab)
    data = json.loads(path.read_text())
    data["part"]["sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    report = check_jig_file(path, PROFILE)

    assert not report.valid and any("has changed" in e for e in report.errors)


def test_a_valid_file_reads_the_part_and_the_insert(slab: Path, tmp_path: Path) -> None:
    report = check_jig_file(write_jig(tmp_path, slab), PROFILE)

    assert report.valid, report.errors
    assert report.part is not None
    assert report.part["height_mm"] == pytest.approx(16.0, abs=0.01)
    assert report.part["insert"] == {"size": "M3", "diameter_mm": 4.6, "length_mm": 5.0}


# --- the insert and its pocket ------------------------------------------------------------------


def test_a_pocket_too_small_or_too_shallow_for_the_insert_is_refused(
    slab: Path, tmp_path: Path
) -> None:
    small = write_jig(
        tmp_path,
        slab,
        inserts=[{"id": "I1", "x_mm": 0, "y_mm": 0, "pocket_diameter_mm": 3.5}],
    )
    report = check_jig_file(small, PROFILE)

    assert any("too small for a M3 insert" in e for e in report.errors)

    shallow = write_jig(
        tmp_path,
        slab,
        inserts=[{"id": "I1", "x_mm": 0, "y_mm": 0, "pocket_depth_mm": 4.0}],
    )
    report = check_jig_file(shallow, PROFILE)

    assert any("too shallow" in e for e in report.errors)


def test_a_pocket_off_the_catalogued_size_warns(slab: Path, tmp_path: Path) -> None:
    path = write_jig(
        tmp_path,
        slab,
        inserts=[
            {
                "id": "I1",
                "x_mm": 0,
                "y_mm": 0,
                "pocket_diameter_mm": 5.4,
                "pocket_depth_mm": 6.0,
            }
        ],
    )
    report = check_jig_file(path, PROFILE)

    assert report.valid, report.errors
    assert any("catalogued size" in w for w in report.warnings)


def test_an_insert_too_long_for_the_part_is_refused(tmp_path: Path, slab: Path) -> None:
    short = tmp_path / "short.step"
    cq.exporters.export(block(50, 30, 4), str(short))
    report = check_jig_file(write_jig(tmp_path, short), PROFILE)

    assert any("needs 5 mm of part" in e for e in report.errors)


# --- the build ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jig(slab: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    return built(tmp_path_factory.mktemp("jig"), slab)


def test_the_bore_is_the_inserts_size_plus_the_printers_allowances() -> None:
    fits, _, _ = printer_numbers(PROFILE)

    assert bore_diameter_mm(4.6, fits) == pytest.approx(
        4.6 + 2 * fits["sliding_clearance_per_side"] + fits["hole_oversize"]
    )


def test_the_plate_is_the_irons_tip_length_and_the_iron_stops_on_it(jig: Any) -> None:
    # Flush: the tip's end reaches the insert's top when the shoulder rests on the plate.
    assert jig.plate_thickness_mm == pytest.approx(6.0)
    assert jig.checks["iron_reaches_insert"]
    assert jig.body.val().BoundingBox().zmax == pytest.approx(6.0, abs=1e-3)


def test_an_insert_below_the_face_makes_a_thinner_plate(
    slab: Path, tmp_path: Path
) -> None:
    sunk = built(tmp_path, slab, depth_below_face_mm=2.0)

    assert sunk.plate_thickness_mm == pytest.approx(4.0)
    assert sunk.passed


def test_each_bore_is_open_through_the_plate_and_the_plate_is_solid_between(
    jig: Any,
) -> None:
    assert jig.passed
    assert len(jig.bores) == 2

    for bore in jig.bores:
        assert not inside(jig.body, bore.centre[0], bore.centre[1], 3.0)

    # the plate between the bores, and over the rest of the part, is solid
    assert inside(jig.body, 0.0, 0.0, 3.0)
    assert inside(jig.body, 20.0, 5.0, 3.0)


def test_the_part_fits_and_lifts_straight_out(jig: Any) -> None:
    assert jig.checks["part_fits_pocket"] and jig.checks["part_lifts_out"]
    assert jig.checks["one_solid"] and jig.checks["bores_open"]


def test_it_prints_plate_down(jig: Any) -> None:
    box = cast(cq.Shape, print_oriented(jig).val()).BoundingBox()

    # The plate's top (z = 6) is turned to the bed, the nest's open end up.
    assert box.zmin == pytest.approx(-6.0, abs=1e-3)
    assert box.zmax == pytest.approx(jig.depth_mm, abs=1e-3)
    assert box.zlen == pytest.approx(jig.size_mm[2])


def test_a_jig_that_does_not_fit_the_bed_is_refused(jig: Any) -> None:
    require_fits_bed(jig, PROFILE)

    with pytest.raises(ValueError, match="printer's bed"):
        require_fits_bed(jig, {"build_volume_mm": {"x": 20, "y": 20, "z": 20}})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"iron": {**IRON, "tip_diameter_mm": 5.4}},
            "will not go down",
        ),
        (
            {"iron": {**IRON, "shoulder_diameter_mm": 6.0}},
            "would not stand on the plate",
        ),
        (
            {"iron": {**IRON, "tip_length_mm": 1.0}},
            "under the printer's",
        ),
        (
            {"inserts": [{"id": "I1", "x_mm": 40.0, "y_mm": 0.0}]},
            "outside the part's shadow",
        ),
        (
            {"inserts": [{"id": "I1", "x_mm": 24.0, "y_mm": 0.0}]},
            "reach past the edge",
        ),
        (
            {
                "inserts": [
                    {"id": "I1", "x_mm": 0.0, "y_mm": 0.0},
                    {"id": "I2", "x_mm": 5.5, "y_mm": 0.0},
                ]
            },
            "of plate between their bores",
        ),
    ],
)
def test_a_jig_that_cannot_work_is_refused_with_the_reason(
    slab: Path, tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    _, spec, part = inspect_jig_file(write_jig(tmp_path, slab, **changes), PROFILE)

    assert spec is not None and part is not None

    with pytest.raises(ValueError, match=message):
        build_jig(spec, part, PROFILE)


# --- the commands -------------------------------------------------------------------------------


def test_the_commands_write_check_and_build_a_jig(slab: Path, tmp_path: Path) -> None:
    out = tmp_path / "template.json"
    code, _ = run("jig", "template", "--part", str(slab), "--output", str(out))

    assert code == 0 and out.exists()

    code, report = run("jig", "check", str(out))

    assert code == 1 and not report["valid"]

    path = write_jig(tmp_path, slab)
    code, report = run("jig", "check", str(path))

    assert code == 0 and report["valid"], report

    code, built_out = run(
        "jig",
        "build",
        "--jig-file",
        str(path),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0, built_out
    assert built_out["verified"] is False
    assert len(built_out["bores"]) == 2
    record = json.loads(Path(built_out["build_record"]).read_text())

    assert record["record_kind"] == "jig-build" and record["verified"] is False
    assert record["iron"]["source"] == IRON["source"]
    assert record["jig_file"]["sha256"] and record["part"]["sha256"]
    assert "no temperature, time or force" in record["not_claimed"]
    assert record["settings"]["plate_thickness_mm"] == pytest.approx(6.0)


# --- phase 4: insert positions from the part's own holes ---------------------------------------


@pytest.fixture(scope="module")
def drilled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 50 x 30 x 16 block with two blind 4.6 x 6 pockets, a 3.4 mm hole right through it,
    and a hole opening on its side face, which is no place for an insert."""

    def hole(x: float, y: float, diameter: float, depth: float) -> cq.Workplane:
        return (
            cq.Workplane("XY")
            .circle(diameter / 2)
            .extrude(depth)
            .translate((x, y, 16 - depth))
        )

    model = (
        block(50, 30, 16)
        .cut(hole(-10, -5, 4.6, 6))
        .cut(hole(10, -5, 4.6, 6))
        .cut(hole(0, 8, 3.4, 16))
        .cut(cq.Workplane("YZ").circle(2).extrude(10).translate((-25, 0, 6)))
    )
    path = tmp_path_factory.mktemp("drilled") / "drilled.step"
    cq.exporters.export(model, str(path))

    return path


def jig_from_holes(directory: Path, part: Path, holes: dict[str, Any]) -> Path:
    data = copy.deepcopy(jig_template(part))
    data["source"] = "a drilled block for tests"
    data["iron"] = dict(IRON)
    data.pop("inserts")
    data["insert_holes"] = holes
    path = directory / "jig.json"
    path.write_text(json.dumps(data))

    return path


def test_the_part_holes_open_at_the_top_face_are_found(drilled: Path) -> None:
    part = load_part_file(drilled, None, None)
    found = part_holes(part.shape, part.height_mm)

    assert [h.identifier for h in found] == ["H01", "H02", "H03"]
    first, second, through = found
    assert (first.x_mm, first.y_mm) == (pytest.approx(-10.0), pytest.approx(-5.0))
    assert (second.x_mm, second.y_mm) == (pytest.approx(10.0), pytest.approx(-5.0))
    assert first.diameter_mm == pytest.approx(4.6)
    assert first.depth_mm == pytest.approx(6.0)
    assert not first.through
    assert through.through and through.diameter_mm == pytest.approx(3.4)


def test_a_pockets_rounded_corners_and_a_slots_ends_are_not_holes() -> None:
    # A 40 x 30 x 10 block, top at z == 0, with a 20 x 10 pocket rounded 2 mm at its
    # corners, a 12 x 4 slot, and one 4 mm hole: each corner and slot end is an arc of a
    # cylinder about a point in the void, but only the hole goes all the way round.
    block = cq.Workplane("XY").box(40, 30, 10).translate((0, 0, -5))
    pocket = (
        cq.Workplane("XY")
        .rect(20, 10)
        .extrude(5)
        .edges("|Z")
        .fillet(2.0)
        .translate((0, 5, -5))
    )
    slot = cq.Workplane("XY").slot2D(12, 4).extrude(5).translate((0, -8, -5))
    hole = cq.Workplane("XY").circle(2.0).extrude(12).translate((-15, -10, -11))
    shape = cast(cq.Shape, block.cut(pocket).cut(slot).cut(hole).val())

    found = part_holes(shape, 10.0)

    assert [(h.x_mm, h.y_mm, h.diameter_mm) for h in found] == [
        (pytest.approx(-15.0), pytest.approx(-10.0), pytest.approx(4.0))
    ]


def test_the_picked_holes_become_bores_over_the_pockets(
    drilled: Path, tmp_path: Path
) -> None:
    path = jig_from_holes(
        tmp_path, drilled, {"from_part": True, "holes": ["H01", "H02"]}
    )
    report, spec, part = inspect_jig_file(path, PROFILE)

    assert report.valid, report.errors
    assert spec is not None and part is not None
    jig = build_jig(spec, part, PROFILE)

    assert jig.passed
    assert [(b.identifier, b.origin) for b in jig.bores] == [
        ("H01", "part"),
        ("H02", "part"),
    ]
    assert jig.bores[0].centre[0] == pytest.approx(-10.0)
    assert jig.bores[0].centre[1] == pytest.approx(-5.0)
    assert not inside(jig.body, -10.0, -5.0, 3.0)


def test_a_hole_too_small_for_the_insert_is_refused_when_it_is_taken(
    drilled: Path, tmp_path: Path
) -> None:
    # No pick: all three, and the 3.4 mm through hole cannot take an M3 insert.
    path = jig_from_holes(tmp_path, drilled, {"from_part": True})
    report = check_jig_file(path, PROFILE)

    assert not report.valid
    assert any("H03" in e and "too small for a M3 insert" in e for e in report.errors)


def test_a_pocket_found_too_shallow_is_refused(drilled: Path, tmp_path: Path) -> None:
    path = jig_from_holes(tmp_path, drilled, {"from_part": True, "holes": ["H01"]})
    data = json.loads(path.read_text())
    data["jig"]["depth_below_face_mm"] = 2.0
    path.write_text(json.dumps(data))
    report = check_jig_file(path, PROFILE)

    assert any("H01" in e and "too shallow" in e for e in report.errors)


def test_a_hole_the_part_does_not_have_is_named_with_the_ones_it_has(
    drilled: Path, tmp_path: Path
) -> None:
    path = jig_from_holes(tmp_path, drilled, {"from_part": True, "holes": ["H09"]})
    report = check_jig_file(path, PROFILE)

    assert any("names H09" in e and "H01, H02, H03" in e for e in report.errors)


def test_a_part_with_no_holes_to_read_is_refused(slab: Path, tmp_path: Path) -> None:
    path = jig_from_holes(tmp_path, slab, {"from_part": True})
    report = check_jig_file(path, PROFILE)

    assert any("no round hole open at its top face" in e for e in report.errors)


def test_typed_and_found_inserts_can_be_mixed(drilled: Path, tmp_path: Path) -> None:
    path = jig_from_holes(tmp_path, drilled, {"from_part": True, "holes": ["H01"]})
    data = json.loads(path.read_text())
    data["inserts"] = [{"id": "T1", "x_mm": 15.0, "y_mm": 8.0}]
    path.write_text(json.dumps(data))
    report, spec, part = inspect_jig_file(path, PROFILE)

    assert report.valid, report.errors
    assert spec is not None and part is not None
    jig = build_jig(spec, part, PROFILE)

    assert {b.identifier: b.origin for b in jig.bores} == {
        "T1": "typed",
        "H01": "part",
    }


@pytest.mark.parametrize(
    ("holes", "message"),
    [
        ({"from_part": "yes"}, "must be true or false"),
        ({"from_part": True, "holes": []}, "list of hole names"),
        ({"holes": ["H01"]}, "needs insert_holes.from_part"),
        ({"from_part": True, "colour": 1}, "unknown fields: colour"),
    ],
)
def test_a_badly_written_holes_section_is_refused(holes: Any, message: str) -> None:
    data = copy.deepcopy(jig_template())
    data["iron"]["source"] = "measured"
    data["insert_holes"] = holes
    report = check_jig_data(data)

    assert any(message in e for e in report.errors), report.errors


def test_a_file_with_neither_inserts_nor_holes_is_refused() -> None:
    data = copy.deepcopy(jig_template())
    data["iron"]["source"] = "measured"
    data.pop("inserts")
    report = check_jig_data(data)

    assert any("unless insert_holes.from_part" in e for e in report.errors)


def test_the_record_says_where_each_position_came_from(
    drilled: Path, tmp_path: Path
) -> None:
    path = jig_from_holes(tmp_path, drilled, {"from_part": True, "holes": ["H01"]})
    code, out = run(
        "jig",
        "build",
        "--jig-file",
        str(path),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0, out
    record = json.loads(Path(out["build_record"]).read_text())

    assert record["bores"][0]["origin"] == "part"
