from __future__ import annotations

from dataclasses import replace

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware.wearables import EdgeFeature
from zcad_core.retention import (
    SnapShellBackend,
    SnapShellFitCheck,
    SnapShellLocation,
    SnapShellParameters,
    SnapShellPolicy,
    SnapShellRequest,
    SyntheticSnapShellBackend,
)

# A G7-sized body, 27.4 x 24.1 x 4.7 mm, with a clip at the middle of three
# edges, each turned to reach into the device.
LENGTH, WIDTH, THICKNESS = 27.4, 24.1, 4.7


def spaced_locations() -> tuple[SnapShellLocation, ...]:
    return (
        SnapShellLocation(
            label="north", x_mm=0.0, y_mm=WIDTH / 2, rotation_degrees=270.0
        ),
        SnapShellLocation(
            label="south", x_mm=0.0, y_mm=-WIDTH / 2, rotation_degrees=90.0
        ),
        SnapShellLocation(
            label="east", x_mm=LENGTH / 2, y_mm=0.0, rotation_degrees=180.0
        ),
    )


def valid_request(
    policy: SnapShellPolicy | None = None,
    locations: tuple[SnapShellLocation, ...] | None = None,
) -> SnapShellRequest:
    return SnapShellRequest(
        device_thickness_mm=THICKNESS,
        device_length_mm=LENGTH,
        device_width_mm=WIDTH,
        locations=locations or spaced_locations(),
        policy=policy or SnapShellPolicy(),
    )


def device() -> cq.Shape:
    return workplane_shape(
        cq.Workplane("XY").box(LENGTH, WIDTH, THICKNESS, centered=(True, True, False))
    )


# A vertical clip on a body this thin bends over too short a stem: every
# G7-sized shell fails on strain, whatever else it does.
STRAIN = {SnapShellFitCheck.CLIP_STRAIN}


def failed(request: SnapShellRequest) -> set[SnapShellFitCheck]:
    backend = SyntheticSnapShellBackend()
    report = backend.analyze_fit(backend.derive(request))

    return {result.check for result in report.failures}


def test_backend_satisfies_protocol() -> None:
    backend = SyntheticSnapShellBackend()

    assert isinstance(
        backend,
        SnapShellBackend,
    )


def test_derive_reuses_validated_parameters() -> None:
    backend = SyntheticSnapShellBackend()

    parameters = backend.derive(valid_request())

    assert parameters.device_thickness_mm == pytest.approx(THICKNESS)
    assert parameters.locations == spaced_locations()
    assert parameters.clip_width_mm == pytest.approx(3.0)


def test_apply_requires_cadquery_workplane() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    with pytest.raises(
        TypeError,
        match="cadquery.Workplane",
    ):
        backend.apply(
            object(),
            parameters,
        )


def test_apply_adds_snap_shell_geometry() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    base = cq.Workplane("XY").box(LENGTH, WIDTH, THICKNESS).translate((0, 0, 2.35))

    base_volume = workplane_shape(base).Volume()

    result = backend.apply(
        base,
        parameters,
    )

    assert isinstance(
        result,
        cq.Workplane,
    )
    assert workplane_shape(result).Volume() > base_volume


def test_apply_is_deterministic() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())
    base = cq.Workplane("XY").box(LENGTH, WIDTH, THICKNESS)

    first = backend.apply(
        base,
        parameters,
    )
    second = backend.apply(
        base,
        parameters,
    )

    assert workplane_shape(first).Volume() == pytest.approx(
        workplane_shape(second).Volume()
    )


def test_a_g7_sized_shell_fits_but_its_clips_strain_too_far() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    assert {result.check for result in report.results} == set(SnapShellFitCheck)
    assert {result.check for result in report.failures} == STRAIN
    (strain,) = report.failures
    # 1 mm stem, 4.7 + 0.15 - 1.0 mm from the rim to the lip, 0.6 mm swing.
    assert strain.detail.startswith(
        "A 1 mm stem bending over 3.85 mm to swing 0.6 mm strains 6.1 per cent, "
        "over the 1.5 per cent limit"
    )


def test_a_mobi_sized_shell_passes_every_check() -> None:
    backend = SyntheticSnapShellBackend()
    length, width, thickness = 51.3, 37.3, 14.2
    request = SnapShellRequest(
        device_thickness_mm=thickness,
        device_length_mm=length,
        device_width_mm=width,
        locations=(
            SnapShellLocation("north", 0.0, width / 2, 270.0),
            SnapShellLocation("south", 0.0, -width / 2, 90.0),
            SnapShellLocation("east", length / 2, 0.0, 180.0),
            SnapShellLocation("west", -length / 2, 0.0, 0.0),
        ),
        policy=SnapShellPolicy(),
    )

    report = backend.analyze_fit(backend.derive(request))

    assert report.passed
    strain = next(r for r in report.results if r.check is SnapShellFitCheck.CLIP_STRAIN)
    assert "strains 0.5 per cent, within" in strain.detail


def test_a_rim_up_to_the_lip_leaves_the_stem_nothing_to_bend() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(
        valid_request(SnapShellPolicy(rim_height_mm=THICKNESS + 0.15))
    )
    report = backend.analyze_fit(parameters)
    (strain,) = (r for r in report.failures if r.check is SnapShellFitCheck.CLIP_STRAIN)

    assert "no length to bend" in strain.detail


@pytest.mark.parametrize("clearance", [0.15, 1.0])
def test_no_shell_material_stands_inside_the_device(clearance: float) -> None:
    # The review that found the old clips 44 mm3 inside a G7-sized body, and
    # 57-64 mm3 at a 1 mm clearance, measured exactly this.
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(
        valid_request(SnapShellPolicy(clearance_mm=clearance, rim_height_mm=1.5))
    )
    shell = workplane_shape(backend.build_geometry(parameters))

    assert intersection_volume(shell, device()) == 0.0
    assert backend.clips_into_device_mm3(parameters) == 0.0
    assert {r.check for r in backend.analyze_fit(parameters).failures} == STRAIN


def test_the_device_rests_on_the_frame_and_the_lips_hold_it_down() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())
    shell = workplane_shape(backend.build_geometry(parameters))
    box = shell.BoundingBox()

    # Under the device: the frame's plate, from its underside down a wall.
    assert box.zmin == pytest.approx(-parameters.wall_mm)
    under = cq.Solid.makeBox(1.0, 1.0, 0.5, pnt=cq.Vector(-LENGTH / 2, 0, -0.5))
    assert intersection_volume(shell, under) > 0
    # Open in the middle, past the ledge.
    middle = cq.Solid.makeBox(1.0, 1.0, 0.5, pnt=cq.Vector(0, 0, -0.5))
    assert intersection_volume(shell, middle) == 0.0
    # The lip's top: the device's top face, the gap, then the lip.
    assert box.zmax == pytest.approx(
        THICKNESS + parameters.clearance_mm + parameters.clip_height_mm
    )


def test_continuity_engagement_and_clearance_detail_are_measured() -> None:
    backend = SyntheticSnapShellBackend()
    report = backend.analyze_fit(backend.derive(valid_request()))
    details = {result.check: result.detail for result in report.results}

    assert details[SnapShellFitCheck.SHELL_MATERIAL_CONTINUITY] == (
        "The frame and every clip are one solid."
    )
    assert (
        "0.6 mm in over the device's top edge"
        in (details[SnapShellFitCheck.SNAP_ENGAGEMENT])
    )
    assert (
        "No shell material is inside the device's envelope"
        in (details[SnapShellFitCheck.DEVICE_CLEARANCE])
    )


def test_a_clip_turned_away_from_the_device_stands_in_it() -> None:
    north, south, east = spaced_locations()
    turned = replace(north, rotation_degrees=90.0)

    assert (
        failed(valid_request(locations=(turned, south, east)))
        == {SnapShellFitCheck.DEVICE_CLEARANCE} | STRAIN
    )


def test_a_clip_past_the_device_corner_holds_nothing() -> None:
    north, south, east = spaced_locations()
    past = replace(north, x_mm=LENGTH / 2 + 2.0)

    assert (
        failed(valid_request(locations=(past, south, east)))
        == {SnapShellFitCheck.SNAP_ENGAGEMENT} | STRAIN
    )


def test_a_clip_inside_the_device_is_refused() -> None:
    # The old anchor: the stem a wall's width in from the edge.
    north, south, east = spaced_locations()
    inside = replace(east, x_mm=east.x_mm - 1.15)

    assert failed(valid_request(locations=(north, south, inside))) >= {
        SnapShellFitCheck.DEVICE_CLEARANCE,
        SnapShellFitCheck.SNAP_ENGAGEMENT,
    }


def test_a_clip_off_the_frame_breaks_continuity() -> None:
    north, south, east = spaced_locations()
    away = replace(east, x_mm=east.x_mm + 10.0)

    assert SnapShellFitCheck.SHELL_MATERIAL_CONTINUITY in failed(
        valid_request(locations=(north, south, away))
    )


def test_the_rim_is_notched_at_an_edge_feature() -> None:
    port = EdgeFeature("port", "west", center_offset_mm=0.0, width_mm=4.0)
    backend = SyntheticSnapShellBackend()
    plain = backend.derive(valid_request())
    notched = replace(plain, edge_features=(port,))
    # A probe in the rim, at the port, beside the device's west edge.
    probe = cq.Solid.makeBox(
        0.5, 1.0, 0.5, pnt=cq.Vector(-LENGTH / 2 - 0.9, -0.5, 0.25)
    )

    assert (
        intersection_volume(workplane_shape(backend.build_geometry(plain)), probe) > 0
    )
    assert (
        intersection_volume(workplane_shape(backend.build_geometry(notched)), probe)
        == 0.0
    )
    assert {r.check for r in backend.analyze_fit(notched).failures} == STRAIN


def test_anchor_separation_fails_when_locations_are_collinear() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=(
            SnapShellLocation(label="a", x_mm=0.0, y_mm=0.0),
            SnapShellLocation(label="b", x_mm=5.0, y_mm=0.0),
            SnapShellLocation(label="c", x_mm=10.0, y_mm=0.0),
        ),
        clip_width_mm=3.0,
        wall_mm=1.0,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.15,
        compliant_span_mm=2.0,
        device_length_mm=LENGTH,
        device_width_mm=WIDTH,
        ledge_mm=1.5,
        rim_height_mm=1.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.ANCHOR_SEPARATION in {
        result.check for result in report.failures
    }


def test_anchor_separation_fails_when_locations_are_too_close() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=(
            SnapShellLocation(label="a", x_mm=0.0, y_mm=0.0),
            SnapShellLocation(label="b", x_mm=1.0, y_mm=0.0),
            SnapShellLocation(label="c", x_mm=0.0, y_mm=1.0),
        ),
        clip_width_mm=3.0,
        wall_mm=1.0,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.15,
        compliant_span_mm=2.0,
        device_length_mm=LENGTH,
        device_width_mm=WIDTH,
        ledge_mm=1.5,
        rim_height_mm=1.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.ANCHOR_SEPARATION in {
        result.check for result in report.failures
    }


def test_manufacturing_gate_fails_closed() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=spaced_locations(),
        clip_width_mm=0.15,
        wall_mm=0.30,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.05,
        compliant_span_mm=2.0,
        device_length_mm=LENGTH,
        device_width_mm=WIDTH,
        ledge_mm=1.5,
        rim_height_mm=1.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.MANUFACTURING_CLEARANCE in {
        result.check for result in report.failures
    }
