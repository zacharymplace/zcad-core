"""The flexure strain limit: provisional by default, measured only when asked."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from zcad_core.cli import main, nest
from zcad_core.cli._common import applied_strain_limit
from zcad_core.features.mounts import (
    FLEXURE_STRAIN_LIMIT,
    flexure_for,
    flexure_strain_limit,
    measured_strain_limit,
    strain_limit_source,
)
from zcad_core.features.nest_features import tab_strain


def profile(tmp_path: Path, strain_limit: dict[str, object] | None) -> Path:
    path = tmp_path / "bambu-lab-a1-mini-petg.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "profile_id": "bambu-lab-a1-mini-petg",
                "version": 3,
                "figures": {},
                "strain_limit": strain_limit,
            }
        ),
        "utf-8",
    )
    return path


def test_flexures_are_held_to_the_provisional_limit_unless_a_build_asks() -> None:
    assert flexure_strain_limit() == FLEXURE_STRAIN_LIMIT
    assert strain_limit_source() == "provisional"

    with measured_strain_limit(0.022, "a profile"):
        assert flexure_strain_limit() == 0.022
        assert strain_limit_source() == "a profile"
        assert flexure_for(1.0, 10.0, 1.0).strain_limit == 0.022

    # Only for the length of the build that asked.
    assert flexure_strain_limit() == FLEXURE_STRAIN_LIMIT
    assert flexure_for(1.0, 10.0, 1.0).strain_limit == FLEXURE_STRAIN_LIMIT


def test_an_implausible_limit_is_refused() -> None:
    with (
        pytest.raises(ValueError, match="not a plausible measurement"),
        measured_strain_limit(0.5, "a typo"),
    ):
        pass


def test_a_profile_applies_its_measured_limit_and_only_that(tmp_path: Path) -> None:
    with applied_strain_limit(None):
        assert strain_limit_source() == "provisional"

    # A profile with no measured limit leaves the provisional one alone.
    with applied_strain_limit(profile(tmp_path, {"value": None})):
        assert flexure_strain_limit() == FLEXURE_STRAIN_LIMIT

    with applied_strain_limit(profile(tmp_path, {"value": 0.02})):
        assert flexure_strain_limit() == 0.02
        assert strain_limit_source() == "bambu-lab-a1-mini-petg version 3"


def test_a_command_runs_under_its_profile_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[float, str]] = []

    def check(args: argparse.Namespace) -> int:
        seen.append((flexure_strain_limit(), strain_limit_source()))
        return 0

    monkeypatch.setattr(nest, "_nest_check", check)
    measured = profile(tmp_path, {"value": 0.025})

    assert main(["nest", "check", "part.json"]) == 0
    assert (
        main(["nest", "check", "part.json", "--compensation-profile", str(measured)])
        == 0
    )
    assert main(["nest", "check", "part.json"]) == 0

    assert seen == [
        (FLEXURE_STRAIN_LIMIT, "provisional"),
        (0.025, "bambu-lab-a1-mini-petg version 3"),
        (FLEXURE_STRAIN_LIMIT, "provisional"),
    ]


def test_a_measured_limit_decides_a_check_that_reads_it() -> None:
    # A nest's lip tab on a part 10 mm tall strains about 2.1 per cent: past the
    # provisional limit, within a measured 4 per cent.
    strain, _, _ = tab_strain(10.0, 1.2, 0.6, 0.2)

    assert strain > FLEXURE_STRAIN_LIMIT
    with measured_strain_limit(0.04, "a profile"):
        assert strain < flexure_strain_limit()
