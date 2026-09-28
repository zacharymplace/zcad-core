"""Tandem Mobi insulin pump specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TandemMobiSpec:
    """Mechanical specification for the Tandem Mobi pump body.

    Body dimensions come from a peer-reviewed secondary source, not a
    caliper capture or Tandem's own spec sheet directly, and secondary
    sources disagree on width by about 12 mm (see ``geometry_source``),
    so they are only good for rough envelope sizing, not for
    tight-tolerance features. This target
    is not eligible for candidate generation until it has a real
    physical capture. Charging-contact and fill-port cutout geometry is
    deliberately not modeled yet; a clip or holster candidate must not
    cover those features, so they need a real physical capture before
    any retention geometry is generated.
    """

    identifier: str = "TANDEM_MOBI"

    geometry_evidence_status: str = "manufacturer-published"
    geometry_source: str = (
        "Tandem Mobi body 2.02 x 1.47 x 0.56 in (51.3 x 37.3 x 14.2 mm, "
        "L x W x H) per the peer-reviewed Mobi overview PMC13089864 "
        "(https://pmc.ncbi.nlm.nih.gov/articles/PMC13089864/). "
        "Conflicts with diabetesnet.com's Tandem Mobi technology "
        "summary, which reports 2.0 x 1.95 x 0.57 in (50.8 x 49.5 x "
        "14.5 mm), weight 56.7g: width differs by ~12 mm. PMC figures "
        "adopted as the better-sourced value, matching mobi-gear's "
        "measurements.json. Not a caliper capture. Replace with "
        "caliper-verified capture before generating any print "
        "candidate."
    )

    body_length_mm: float = 51.3
    body_width_mm: float = 37.3
    body_thickness_mm: float = 14.2

    recommended_clip_clearance_mm: float = 0.5


_MOBI = TandemMobiSpec()


def get_tandem_mobi() -> TandemMobiSpec:
    """Return the Tandem Mobi pump specification."""
    return _MOBI
