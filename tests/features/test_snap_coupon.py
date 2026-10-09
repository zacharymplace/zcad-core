"""The snap coupon: drawer detents at a ladder of engagements, and the profile they feed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.mounts import measured_strain_limit
from zcad_core.features.snap_coupon import (
    BUILD_RECORD,
    FRAME_WALL_MM,
    RUNG_GAP_MM,
    SNAP_ENGAGEMENTS_MM,
    SnapCoupon,
    SnapRung,
    build_snap_coupon,
    snap_coupon_checks,
    snap_frame_plan,
)
from zcad_core.features.stack_detent import DEFAULT_DETENT_ENGAGEMENT_MM
from zcad_core.features.stack_file import Item, detent_engagement
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.profiles.joints import (
    DETENT,
    JOINT_TRIAL_RECORD,
    SLIDING,
    derive_joint_profile,
    load_joint_profile,
    measured_fits,
    write_joint_profile,
)

PRINTER = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


@pytest.fixture(scope="module")
def coupon() -> SnapCoupon:
    return build_snap_coupon(0.2, 1.2)


def test_each_rung_is_the_products_detent_at_its_engagement(coupon: SnapCoupon) -> None:
    assert [rung.engagement_mm for rung in coupon.rungs] == list(SNAP_ENGAGEMENTS_MM)

    for rung in coupon.rungs:
        assert rung.detent.engagement_mm == rung.engagement_mm
        assert rung.detent.protrusion_mm == pytest.approx(0.2 + rung.engagement_mm)
        assert rung.detent.dimple_depth_mm < FRAME_WALL_MM


def shut(rung: SnapRung) -> cq.Shape:
    """The rung's drawer pushed home in its frame: it printed in front of it."""

    plan = snap_frame_plan(0.2)

    return workplane_shape(
        rung.drawer.translate((0.0, plan.outer_depth + RUNG_GAP_MM, 0.0))
    )


def test_a_shut_drawer_clears_its_frame_with_its_bumps_in_the_dimples(
    coupon: SnapCoupon,
) -> None:
    for rung in coupon.rungs:
        assert intersection_volume(
            workplane_shape(rung.frame), shut(rung)
        ) == pytest.approx(0.0, abs=1e-6), rung.name


def test_each_bump_reaches_past_the_frames_face_by_its_engagement(
    coupon: SnapCoupon,
) -> None:
    plan = snap_frame_plan(0.2)

    for index, rung in enumerate(coupon.rungs):
        detent = rung.detent
        x = index * (plan.outer_width + RUNG_GAP_MM)
        wall = cq.Solid.makeBox(
            FRAME_WALL_MM,
            plan.outer_depth,
            plan.roof_z,
            cq.Vector(x + plan.inner_width / 2, -plan.outer_depth / 2, 0.0),
        )

        assert detent.drawer_half_mm + detent.protrusion_mm - detent.frame_half_mm == (
            pytest.approx(rung.engagement_mm)
        )
        # Without its dimple, the frame's wall would stand in the bump's way.
        assert intersection_volume(wall, shut(rung)) > 0.0, rung.name


def test_the_coupon_passes_its_checks_and_a_small_bed_refuses_it(
    coupon: SnapCoupon,
) -> None:
    checks = snap_coupon_checks(coupon, {"x": 180, "y": 180, "z": 180})

    assert all(check["passed"] for check in checks.values()), checks
    assert not snap_coupon_checks(coupon, {"x": 100, "y": 180, "z": 180})["fits_bed"][
        "passed"
    ]


def build(tmp_path: Path, name: str = "snap-01") -> Path:
    output = tmp_path / "evidence" / "joints" / name
    command = [
        "joint",
        "build",
        "snap",
        "--output-directory",
        str(output),
        "--printer-profile",
        str(PRINTER),
    ]

    assert main(command) == 0

    return output / BUILD_RECORD


HOLDS = {"clicks_shut": True, "holds_shake": True, "lets_go": True, "whitened": False}
LOOSE = {**HOLDS, "holds_shake": False}
TIGHT = {**HOLDS, "whitened": True}


def fill(trial: Path, readings: dict[float, Any], result: str = "pass") -> None:
    """Answer both checks with ``result`` and read each rung as ``readings`` says
    by engagement; a rung not named is skipped."""

    observations = json.loads((trial / "observations.json").read_text("utf-8"))

    for entry in observations.values():
        if "reading" in entry:
            entry["reading"] = readings.get(entry["engagement_mm"], "skipped")
        else:
            entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")


def test_the_build_and_its_trial_record_how_each_rung_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    record_path = build(tmp_path)
    record = json.loads(record_path.read_text("utf-8"))

    assert record["family"] == "snap"
    assert record["strain_limit"] == 0.015
    assert [rung["dots"] for rung in record["rungs"]] == [1, 2, 3, 4]
    assert set(record["parts"]) == {"frames", "drawers"}

    assert main(["joint", "trial", "start", "--build-record", str(record_path)]) == 0
    trial = record_path.parent / "trials" / "trial-001"
    fill(trial, {0.3: {**HOLDS, "clicks_shut": "yes"}})
    command = ["joint", "trial", "complete", "--trial-directory", str(trial)]
    capsys.readouterr()

    assert main(command) == 1
    assert "must be true or false" in capsys.readouterr().err

    fill(trial, {0.3: LOOSE, 0.4: HOLDS, 0.5: {**TIGHT, "pull_force_n": 6.5}})

    assert main(command) == 0
    written = json.loads((trial / JOINT_TRIAL_RECORD).read_text("utf-8"))

    assert [entry["engagement_mm"] for entry in written["readings"]] == [0.3, 0.4, 0.5]
    assert written["readings"][2]["pull_force_n"] == 6.5
    assert written["strain_limit"] == 0.015


def snap_record(
    evidence: Path,
    name: str,
    readings: dict[float, dict[str, Any]],
    limit: float = 0.015,
) -> None:
    folder = evidence / "joints" / name / "trials" / "trial-001"
    folder.mkdir(parents=True)
    (folder / JOINT_TRIAL_RECORD).write_text(
        json.dumps(
            {
                "family": "snap",
                "trial_id": name,
                "generator_version": "1.0.0",
                "printer_profile_id": "bambu-lab-a1-mini",
                "material_profile_id": "petg",
                "strain_limit": limit,
                "readings": [
                    {"engagement_mm": engagement, **reading}
                    for engagement, reading in readings.items()
                ],
            }
        ),
        "utf-8",
    )


def derive(evidence: Path) -> dict[str, Any]:
    return derive_joint_profile(
        evidence, printer_profile_id="bambu-lab-a1-mini", material_profile_id="petg"
    )


def test_the_detent_is_the_least_rung_that_holds_in_every_trial(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    snap_record(evidence, "a", {0.3: LOOSE, 0.4: HOLDS, 0.5: HOLDS, 0.6: TIGHT})

    with pytest.raises(ValueError, match="at least 2 of one family"):
        derive(evidence)

    # The second print's 0.4 mm rung did not hold: 0.5 is the least that held in both.
    snap_record(evidence, "b", {0.3: LOOSE, 0.4: LOOSE, 0.5: HOLDS, 0.6: TIGHT})
    profile = derive(evidence)

    assert profile["figures"][DETENT]["value_mm"] == 0.5
    assert profile["strain_limit"] == 0.015
    assert profile["hole_oversize_mm"] is None
    assert SLIDING not in profile["figures"]
    assert "left out" in profile["families"]["fit"]


def test_a_detent_no_rung_holds_is_left_to_the_engine(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    snap_record(evidence, "a", {0.3: LOOSE, 0.6: TIGHT})
    snap_record(evidence, "b", {0.3: LOOSE, 0.6: TIGHT})
    figure = derive(evidence)["figures"][DETENT]

    assert figure["value_mm"] is None
    assert "engine's own figure stands" in figure["reason"]


def test_snap_trials_at_different_strain_limits_are_refused(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    snap_record(evidence, "a", {0.4: HOLDS})
    snap_record(evidence, "b", {0.4: HOLDS}, limit=0.02)

    with pytest.raises(ValueError, match="different strain_limit"):
        derive(evidence)


def detent_profile(tmp_path: Path, limit: float = 0.015) -> Path:
    evidence = tmp_path / f"evidence-{limit}"
    snap_record(evidence, "a", {0.3: LOOSE, 0.5: HOLDS}, limit)
    snap_record(evidence, "b", {0.3: LOOSE, 0.5: HOLDS}, limit)
    path = tmp_path / f"joints-{limit}.json"
    write_joint_profile(derive(evidence), path)

    return path


def test_a_stack_given_a_profile_builds_its_detent_at_the_measured_engagement(
    tmp_path: Path,
) -> None:
    frame = Item(kind="frame", name="frame", cells=(1, 1), detent=True)
    own = Item(
        kind="frame", name="own", cells=(1, 1), detent=True, detent_engagement_mm=0.45
    )
    profile = load_joint_profile(detent_profile(tmp_path))

    assert detent_engagement(frame) == DEFAULT_DETENT_ENGAGEMENT_MM

    with measured_fits(profile):
        assert detent_engagement(frame) == 0.5
        # A stack file's own engagement is what its author asked for.
        assert detent_engagement(own) == 0.45

    assert detent_engagement(frame) == DEFAULT_DETENT_ENGAGEMENT_MM


def test_a_detent_measured_at_another_strain_limit_is_refused(tmp_path: Path) -> None:
    frame = Item(kind="frame", name="frame", cells=(1, 1), detent=True)
    profile = load_joint_profile(detent_profile(tmp_path))

    with (
        measured_fits(profile),
        measured_strain_limit(0.025, "a coupon"),
        pytest.raises(ValueError, match="print a new snap coupon"),
    ):
        detent_engagement(frame)


def test_a_profile_with_only_a_detent_leaves_the_fits_alone(tmp_path: Path) -> None:
    profile = load_joint_profile(detent_profile(tmp_path))

    assert profile.fits() == {}
    assert profile.reference()["detent_engagement_mm"] == 0.5
