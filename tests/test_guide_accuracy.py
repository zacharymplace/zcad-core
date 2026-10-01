"""Pooling guide trials into a measured accuracy profile."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from zcad_core.profiles.guide_accuracy import (
    collect_guide_trials,
    derive_guide_profile,
    load_guide_profile,
    write_guide_profile,
)

PRINTER = "bambu-lab-a1-mini"


def offset(dx: float, dy: float) -> dict[str, float]:
    return {"dx": dx, "dy": dy, "radial": round(math.hypot(dx, dy), 3)}


def trial(
    root: Path,
    name: str,
    bores: list[dict[str, Any]],
    *,
    passed: bool = True,
    printer: str = PRINTER,
    material: str = "petg",
) -> Path:
    directory = root / name / "trials" / "trial-001"
    directory.mkdir(parents=True)
    path = directory / "guide-trial.json"
    path.write_text(
        json.dumps(
            {
                "trial_id": "trial-001",
                "passed": passed,
                "printer_profile_id": printer,
                "material_profile_id": material,
                "bores": bores,
            }
        )
    )

    return path


def printed(dx: float, dy: float, error: float | None = None) -> dict[str, Any]:
    bore: dict[str, Any] = {"kind": "printed", "offset_mm": offset(dx, dy)}

    if error is not None:
        bore["bore_error_mm"] = error

    return bore


def bushed(dx: float, dy: float, error: float | None = None) -> dict[str, Any]:
    bore: dict[str, Any] = {"kind": "bushing", "offset_mm": offset(dx, dy)}

    if error is not None:
        bore["seat_error_mm"] = error

    return bore


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    trial(
        tmp_path,
        "a",
        [printed(0.3, 0.0, -0.1), printed(0.0, 0.4, -0.2), bushed(0.1, 0.0, 0.05)],
    )
    trial(tmp_path, "b", [printed(0.3, 0.4), bushed(-0.1, 0.0, 0.15)])

    return tmp_path


def test_only_passing_trials_of_the_same_printer_and_material_are_collected(
    tmp_path: Path,
) -> None:
    trial(tmp_path, "ok", [printed(0.1, 0.0)])
    trial(tmp_path, "failed", [printed(0.1, 0.0)], passed=False)
    trial(tmp_path, "other-printer", [printed(0.1, 0.0)], printer="prusa-mk4")
    trial(tmp_path, "other-material", [printed(0.1, 0.0)], material="pla")

    found = collect_guide_trials(
        tmp_path, printer_profile_id=PRINTER, material_profile_id="petg"
    )

    assert [path.parts[-4] for path, _ in found] == ["ok"]


def test_offsets_are_pooled_per_kind_of_bore(evidence: Path) -> None:
    profile = derive_guide_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id="petg"
    )
    position = profile["figures"]["position"]

    # Three printed bores: radial 0.3, 0.4, 0.5; two bushing bores: 0.1 and 0.1.
    assert position["printed"]["samples"] == 3
    assert position["printed"]["mean"] == pytest.approx(0.4)
    assert position["printed"]["max"] == pytest.approx(0.5)
    assert position["printed"]["spread"] == pytest.approx(0.0816, abs=1e-3)
    assert position["bushing"]["samples"] == 2
    assert position["bushing"]["mean"] == pytest.approx(0.1)
    assert profile["trials"] == 2


def test_a_bias_shows_when_every_hole_lands_the_same_way(evidence: Path) -> None:
    printed_bias = derive_guide_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id="petg"
    )["figures"]["position"]["printed"]["bias_mm"]

    assert printed_bias == [pytest.approx(0.2), pytest.approx(0.2667, abs=1e-3)]


def test_the_printed_hole_and_seat_errors_are_pooled(evidence: Path) -> None:
    figures = derive_guide_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id="petg"
    )["figures"]

    assert figures["bore_diameter_error_mm"]["mean"] == pytest.approx(-0.15)
    assert figures["bore_diameter_error_mm"]["samples"] == 2
    assert figures["seat_diameter_error_mm"]["mean"] == pytest.approx(0.1)


def test_a_kind_with_no_samples_has_no_figure(tmp_path: Path) -> None:
    trial(tmp_path, "a", [printed(0.1, 0.0)])
    trial(tmp_path, "b", [printed(0.2, 0.0)])
    figures = derive_guide_profile(
        tmp_path, printer_profile_id=PRINTER, material_profile_id="petg"
    )["figures"]

    assert figures["position"]["bushing"] is None
    assert figures["bore_diameter_error_mm"] is None


def test_too_few_trials_make_no_profile(tmp_path: Path) -> None:
    trial(tmp_path, "a", [printed(0.1, 0.0)])

    with pytest.raises(ValueError, match="needs at least 2"):
        derive_guide_profile(
            tmp_path, printer_profile_id=PRINTER, material_profile_id="petg"
        )


def test_trials_that_measured_nothing_make_no_profile(tmp_path: Path) -> None:
    empty: dict[str, Any] = {"kind": "printed", "offset_mm": None}
    trial(tmp_path, "a", [empty])
    trial(tmp_path, "b", [empty])

    with pytest.raises(ValueError, match="measured no bore's position"):
        derive_guide_profile(
            tmp_path, printer_profile_id=PRINTER, material_profile_id="petg"
        )


def test_a_profile_moves_only_to_the_next_version(
    evidence: Path, tmp_path: Path
) -> None:
    first = derive_guide_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id="petg"
    )
    path = write_guide_profile(first, tmp_path / "profiles" / "p.json")
    second = derive_guide_profile(
        evidence,
        printer_profile_id=PRINTER,
        material_profile_id="petg",
        previous=first,
    )

    assert first["version"] == 1 and second["version"] == 2
    assert second["history"][0]["version"] == 1

    with pytest.raises(FileExistsError):
        write_guide_profile(first, path)

    write_guide_profile(second, path)

    assert load_guide_profile(path).payload["version"] == 2


def test_a_loaded_profile_gives_a_reference_with_its_hash(
    evidence: Path, tmp_path: Path
) -> None:
    profile = derive_guide_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id="petg"
    )
    path = write_guide_profile(profile, tmp_path / "p.json")
    loaded = load_guide_profile(path)

    assert loaded.reference()["profile_id"] == f"{PRINTER}-petg"
    assert len(loaded.reference()["sha256"]) == 64
    assert loaded.position("printed") is not None
    assert "2 passing trials" in loaded.describe()


def test_a_profile_with_no_position_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            {"schema_version": "1.0.0", "figures": {"position": {"printed": None}}}
        )
    )

    with pytest.raises(ValueError, match="no measured position"):
        load_guide_profile(path)
