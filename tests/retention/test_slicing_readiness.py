from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.profiles.loading import (
    load_material_profile,
    load_printer_profile,
    load_slicer_profile,
)
from zcad_core.retention import (
    evaluate_slicing_readiness,
    write_slicing_readiness_report,
)


def fixture_model() -> cq.Workplane:
    return cq.Workplane("XY").box(
        54.8,
        26.86,
        5.67,
    )


def profiles():
    return (
        load_printer_profile(Path("profiles/printers/bambu-lab-a1-mini.json")),
        load_material_profile(Path("profiles/materials/petg.json")),
        load_slicer_profile(
            Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json")
        ),
    )


def test_fixture_is_ready_for_a1_mini(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "fixture.stl"
    fixture_path.write_text(
        "fixture",
        encoding="utf-8",
    )
    printer, material, slicer = profiles()

    report = evaluate_slicing_readiness(
        candidate_id="candidate-r003",
        fixture_model=fixture_model(),
        fixture_artifact_path=fixture_path,
        printer_profile=printer,
        material_profile=material,
        slicer_profile=slicer,
    )

    assert report.ready_for_slicing is True
    assert report.slice_completed is False
    assert report.physical_validation_satisfied is False
    assert report.build_margin_mm == {
        "x": 125.2,
        "y": 153.14,
        "z": 174.33,
    }


def test_oversized_fixture_is_not_ready(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "fixture.stl"
    fixture_path.write_text(
        "fixture",
        encoding="utf-8",
    )
    printer, material, slicer = profiles()

    report = evaluate_slicing_readiness(
        candidate_id="candidate-r003",
        fixture_model=(
            cq.Workplane("XY").box(
                181.0,
                20.0,
                10.0,
            )
        ),
        fixture_artifact_path=fixture_path,
        printer_profile=printer,
        material_profile=material,
        slicer_profile=slicer,
    )

    assert report.ready_for_slicing is False
    assert any(
        not result.passed
        for result in report.results
        if result.check.value == "build_volume_fit"
    )


def test_writes_immutable_readiness_report(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "fixture.stl"
    fixture_path.write_text(
        "fixture",
        encoding="utf-8",
    )
    printer, material, slicer = profiles()
    report = evaluate_slicing_readiness(
        candidate_id="candidate-r003",
        fixture_model=fixture_model(),
        fixture_artifact_path=fixture_path,
        printer_profile=printer,
        material_profile=material,
        slicer_profile=slicer,
    )
    output_path = tmp_path / "readiness.json"

    write_slicing_readiness_report(
        report,
        output_path=output_path,
    )
    write_slicing_readiness_report(
        report,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["ready_for_slicing"] is True
    assert payload["slice_completed"] is False
    assert payload["physical_validation_satisfied"] is False

    output_path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        write_slicing_readiness_report(
            report,
            output_path=output_path,
        )
