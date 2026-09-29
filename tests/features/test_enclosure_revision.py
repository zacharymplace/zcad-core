"""Revising an enclosure design from a completed trial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.enclosure_revision import propose_revision, revised_name
from zcad_core.hardware import get_board

DESIGN = {
    "hole_compensation_mm": 0.0,
    "cable_plug_width_mm": 12.5,
    "cable_plug_height_mm": 7.5,
}


def recorded_trial(
    tmp_path: Path,
    *,
    measurements: dict[str, tuple[float, float]] | None = None,
    failed: tuple[str, ...] = (),
    design: dict[str, Any] | None = None,
) -> Path:
    """A build record and a completed trial of it, written by hand."""

    build = tmp_path / "enclosure.json"
    build.write_text(
        json.dumps({"design_name": "case", "design": design or DESIGN}), "utf-8"
    )
    trial = tmp_path / "trials" / "trial-001"
    trial.mkdir(parents=True)
    record = {
        "trial_id": "trial-001",
        "disposition": "revise" if failed or measurements else "pass",
        "build_record_sha256": hashlib.sha256(build.read_bytes()).hexdigest(),
        "failed_checks": list(failed),
        "measurements": [
            {"name": name, "nominal_mm": nominal, "value_mm": value}
            for name, (nominal, value) in (measurements or {}).items()
        ],
    }
    (trial / "enclosure-trial.json").write_text(json.dumps(record), "utf-8")

    return trial


def test_undersized_holes_raise_the_compensation(tmp_path: Path) -> None:
    trial = recorded_trial(
        tmp_path,
        measurements={
            "insert_pocket_diameter_mm": (4.6, 4.3),
            "lid_hole_diameter_mm": (3.4, 3.2),
        },
    )

    revision = propose_revision(trial)

    (change,) = revision.changes
    assert (change.setting, change.current, change.proposed) == (
        "hole_compensation_mm",
        0.0,
        0.25,
    )
    assert "short by 0.30 mm" in change.reason
    assert revision.design["hole_compensation_mm"] == 0.25


def test_compensation_builds_on_the_last_one_and_stays_in_range(
    tmp_path: Path,
) -> None:
    trial = recorded_trial(
        tmp_path,
        measurements={"lid_hole_diameter_mm": (3.4, 2.6)},
        design={**DESIGN, "hole_compensation_mm": 0.4},
    )

    (change,) = propose_revision(trial).changes

    assert change.proposed == 1.0


def test_noise_changes_nothing(tmp_path: Path) -> None:
    trial = recorded_trial(tmp_path, measurements={"lid_hole_diameter_mm": (3.4, 3.37)})

    revision = propose_revision(trial)

    assert revision.changes == ()
    assert revision.notes == ("The trial found nothing to change.",)


def test_a_cable_that_will_not_plug_in_widens_the_plug_allowance(
    tmp_path: Path,
) -> None:
    revision = propose_revision(recorded_trial(tmp_path, failed=("cable_plugs_in",)))

    assert {(c.setting, c.proposed) for c in revision.changes} == {
        ("cable_plug_width_mm", 13.5),
        ("cable_plug_height_mm", 8.5),
    }


def test_checks_no_setting_fixes_become_notes(tmp_path: Path) -> None:
    revision = propose_revision(
        recorded_trial(tmp_path, failed=("board_retained", "lid_closes_flush"))
    )

    assert revision.changes == ()
    assert [note.split(":")[0] for note in revision.notes] == [
        "board_retained",
        "lid_closes_flush",
    ]


def test_a_wrongly_scaled_base_is_a_calibration_note(tmp_path: Path) -> None:
    revision = propose_revision(
        recorded_trial(tmp_path, measurements={"base_outer_width_mm": (40.0, 39.5)})
    )

    assert revision.changes == ()
    (note,) = revision.notes
    assert note.startswith("base_outer_width printed 1.2% small")


def test_refuses_an_incomplete_trial_or_a_changed_build(tmp_path: Path) -> None:
    trial = recorded_trial(tmp_path)

    (tmp_path / "enclosure.json").write_text('{"changed": true}', "utf-8")
    with pytest.raises(ValueError, match="build record changed after the trial"):
        propose_revision(trial)

    (trial / "enclosure-trial.json").unlink()
    with pytest.raises(FileNotFoundError, match="run enclosure trial complete"):
        propose_revision(trial)


@pytest.mark.parametrize(
    ("name", "revised"),
    [
        ("case", "case-r2"),
        ("case-r2", "case-r3"),
        ("case-r9", "case-r10"),
        ("r2", "r2-r2"),
    ],
)
def test_revised_names_count_up(name: str, revised: str) -> None:
    assert revised_name(name) == revised


def test_compensation_widens_the_lid_holes_and_insert_pockets() -> None:
    board = get_board("RASPBERRY_PI_PICO_2")
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )

    def built(
        compensation: float,
    ) -> tuple[cq.Solid, cq.Solid, tuple[float, float], float]:
        enclosure = build_enclosure(
            assembly,
            board=board,
            design=EnclosureDesign(hole_compensation_mm=compensation),
        )
        (base,) = enclosure.base.solids().vals()
        (lid,) = enclosure.lid.solids().vals()
        assert isinstance(base, cq.Solid) and isinstance(lid, cq.Solid)
        spec = enclosure.specification

        return (
            base,
            lid,
            enclosure.fastener_positions[0],
            spec.bottom_z_mm + spec.inner_height_mm,
        )

    plain_base, plain_lid, (x, y), top = built(0.0)
    wide_base, wide_lid, _, _ = built(0.4)
    # Just outside the plain hole and pocket, inside the compensated ones.
    lid_probe = cq.Vector(x + 3.4 / 2 + 0.1, y, top + 1.0)
    pocket_probe = cq.Vector(x + 4.6 / 2 + 0.1, y, top - 1.0)

    assert plain_lid.isInside(lid_probe) and not wide_lid.isInside(lid_probe)
    assert plain_base.isInside(pocket_probe) and not wide_base.isInside(pocket_probe)


def test_design_limits_the_compensation() -> None:
    with pytest.raises(ValueError, match="hole_compensation_mm must be from -0.2"):
        EnclosureDesign(hole_compensation_mm=1.5).validate()
