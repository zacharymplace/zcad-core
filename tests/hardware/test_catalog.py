"""Tests for the typed hardware catalog."""

from dataclasses import dataclass

import pytest

from zcad_core.hardware.catalog import (
    HardwareCatalog,
)


@dataclass(frozen=True)
class ExampleSpec:
    """Small test specification."""

    identifier: str
    value: float


def test_catalog_lookup_is_case_insensitive() -> None:
    catalog = HardwareCatalog(
        category="example",
        entries={
            "PART-A": ExampleSpec(
                identifier="PART-A",
                value=1.0,
            ),
        },
    )

    assert catalog.get("part-a").value == 1.0


def test_catalog_identifiers_are_sorted() -> None:
    catalog = HardwareCatalog(
        category="example",
        entries={
            "PART-B": ExampleSpec(
                identifier="PART-B",
                value=2.0,
            ),
            "PART-A": ExampleSpec(
                identifier="PART-A",
                value=1.0,
            ),
        },
    )

    assert catalog.identifiers() == (
        "PART-A",
        "PART-B",
    )


def test_catalog_rejects_key_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="key does not match",
    ):
        HardwareCatalog(
            category="example",
            entries={
                "PART-A": ExampleSpec(
                    identifier="PART-B",
                    value=1.0,
                ),
            },
        )


def test_catalog_rejects_unknown_identifier() -> None:
    catalog = HardwareCatalog(
        category="example",
        entries={
            "PART-A": ExampleSpec(
                identifier="PART-A",
                value=1.0,
            ),
        },
    )

    with pytest.raises(
        ValueError,
        match="Unsupported example",
    ):
        catalog.get("PART-Z")
