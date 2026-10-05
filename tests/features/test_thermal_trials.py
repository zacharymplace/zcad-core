"""Thermal trials, the pooled thermal profile, the review's cooling section, and
the group enclosure's vents.

The temperatures and powers in these tests are made up to exercise the
arithmetic. Nothing in the repository holds a measurement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.cli import main
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.enclosure_group import GroupDesign, build_group_enclosure
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.enclosure_review import export_enclosure_review
from zcad_core.features.enclosure_thermal import estimate_thermal
from zcad_core.features.enclosure_trial import (
    MINIMUM_SETTLED_MINUTES,
    EnclosureTrialDisposition,
    complete_enclosure_trial,
    start_enclosure_trial,
    write_build_record,
)
from zcad_core.features.vent_patterns import add_wall_inlets
from zcad_core.hardware import get_raspberry_pi5, get_raspberry_pi_pico2
from zcad_core.profiles import (
    derive_thermal_profile,
    load_thermal_profile,
    write_thermal_profile,
)

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PICO = get_raspberry_pi_pico2()
PI5 = get_raspberry_pi5()
FAN_40 = "NOCTUA_NF_A4X10_5V"


def assembly(board):  # type: ignore[no-untyped-def]
    return build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )


def record_for(design: EnclosureDesign, directory: Path) -> Path:
    enclosure = build_enclosure(assembly(PICO), board=PICO, design=design)
    parts = {}

    for name in ("base", "lid"):
        parts[name] = directory / f"{name}.stl"
        parts[name].write_text(f"solid {name}\n", encoding="utf-8")

    return write_build_record(
        directory,
        enclosure=enclosure,
        design_name="pico-case",
        board_identifier=PICO.identifier,
        display=None,
        part_stls=parts,
        printer_profile_id="bambu-lab-a1-mini",
    )


def read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    assert isinstance(payload, dict)

    return payload


def pass_observations(trial: Path) -> None:
    observations = read(trial / "observations.json")

    for entry in observations.values():
        entry["result"] = "pass"

    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")


def fill_thermal(
    trial: Path,
    *,
    h: float,
    power: float = 2.0,
    ambient: float = 22.0,
    minutes: float = 20.0,
    deformed: bool = False,
    **overrides: Any,
) -> None:
    """Record the rise a box of coefficient ``h`` would show, from the
    surface the build record gives."""

    template = read(trial / "thermal.json")
    surface = template["estimate"]["surface_m2"]
    template.update(
        {
            "ambient_c": ambient,
            "internal_air_c": ambient + power / (h * surface),
            "power_w": power,
            "settled_minutes": minutes,
            "deformation_observed": deformed,
            "sensor": "synthetic, for a test",
            **overrides,
        }
    )
    (trial / "thermal.json").write_text(json.dumps(template), "utf-8")


def complete(trial: Path) -> dict[str, Any]:
    pass_observations(trial)

    return read(
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )
    )


# --- the build record and the trial template -------------------------------


def test_the_build_record_carries_what_a_trial_compares_with(tmp_path: Path) -> None:
    build = read(record_for(EnclosureDesign(), tmp_path))
    thermal = build["thermal"]

    assert thermal["coefficient_w_m2k"] == 8.0
    assert thermal["coefficient_source"].startswith("the default")
    assert thermal["closed"] is True and thermal["surface_m2"] > 0
    assert build["thermal_profile"] is None


def test_a_vented_or_slotted_box_is_not_closed(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()

    vented = read(
        record_for(
            EnclosureDesign(
                bottom_clearance_mm=6.0, vent_pattern="hex", vent_area_mm2=100.0
            ),
            tmp_path / "a",
        )
    )
    slotted = read(
        record_for(
            EnclosureDesign(bottom_clearance_mm=6.0, vent_slots=2), tmp_path / "b"
        )
    )

    assert vented["thermal"]["closed"] is False
    assert slotted["thermal"]["closed"] is False


def test_a_trial_template_has_a_thermal_file_with_the_estimate_and_blanks(
    tmp_path: Path,
) -> None:
    trial = start_enclosure_trial(record_for(EnclosureDesign(), tmp_path))
    template = read(trial / "thermal.json")

    assert "thermocouple" in template["guidance"]
    assert template["estimate"]["coefficient_w_m2k"] == 8.0
    assert template["estimate"]["closed"] is True
    for blank in ("ambient_c", "internal_air_c", "power_w", "deformation_observed"):
        assert template[blank] is None


# --- completing a trial ----------------------------------------------------


def test_a_recorded_temperature_is_compared_with_the_estimate(tmp_path: Path) -> None:
    trial = start_enclosure_trial(record_for(EnclosureDesign(), tmp_path))
    fill_thermal(trial, h=6.0)
    thermal = complete(trial)["thermal"]

    # A box that sheds heat at 6 W/m2K, against the estimate's 8: 8/6 hotter.
    assert thermal["h_effective_w_m2k"] == pytest.approx(6.0, abs=0.01)
    assert thermal["estimate_error_ratio"] == pytest.approx(8.0 / 6.0, abs=0.01)
    assert thermal["rise_c"] > 0
    assert thermal["closed"] is True
    assert thermal["conductance_w_k"] == pytest.approx(
        thermal["power_w"] / thermal["rise_c"], rel=0.01
    )
    assert thermal["deformation_observed"] is False
    assert thermal["configuration"]["vents"] is None


def test_a_fit_only_trial_leaves_the_temperature_blank(tmp_path: Path) -> None:
    trial = start_enclosure_trial(record_for(EnclosureDesign(), tmp_path))
    measurements = read(trial / "measurements.json")
    measurements["wall_thickness_mm"]["value_mm"] = 2.1
    (trial / "measurements.json").write_text(json.dumps(measurements), "utf-8")

    assert complete(trial)["thermal"] is None


def test_a_temperature_alone_is_enough_to_complete_a_trial(tmp_path: Path) -> None:
    trial = start_enclosure_trial(record_for(EnclosureDesign(), tmp_path))
    fill_thermal(trial, h=7.0)

    assert complete(trial)["passed"] is True


@pytest.mark.parametrize(
    ("overrides", "error", "message"),
    [
        ({"minutes": MINIMUM_SETTLED_MINUTES - 1}, ValueError, "held for at least"),
        ({"power": -1.0}, ValueError, "power_w must be greater than zero"),
        ({"internal_air_c": 20.0}, ValueError, "no warmer than the room"),
        ({"deformed": None}, TypeError, "deformation_observed must be true or false"),
        ({"ambient_c": "warm"}, TypeError, "ambient_c must be a number"),
    ],
)
def test_a_thermal_record_must_be_whole_and_settled(
    tmp_path: Path, overrides: dict[str, Any], error: type[Exception], message: str
) -> None:
    trial = start_enclosure_trial(record_for(EnclosureDesign(), tmp_path))
    fill_thermal(trial, h=6.0, **overrides)
    pass_observations(trial)

    with pytest.raises(error, match=message):
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


# --- the pooled profile ----------------------------------------------------


def closed_trial(directory: Path, h: float, *, deformed: bool = False) -> None:
    directory.mkdir()
    trial = start_enclosure_trial(record_for(EnclosureDesign(), directory))
    fill_thermal(trial, h=h, deformed=deformed)
    complete(trial)


def test_two_closed_trials_pool_into_a_measured_coefficient(tmp_path: Path) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    profile = derive_thermal_profile(tmp_path, material_profile_id="petg")

    figure = profile["figures"]["convection_w_m2k"]
    assert figure["mean"] == pytest.approx(6.5, abs=0.01)
    assert figure["spread"] == pytest.approx(0.5, abs=0.01)
    assert figure["samples"] == 2
    assert len(profile["sources"]) == 2
    assert all(len(source["sha256"]) == 64 for source in profile["sources"])
    assert profile["version"] == 1 and profile["history"] == []


def test_a_profile_needs_closed_trials_and_vented_ones_do_not_count(
    tmp_path: Path,
) -> None:
    closed_trial(tmp_path / "a", 6.0)
    vented = tmp_path / "v"
    vented.mkdir()
    trial = start_enclosure_trial(
        record_for(EnclosureDesign(bottom_clearance_mm=6.0, vent_slots=2), vented)
    )
    fill_thermal(trial, h=14.0)
    complete(trial)

    with pytest.raises(ValueError, match="1 closed-box thermal trial"):
        derive_thermal_profile(tmp_path, material_profile_id="petg")


def test_a_closed_trial_copied_to_another_folder_counts_once(tmp_path: Path) -> None:
    # One closed box, its completed record copied: one trial, not the two a
    # measured coefficient needs.
    closed_trial(tmp_path / "a", 6.0)
    (record,) = (tmp_path / "a").rglob("enclosure-trial.json")
    copy = tmp_path / "copy" / "trials" / "trial-001" / record.name
    copy.parent.mkdir(parents=True)
    copy.write_bytes(record.read_bytes())

    with pytest.raises(ValueError, match="1 closed-box thermal trial"):
        derive_thermal_profile(tmp_path, material_profile_id="petg")


def test_vented_trials_are_listed_beside_the_passive_figure_not_pooled(
    tmp_path: Path,
) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 6.0)
    vented = tmp_path / "v"
    vented.mkdir()
    trial = start_enclosure_trial(
        record_for(EnclosureDesign(bottom_clearance_mm=6.0, vent_slots=2), vented)
    )
    fill_thermal(trial, h=12.0)
    complete(trial)
    profile = derive_thermal_profile(tmp_path, material_profile_id="petg")

    # The coefficient is from the two closed boxes only.
    assert profile["figures"]["convection_w_m2k"]["mean"] == pytest.approx(
        6.0, abs=0.01
    )
    (entry,) = profile["ventilated"]
    assert entry["conductance_ratio"] == pytest.approx(2.0, abs=0.05)
    assert entry["configuration"]["vent_slots"] == 2


def test_the_profile_keeps_what_the_plastic_did(tmp_path: Path) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 4.0, deformed=True)
    profile = derive_thermal_profile(tmp_path, material_profile_id="petg")
    deformation = profile["deformation"]

    assert deformation["highest_air_c_without_deformation"] is not None
    assert deformation["lowest_air_c_with_deformation"] is not None
    # The box that deformed ran hotter, since it shed heat less well.
    assert (
        deformation["lowest_air_c_with_deformation"]
        > deformation["highest_air_c_without_deformation"]
    )


def test_a_profile_only_moves_to_the_next_version(tmp_path: Path) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    first = derive_thermal_profile(tmp_path, material_profile_id="petg")
    path = tmp_path / "profiles" / "petg.json"
    write_thermal_profile(first, path)

    with pytest.raises(FileExistsError, match="derive the next version"):
        write_thermal_profile(first, path)

    second = derive_thermal_profile(
        tmp_path, material_profile_id="petg", previous=read(path)
    )

    assert second["version"] == 2
    assert second["history"][0]["version"] == 1
    write_thermal_profile(second, path)
    assert read(path)["version"] == 2


def test_a_loaded_profile_describes_itself_and_is_checked(tmp_path: Path) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    path = write_thermal_profile(
        derive_thermal_profile(tmp_path, material_profile_id="petg"),
        tmp_path / "petg.json",
    )
    profile = load_thermal_profile(path)

    assert profile.coefficient_w_m2k == pytest.approx(6.5, abs=0.01)
    assert "2 closed-box trials" in profile.describe()
    assert (
        profile.reference()["version"] == 1 and len(profile.reference()["sha256"]) == 64
    )

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "9.9.9"}))
    with pytest.raises(ValueError, match="Unsupported thermal profile schema"):
        load_thermal_profile(bad)

    empty = tmp_path / "empty.json"
    empty.write_text(
        json.dumps({"schema_version": "1.0.0", "figures": {}, "version": 1})
    )
    with pytest.raises(ValueError, match="no positive convection_w_m2k"):
        load_thermal_profile(empty)


# --- using a profile -------------------------------------------------------


def test_a_measured_coefficient_replaces_the_default_and_says_where_from() -> None:
    default = estimate_thermal(["RASPBERRY_PI_5"], outer_size_mm=(100.0, 100.0, 50.0))
    measured = estimate_thermal(
        ["RASPBERRY_PI_5"],
        outer_size_mm=(100.0, 100.0, 50.0),
        coefficient_w_m2k=6.0,
        coefficient_source="profile petg v1: 3 closed-box trials",
    )

    assert measured.rise_typical_c == pytest.approx(default.rise_typical_c * 8.0 / 6.0)
    assert "off by half" in default.to_dict()["note"]
    assert "measured on printed boxes" in measured.to_dict()["note"]
    assert measured.to_dict()["coefficient_source"].startswith("profile petg")


def test_cli_builds_with_a_thermal_profile_and_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    path = write_thermal_profile(
        derive_thermal_profile(tmp_path, material_profile_id="petg"),
        tmp_path / "petg.json",
    )
    output = tmp_path / "out"
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--thermal-profile",
            str(path),
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["thermal"]["coefficient_w_m2k"] == pytest.approx(6.5, abs=0.01)
    assert payload["thermal"]["coefficient_source"].startswith("profile petg v1")
    record = read(output / "enclosure.json")
    assert record["thermal_profile"]["profile_id"] == "petg"
    assert record["design"]["convection_w_m2k"] == pytest.approx(6.5, abs=0.01)


def test_cli_thermal_derive_writes_the_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    out = tmp_path / "petg-thermal.json"
    exit_code = main(
        [
            "thermal",
            "derive",
            "--evidence-root",
            str(tmp_path),
            "--output",
            str(out),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0 and out.is_file()
    assert payload["version"] == 1 and payload["trials"] == 2
    assert payload["figures"]["convection_w_m2k"]["samples"] == 2


def test_the_design_checks_its_coefficient() -> None:
    with pytest.raises(ValueError, match="convection_w_m2k must be greater than zero"):
        EnclosureDesign(convection_w_m2k=0.0).validate()


# --- the review package ----------------------------------------------------


def test_the_review_shows_the_fan_in_the_model_and_the_air_path(
    tmp_path: Path,
) -> None:
    pi5_assembly = assembly(PI5)
    enclosure = build_enclosure(
        pi5_assembly,
        board=PI5,
        design=EnclosureDesign(
            fan=FAN_40, top_clearance_mm=12.0, vent_pattern="hex", vent_area_mm2=300.0
        ),
    )
    review = export_enclosure_review(
        enclosure, pi5_assembly, output_directory=tmp_path / "review"
    )
    cooling = review.report["cooling"]

    # The fan seats against the lid, which is expected contact, not a fault.
    assert review.passed
    assert cooling["fan"]["model"] == "Noctua NF-A4x10 5V"
    assert cooling["vents"]["pattern"] == "hex"
    # The Active Cooler's fan has no figure, so the estimate is a floor.
    assert cooling["thermal"]["status"] == "lower_bound"
    assert any("inlets low" in step for step in cooling["air_path"])
    assert any("Noctua NF-A4x10 5V" in step for step in cooling["air_path"])
    assert review.glb_path.stat().st_size > 0


def test_a_review_of_a_plain_box_has_an_empty_air_path(tmp_path: Path) -> None:
    enclosure = build_enclosure(assembly(PICO), board=PICO)
    review = export_enclosure_review(
        enclosure, assembly(PICO), output_directory=tmp_path / "review"
    )

    assert review.report["cooling"]["air_path"] == []
    assert review.report["cooling"]["fan"] is None


# --- the group enclosure's vents -------------------------------------------


def test_the_group_takes_its_vents_in_the_side_walls_and_the_lid() -> None:
    plain = build_group_enclosure()
    group = build_group_enclosure(
        design=GroupDesign(vent_pattern="hex", vent_area_mm2=300.0)
    )
    report = group.vents

    assert plain.vents is None and report is not None
    assert report.inlet_mm2 >= 300.0 and report.outlet_not_smaller
    assert group.passed
    assert len(group.base.solids().vals()) == 1 and len(group.lid.solids().vals()) == 1
    assert group.base.val().Volume() < plain.base.val().Volume()  # type: ignore[union-attr]
    assert group.lid.val().Volume() < plain.lid.val().Volume()  # type: ignore[union-attr]
    # The footprint is unchanged: nothing was added.
    assert group.outer_size_mm == plain.outer_size_mm


def test_the_groups_vents_stay_off_the_front_and_back_walls() -> None:
    plain = build_group_enclosure()
    group = build_group_enclosure(
        design=GroupDesign(vent_pattern="round", vent_area_mm2=250.0)
    )
    width, _, _ = group.outer_size_mm
    removed = plain.base.cut(group.base).solids().vals()

    assert removed
    # Every cell cut from the base is in a side wall, at one end of the row.
    for cell in removed:
        centre_x = cell.Center().x  # type: ignore[union-attr]
        assert centre_x < 3.0 or centre_x > width - 3.0


def test_the_groups_design_checks_its_vent_settings() -> None:
    with pytest.raises(ValueError, match="vent_pattern must be one of"):
        GroupDesign(vent_pattern="zigzag").validate()

    with pytest.raises(ValueError, match="needs a vent_area_mm2"):
        GroupDesign(vent_pattern="hex").validate()

    with pytest.raises(ValueError, match="vent_area_mm2 must not be negative"):
        GroupDesign(vent_area_mm2=-1.0).validate()


def test_inlets_can_be_asked_for_in_particular_walls() -> None:
    c = Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=100.0,
        depth_mm=60.0,
        floor_z_mm=2.0,
        top_z_mm=24.0,
        wall_mm=2.0,
    )
    base = (
        cq.Workplane("XY")
        .box(104.0, 64.0, 24.0, centered=(True, True, False))
        .cut(
            cq.Workplane("XY")
            .box(100.0, 60.0, 24.0, centered=(True, True, False))
            .translate((0, 0, 2.0))
        )
    )
    _, fills = add_wall_inlets(
        base,
        c,
        kind="hex",
        target_mm2=80.0,
        blocked_edges=[],
        top_z_mm=20.0,
        corner_keepout_mm=5.0,
        edges=("negative_x", "positive_x"),
    )

    assert len(fills) == 2

    with pytest.raises(ValueError, match="nowhere to vent"):
        add_wall_inlets(
            base,
            c,
            kind="hex",
            target_mm2=80.0,
            blocked_edges=["negative_x", "positive_x"],
            top_z_mm=20.0,
            corner_keepout_mm=5.0,
            edges=("negative_x", "positive_x"),
        )


def run_group(
    capsys: pytest.CaptureFixture[str], output: Path, *args: str
) -> dict[str, Any]:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            "pi5,pi5",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *args,
        ]
    )
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)

    return payload


def test_cli_group_reports_vents_and_is_not_a_closed_box(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = run_group(
        capsys, tmp_path, "--vent-pattern", "hex", "--vent-area-mm2", "300"
    )

    assert payload["validation_status"] == "PASS"
    assert payload["vents"]["pattern"] == "hex"
    # Its lid has slots over each Pi's fan and now a vent pattern: not closed.
    assert payload["thermal"]["closed"] is False


def test_cli_group_takes_a_thermal_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    closed_trial(tmp_path / "a", 6.0)
    closed_trial(tmp_path / "b", 7.0)
    path = write_thermal_profile(
        derive_thermal_profile(tmp_path, material_profile_id="petg"),
        tmp_path / "petg.json",
    )
    payload = run_group(capsys, tmp_path / "g", "--thermal-profile", str(path))

    assert payload["thermal"]["coefficient_w_m2k"] == pytest.approx(6.5, abs=0.01)
    assert payload["thermal"]["coefficient_source"].startswith("profile petg v1")
