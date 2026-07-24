"""Assembly definition for enclosure body and lid."""

from zcad.assemblies.models import (
    Assembly,
    AssemblyPart,
    Mate,
)


def build_enclosure_assembly(
    *,
    assembly_id: str,
    lid_clearance: float,
    lid_engagement: float,
) -> Assembly:
    """Create the standard body-and-lid enclosure assembly."""
    return Assembly(
        assembly_id=assembly_id,
        reference_part="body",
        parts=(
            AssemblyPart(
                name="body",
            ),
            AssemblyPart(
                name="lid",
            ),
        ),
        relationships=(
            Mate(
                parent="body",
                child="lid",
                kind="sliding_fit",
                axis="z",
                direction="negative",
                clearance_mm=lid_clearance,
                engagement_mm=lid_engagement,
            ),
        ),
    )
