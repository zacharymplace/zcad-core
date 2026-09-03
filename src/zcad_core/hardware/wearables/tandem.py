"""Tandem Mobi insulin pump specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TandemMobiSpec:
    """Mechanical specification for the Tandem Mobi pump body.

    Body dimensions are corroborated across multiple secondary sources
    reporting Tandem's published figures, not a caliper capture or
    Tandem's own spec sheet directly, so they are trustworthy for
    envelope sizing but not for tight-tolerance features. This target
    is not eligible for candidate generation until it has a real
    physical capture. Charging-contact and fill-port cutout geometry is
    deliberately not modeled yet; a clip or holster candidate must not
    cover those features, so they need a real physical capture before
    any retention geometry is generated.
    """

    identifier: str = "TANDEM_MOBI"

    geometry_evidence_status: str = "manufacturer-published"
    geometry_source: str = (
        "Tandem Mobi dimensions reported as 2.0 x 1.95 x 0.57 in "
        "(5.08 x 4.95 x 1.45 cm, L x W x H), weight 56.7g, per "
        "diabetesnet.com's Tandem Mobi technology summary, citing "
        "Tandem's published figures. Not a caliper capture. Replace "
        "with caliper-verified capture before generating any print "
        "candidate."
    )

    body_length_mm: float = 50.8
    body_width_mm: float = 49.5
    body_thickness_mm: float = 14.5

    recommended_clip_clearance_mm: float = 0.5


_MOBI = TandemMobiSpec()


def get_tandem_mobi() -> TandemMobiSpec:
    """Return the Tandem Mobi pump specification."""
    return _MOBI
