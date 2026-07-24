"""Tests for declarative assembly models."""

import pytest

from zcad.assemblies.enclosure import (
    build_enclosure_assembly,
)
from zcad.assemblies.models import (
    Assembly,
    AssemblyPart,
    Mate,
)
from zcad.assemblies.validation import (
    validate_assembly,
)


def test_enclosure_assembly_is_valid() -> None:
    assembly = build_enclosure_assembly(
        assembly_id="default-enclosure",
        lid_clearance=0.25,
        lid_engagement=4.0,
    )

    validate_assembly(
        assembly,
        generated_part_names={
            "body",
            "lid",
        },
    )

    record = assembly.to_dict()

    assert record["reference_part"] == "body"
    assert len(record["parts"]) == 2
    assert record["relationships"][0]["kind"] == "sliding_fit"
    assert record["relationships"][0]["clearance_mm"] == pytest.approx(0.25)


def test_missing_generated_part_is_rejected() -> None:
    assembly = build_enclosure_assembly(
        assembly_id="test",
        lid_clearance=0.25,
        lid_engagement=4.0,
    )

    with pytest.raises(
        ValueError,
        match="missing generated parts",
    ):
        validate_assembly(
            assembly,
            generated_part_names={
                "body",
            },
        )


def test_undeclared_generated_part_is_rejected() -> None:
    assembly = build_enclosure_assembly(
        assembly_id="test",
        lid_clearance=0.25,
        lid_engagement=4.0,
    )

    with pytest.raises(
        ValueError,
        match="missing from assembly",
    ):
        validate_assembly(
            assembly,
            generated_part_names={
                "body",
                "lid",
                "insert",
            },
        )


def test_invalid_mate_part_is_rejected() -> None:
    assembly = Assembly(
        assembly_id="invalid",
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
                child="missing",
                kind="sliding_fit",
                axis="z",
                direction="negative",
                clearance_mm=0.25,
                engagement_mm=4.0,
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="Mate child",
    ):
        validate_assembly(
            assembly,
            generated_part_names={
                "body",
                "lid",
            },
        )


@pytest.mark.parametrize(
    "mate",
    [
        Mate(
            parent="body",
            child="body",
            kind="sliding_fit",
            axis="z",
            direction="negative",
        ),
        Mate(
            parent="body",
            child="lid",
            kind="unknown",
            axis="z",
            direction="negative",
        ),
        Mate(
            parent="body",
            child="lid",
            kind="sliding_fit",
            axis="q",
            direction="negative",
        ),
        Mate(
            parent="body",
            child="lid",
            kind="sliding_fit",
            axis="z",
            direction="down",
        ),
        Mate(
            parent="body",
            child="lid",
            kind="sliding_fit",
            axis="z",
            direction="negative",
            clearance_mm=-0.1,
        ),
    ],
)
def test_invalid_mates_are_rejected(
    mate: Mate,
) -> None:
    with pytest.raises(ValueError):
        mate.validate()
