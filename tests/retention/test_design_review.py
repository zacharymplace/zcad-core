from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    EdgeCapturePolicy,
    ProductionCornerExecutionRequest,
    ProductionEdgeExecutionRequest,
    ValidationFixturePolicy,
    execute_production_corner_capture,
    execute_production_edge_capture,
    export_design_review_package,
)


def export_clear_board(
    path: Path,
) -> None:
    pcb = (
        cq.Workplane("XY")
        .box(
            40.0,
            30.0,
            1.6,
        )
        .translate(
            (
                0.0,
                0.0,
                0.8,
            )
        )
    )

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )
    assembly.export(
        str(path),
        exportType="STEP",
    )


def production_execution(
    tmp_path: Path,
):
    source_step = tmp_path / "board.step"

    export_clear_board(source_step)

    return execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=(tmp_path / "retention.step"),
            policy=CornerCapturePolicy(),
        )
    )


def test_exports_design_review_package(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_directory = tmp_path / "review"

    artifact = export_design_review_package(
        execution,
        output_directory=output_directory,
        fixture_policy=ValidationFixturePolicy(),
    )

    assert artifact.passed is True
    assert artifact.glb_path.is_file()
    assert artifact.step_path.is_file()
    assert artifact.three_mf_path.is_file()
    assert len(artifact.view_paths) == 4
    assert all(path.is_file() for path in artifact.view_paths)

    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))

    assert report["decision"] == ("visual_review_ready")
    assert report["passed"] is True
    assert report["geometry"]["component_count"] == 0
    assert report["review_status"] == {
        "automated_geometry_complete": True,
        "human_visual_review_complete": False,
        "physical_validation_complete": False,
    }


def test_refuses_existing_review_outputs(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_directory = tmp_path / "review"
    existing = output_directory / "design-review.json"

    output_directory.mkdir()
    existing.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        export_design_review_package(
            execution,
            output_directory=output_directory,
            fixture_policy=ValidationFixturePolicy(),
        )

    assert existing.read_text(encoding="utf-8") == "{}\n"
    assert not (output_directory / "design-review.glb").exists()


def test_rejects_negative_tolerance(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)

    with pytest.raises(
        ValueError,
        match="tolerance_mm3",
    ):
        export_design_review_package(
            execution,
            output_directory=(tmp_path / "review"),
            fixture_policy=ValidationFixturePolicy(),
            tolerance_mm3=-1.0,
        )


def test_exports_edge_clip_design_review_package(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    export_clear_board(source_step)
    execution = execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=EdgeCapturePolicy(),
        )
    )

    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=ValidationFixturePolicy(),
    )

    assert artifact.passed is True
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["geometry"]["selected_corners"] == [
        execution.derivation.selected_edge.value
    ]


def board_with_underside_part(
    path: Path, *, depth_mm: float, z_offset: float = 0.0
) -> None:
    """A board with one bottom-side part proud of its underside by depth_mm."""

    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8 + z_offset))
    pad = (
        cq.Workplane("XY")
        .box(2.0, 2.0, depth_mm + 0.5)
        .translate((0.0, 0.0, z_offset - depth_mm + (depth_mm + 0.5) / 2))
    )
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.add(pad, name="pad")
    assembly.export(str(path), exportType="STEP")


def review_board(
    tmp_path: Path,
    fixture_policy: ValidationFixturePolicy | None = None,
    **board: float,
) -> dict[str, object]:
    source_step = tmp_path / "board.step"
    board_with_underside_part(source_step, **board)
    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=CornerCapturePolicy(),
        )
    )
    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=fixture_policy or ValidationFixturePolicy(),
    )
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["passed"] is artifact.passed

    return report


def test_shallow_underside_pads_are_seating_contact(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.04)

    interference = report["interference"]
    assert report["passed"] is True
    assert interference["component_fixture_intersections"] == []
    assert len(interference["underside_seating_contacts"]) == 1
    assert interference["underside_seating_contacts"][0]["depth_mm"] == pytest.approx(
        0.04, abs=1e-6
    )


def test_deep_underside_parts_get_clearance_holes(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.3)

    assert report["passed"] is True
    assert report["interference"]["component_fixture_intersections"] == []
    assert report["interference"]["underside_seating_contacts"] == []


def test_deep_underside_parts_block_review_without_holes(tmp_path: Path) -> None:
    report = review_board(
        tmp_path,
        fixture_policy=ValidationFixturePolicy(underside_seating_mm=10.0),
        depth_mm=0.3,
    )

    assert report["passed"] is False
    assert len(report["interference"]["component_fixture_intersections"]) == 1
    assert report["interference"]["underside_seating_contacts"] == []


def test_board_modelled_below_origin_seats_on_base(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.04, z_offset=-1.6)

    assert report["passed"] is True
    assert report["interference"]["pcb_fixture_intersection_mm3"] == 0.0


def review_board_with_top_part(
    tmp_path: Path, *, minimum_component_gap_mm: float
) -> dict[str, object]:
    """A board with one top-side part 1.6 mm (the board) above the base."""

    source_step = tmp_path / "board.step"
    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    part = cq.Workplane("XY").box(4.0, 4.0, 2.0).translate((0.0, 0.0, 2.6))
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.add(part, name="part")
    assembly.export(str(source_step), exportType="STEP")

    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=CornerCapturePolicy(),
        )
    )
    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=ValidationFixturePolicy(),
        minimum_component_gap_mm=minimum_component_gap_mm,
    )
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["passed"] is artifact.passed

    return report


def test_component_inside_minimum_gap_blocks_review(tmp_path: Path) -> None:
    """Zero overlap volume is not enough: a part closer to the fixture than
    the minimum gap blocks the review (UNO R4 r004's clip touched a header)."""

    report = review_board_with_top_part(tmp_path, minimum_component_gap_mm=2.0)
    interference = report["interference"]

    assert report["passed"] is False
    assert report["decision"] == "geometry_review_blocked"
    assert interference["component_fixture_intersections"] == []
    assert interference["component_clearance_violations"] == [
        {"component_index": 1, "gap_mm": pytest.approx(1.6, abs=1e-3)}
    ]


def test_component_beyond_minimum_gap_passes(tmp_path: Path) -> None:
    report = review_board_with_top_part(tmp_path, minimum_component_gap_mm=0.1)

    assert report["passed"] is True
    assert report["schema_version"] == "1.2.0"
    assert report["interference"]["minimum_component_gap_mm"] == 0.1
    assert report["interference"]["component_clearance_violations"] == []


def test_flush_underside_pad_is_seating_not_a_clearance_violation(
    tmp_path: Path,
) -> None:
    report = review_board(tmp_path, depth_mm=0.0)
    interference = report["interference"]

    assert report["passed"] is True
    assert interference["component_clearance_violations"] == []
    assert interference["underside_seating_contacts"] == [
        {"component_index": 1, "intersection_mm3": 0.0, "depth_mm": 0.0}
    ]


def test_rejects_negative_minimum_component_gap(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="minimum_component_gap_mm"):
        export_design_review_package(
            production_execution(tmp_path),
            output_directory=tmp_path / "review",
            fixture_policy=ValidationFixturePolicy(),
            minimum_component_gap_mm=-0.1,
        )


def review_clearance(
    tmp_path: Path,
    parts: tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...],
) -> dict[str, Any]:
    """Review a 40 x 30 mm board carrying boxes given as (size, center)."""

    source_step = tmp_path / "board.step"
    assembly = cq.Assembly()
    assembly.add(
        cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8)),
        name="pcb",
    )

    for index, (size, center) in enumerate(parts):
        assembly.add(
            cq.Workplane("XY").box(*size).translate(center), name=f"part-{index}"
        )

    assembly.export(str(source_step), exportType="STEP")
    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=CornerCapturePolicy(),
        )
    )
    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=ValidationFixturePolicy(),
    )
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["geometry"]["selected_corners"] == [
        "negative_x_negative_y",
        "positive_x_positive_y",
    ]

    return dict(report["clearance"])


CENTER_PART = ((4.0, 4.0, 2.0), (0.0, 0.0, 2.6))
EDGE_PART = ((3.0, 4.0, 2.0), (-20.0, 5.0, 2.6))
CORNER_PART = ((1.0, 1.0, 2.0), (-15.0, -13.5, 2.6))


def test_clearance_lists_closest_parts_and_capture_gaps(tmp_path: Path) -> None:
    clearance = review_clearance(tmp_path, (CENTER_PART, EDGE_PART, CORNER_PART))

    closest = [
        (entry["component_index"], entry["gap_mm"])
        for entry in clearance["closest_components"]
    ]
    assert closest == [(3, 1.25), (1, 1.6), (2, 1.6)]

    # Only the part beside a capture is measured against the captures.
    assert [
        (entry["component_index"], entry["gap_mm"])
        for entry in clearance["closest_to_captures"]
    ] == [(3, 1.25)]
    assert clearance["closest_to_captures"][0]["center_mm"] == [-15.0, -13.5]
    assert clearance["pcb_to_capture_gap_mm"] == pytest.approx(0.25)
    assert clearance["capture_volume_mm3"] > 0


def test_clearance_measures_base_lip_under_an_overhanging_part(tmp_path: Path) -> None:
    """The fixture's 2 mm margin runs 0.5 mm past a part overhanging by 1.5 mm."""

    clearance = review_clearance(tmp_path, (EDGE_PART,))

    assert clearance["edge_overhangs"] == [
        {
            "component_index": 1,
            "edge": "negative_x",
            "overhang_mm": 1.5,
            "base_lip_mm": 0.5,
            "height_above_base_mm": 1.6,
            "gap_mm": 1.6,
            "size_mm": [3.0, 4.0, 2.0],
        }
    ]


def test_clearance_reports_parts_through_base_holes(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.3)
    passthroughs = report["clearance"]["underside_passthroughs"]

    assert len(passthroughs) == 1
    assert passthroughs[0]["depth_below_pcb_mm"] == pytest.approx(0.3)
    assert passthroughs[0]["hole_clearance_mm"] == pytest.approx(0.5, abs=1e-3)
    # Shallow seating pads rest on the base; they are not pass-throughs.
    (tmp_path / "shallow").mkdir()
    assert (
        review_board(tmp_path / "shallow", depth_mm=0.04)["clearance"][
            "underside_passthroughs"
        ]
        == []
    )
