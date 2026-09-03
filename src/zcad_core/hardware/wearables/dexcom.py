"""Dexcom continuous glucose monitor specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DexcomG7Spec:
    """Mechanical specification for the Dexcom G7 sensor and transmitter.

    The body dimensions come from Dexcom's own published technical
    specification sheet, not a caliper capture, so they are trustworthy
    for envelope sizing but not for tight-tolerance features (edge
    radii, seam lines). The adhesive patch diameter is a rough visual
    estimate with no manufacturer source. This target is not eligible
    for candidate generation until it has a real physical capture.

    The device is a rounded rectangle, not a circular puck.
    """

    identifier: str = "DEXCOM_G7"

    geometry_evidence_status: str = "manufacturer-published"
    geometry_source: str = (
        "Dexcom G7 Technical Specifications Sheet (LBL-1002469 Rev001, "
        "Jan 2023): wearable dimensions 2.74 x 2.41 x 0.47 cm (L x W x H), "
        "without sensor wire or patch; wire length 5.7mm. Adhesive patch "
        "diameter is a rough visual estimate, not manufacturer-sourced. "
        "Replace with caliper-verified capture before generating any "
        "print candidate."
    )

    body_length_mm: float = 27.4
    body_width_mm: float = 24.1
    body_thickness_mm: float = 4.7
    wire_length_mm: float = 5.7
    adhesive_patch_diameter_mm: float = 42.0

    recommended_shell_clearance_mm: float = 0.5


_G7 = DexcomG7Spec()


def get_dexcom_g7() -> DexcomG7Spec:
    """Return the Dexcom G7 sensor specification."""
    return _G7
