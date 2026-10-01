"""What a fixture accuracy profile says about a new fixture's pins.

A build given a profile pooled from trials (see
:mod:`zcad_core.profiles.fixture_accuracy`) reports the measured offsets beside
each point's slack and the worst-case sum the build computed, and says when the
measured offsets are bigger than either. A measured offset bigger than a pad's
slack is a finding, not an error: it says the pooled prints missed by more than
this pad allows, so a pin on it may miss, whatever the worst-case sum said.

The profile never replaces the sum. It is evidence about the prints that were
measured, with their sample size, and not a guarantee for this fixture.
"""

from __future__ import annotations

from typing import Any

from zcad_core.features.pcb_fixture import PcbFixture
from zcad_core.profiles.fixture_accuracy import FixtureAccuracyProfile


def measured_accuracy(
    fixture: PcbFixture, profile: FixtureAccuracyProfile, material_profile_id: str
) -> dict[str, Any]:
    """The profile's figures against this fixture's points. Refuses a profile for
    another printer or material, whose offsets say nothing about this one."""

    if profile.printer_profile_id != fixture.profile_id:
        raise ValueError(
            f"The accuracy profile is for printer {profile.printer_profile_id}; "
            f"this fixture is for {fixture.profile_id}"
        )

    if profile.material_profile_id != material_profile_id:
        raise ValueError(
            f"The accuracy profile is for {profile.material_profile_id}; this "
            f"fixture is for {material_profile_id}"
        )

    figure = profile.position
    largest = float(figure["max"])
    points = []
    warnings = []

    for point in fixture.plan.points:
        slack = point.pad_diameter_mm / 2 - fixture.spec.pin.tip_diameter_mm / 2
        assumed = fixture.plan.budgets[point.identifier].total_mm
        over_slack = largest > slack + 1e-9
        points.append(
            {
                "identifier": point.identifier,
                "slack_mm": round(slack, 3),
                "assumed_misalignment_mm": round(assumed, 3),
                "measured_max_exceeds_slack": over_slack,
                "measured_max_exceeds_assumed": largest > assumed + 1e-9,
            }
        )

        if over_slack:
            warnings.append(
                f"{point.identifier}: the measured offset reached {largest:.2f} mm "
                f"in {figure['samples']} samples, more than this pad's "
                f"{slack:.2f} mm of slack: the pin may miss"
            )

    return {
        "profile": profile.reference(),
        "described": profile.describe(),
        "note": (
            "Measured offsets of pin tips from passing trials on this printer and "
            "material. They are evidence about those prints and how they were "
            "measured, with the sample size given, and not a guarantee for this "
            "fixture; the worst-case sum is still a bound from provisional "
            "tolerances."
        ),
        "figures": profile.payload["figures"],
        "points": points,
        "warnings": warnings,
    }
