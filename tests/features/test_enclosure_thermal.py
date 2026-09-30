from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.cli import main
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_SERVICE_LIMIT_C,
    WARN_FRACTION,
    estimate_thermal,
    require_not_too_hot,
    surface_m2,
)
from zcad_core.hardware import (
    get_arduino_uno_r4_wifi,
    get_raspberry_pi5,
    get_raspberry_pi_pico2,
)
from zcad_core.hardware.thermal import POWER_FIGURES, get_power_figure
from zcad_core.profiles import load_material_profile, material_service_limit_c

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PICO = get_raspberry_pi_pico2()
BOX = (100.0, 100.0, 50.0)


def test_the_pico_2_figures_are_the_datasheets() -> None:
    figure = get_power_figure("RASPBERRY_PI_PICO_2")
    assert figure is not None

    # Hello_serial 62.1 mW, and the highest entry in the table, 71.3 mW.
    assert figure.typical_w == pytest.approx(0.0621)
    assert figure.peak_w == pytest.approx(0.0713)
    assert figure.source.kind == "vendor"
    assert "Table 2" in figure.source.detail
    assert figure.source.url.startswith("https://datasheets.raspberrypi.com/")


def test_the_pi_5_figure_is_marked_as_a_community_measurement_with_no_peak() -> None:
    figure = get_power_figure("RASPBERRY_PI_5")
    assert figure is not None

    assert figure.typical_w == 3.0
    assert figure.peak_w is None
    assert figure.source.kind == "community"
    assert "hqcamuser" in figure.source.detail
    assert "forums.raspberrypi.com" in figure.source.url


def test_every_figure_is_for_a_catalogued_part_and_carries_its_source() -> None:
    for identifier, figure in POWER_FIGURES.items():
        assert figure.identifier == identifier
        assert figure.source.title and figure.source.url.startswith("https://")
        assert figure.source.detail

    # Nothing is invented for the other boards or the displays.
    for identifier in ("ADAFRUIT_FEATHER_RP2040", "REFERENCE_OLED_128X64"):
        assert get_power_figure(identifier) is None


def test_surface_and_rise_follow_the_lumped_balance() -> None:
    surface = surface_m2(BOX)
    assert surface == pytest.approx(2 * (100 * 100 + 100 * 50 + 100 * 50) / 1e6)

    estimate = estimate_thermal(
        ["RASPBERRY_PI_PICO_2"] * 1, outer_size_mm=BOX, declared_power_w=4.0
    )

    assert estimate.coefficient_w_m2k == CONVECTION_W_M2K == 8.0
    assert estimate.declared_w == 4.0
    assert estimate.peak_w == pytest.approx(4.0713)
    assert estimate.rise_peak_c == pytest.approx(4.0713 / (8.0 * surface))
    assert estimate.temperature_peak_c == pytest.approx(25.0 + estimate.rise_peak_c)


def test_the_pi_5_pair_estimate_is_the_documented_worked_example() -> None:
    # The pair is 176 x 96 mm and 28.4 mm tall with its lid.
    estimate = estimate_thermal(
        ["RASPBERRY_PI_5", "RASPBERRY_PI_5"], outer_size_mm=(176.0, 96.0, 28.4)
    )

    assert estimate.surface_m2 == pytest.approx(0.0492, abs=1e-4)
    assert estimate.typical_w == 6.0
    assert estimate.rise_typical_c == pytest.approx(15.2, abs=0.1)
    assert estimate.temperature_typical_c == pytest.approx(40.2, abs=0.1)
    assert estimate.status == "ok"


def test_a_part_with_no_figure_is_unknown_not_zero() -> None:
    feather = estimate_thermal(["ADAFRUIT_FEATHER_RP2040"], outer_size_mm=BOX)

    assert feather.status == "unavailable"
    assert feather.missing == ("ADAFRUIT_FEATHER_RP2040",)
    assert not feather.complete

    mixed = estimate_thermal(
        ["RASPBERRY_PI_PICO_2", "REFERENCE_OLED_128X64"], outer_size_mm=BOX
    )

    # A lower bound from the part that has a figure, and the gap named.
    assert mixed.typical_w == pytest.approx(0.0621)
    assert mixed.missing == ("REFERENCE_OLED_128X64",)
    assert "at least" in mixed.message()
    assert "no power figure for REFERENCE_OLED_128X64" in mixed.message()


def test_a_part_with_no_peak_lends_its_typical_figure_and_says_so() -> None:
    estimate = estimate_thermal(["RASPBERRY_PI_5"], outer_size_mm=BOX)

    assert estimate.peak_w == estimate.typical_w == 3.0
    assert estimate.missing_peak == ("RASPBERRY_PI_5",)
    assert not estimate.complete
    assert "at least" in estimate.message()
    assert "no peak figure for RASPBERRY_PI_5" in estimate.message()
    assert estimate.to_dict()["peak_uses_typical_for"] == ["RASPBERRY_PI_5"]


def test_a_complete_estimate_does_not_say_at_least() -> None:
    estimate = estimate_thermal(["RASPBERRY_PI_PICO_2"], outer_size_mm=BOX)

    assert estimate.complete
    assert "at least" not in estimate.message()


def test_status_warns_above_85_percent_of_the_limit_and_fails_above_it() -> None:
    surface = surface_m2(BOX)
    limit = DEFAULT_SERVICE_LIMIT_C

    def at(temperature: float):  # type: ignore[no-untyped-def]
        watts = (temperature - 25.0) * 8.0 * surface

        return estimate_thermal([], outer_size_mm=BOX, declared_power_w=watts)

    assert at(WARN_FRACTION * limit - 1).status == "ok"
    assert at(WARN_FRACTION * limit + 1).status == "warn"
    assert at(limit - 1).status == "warn"
    assert at(limit + 1).status == "fail"


def test_too_hot_is_refused_unless_allowed() -> None:
    hot = estimate_thermal([], outer_size_mm=BOX, declared_power_w=40.0)

    assert hot.status == "fail"
    with pytest.raises(ValueError, match="off by half either way"):
        require_not_too_hot(hot, allow_hot=False)

    require_not_too_hot(hot, allow_hot=True)
    require_not_too_hot(
        estimate_thermal([], outer_size_mm=BOX, declared_power_w=1.0),
        allow_hot=False,
    )


def test_inputs_are_checked() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        estimate_thermal([], outer_size_mm=BOX, declared_power_w=-1.0)

    with pytest.raises(ValueError, match="above the ambient"):
        estimate_thermal([], outer_size_mm=BOX, ambient_c=70.0, limit_c=60.0)

    with pytest.raises(ValueError, match="service_limit_c must be above"):
        EnclosureDesign(ambient_c=70.0).validate()

    with pytest.raises(ValueError, match="must not be negative"):
        EnclosureDesign(declared_power_w=-1.0).validate()


def pico_enclosure(**overrides):  # type: ignore[no-untyped-def]
    assembly = build_board_assembly(
        board=PICO,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )

    return build_enclosure(
        assembly, board=PICO, design=replace(EnclosureDesign(), **overrides)
    )


def test_the_builder_attaches_an_estimate_from_the_boxs_real_size() -> None:
    enclosure = pico_enclosure()
    thermal = enclosure.thermal

    assert thermal is not None and thermal.complete
    assert thermal.status == "ok"
    assert thermal.typical_w == pytest.approx(0.0621)
    # About the size of the box, not a default.
    assert 0.005 < thermal.surface_m2 < 0.03


def test_a_declared_load_that_overheats_a_box_stops_the_build() -> None:
    with pytest.raises(ValueError, match="estimated air temperature"):
        pico_enclosure(declared_power_w=30.0)

    hot = pico_enclosure(declared_power_w=30.0, allow_hot=True)
    assert hot.thermal is not None and hot.thermal.status == "fail"


def test_a_board_with_no_figure_builds_with_the_gap_named() -> None:
    uno = get_arduino_uno_r4_wifi()
    assembly = build_board_assembly(
        board=uno, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    enclosure = build_enclosure(assembly, board=uno)

    assert enclosure.thermal is not None
    assert enclosure.thermal.status == "unavailable"
    assert enclosure.thermal.missing == ("ARDUINO_UNO_R4_WIFI",)


def test_a_pi_5_with_its_cooler_counts_the_cooler_as_a_missing_figure() -> None:
    pi5 = get_raspberry_pi5().with_active_cooler()
    assembly = build_board_assembly(
        board=pi5, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    enclosure = build_enclosure(assembly, board=pi5)

    assert enclosure.thermal is not None
    assert "RASPBERRY_PI_5:active-cooler-fan" in enclosure.thermal.missing


def test_the_petg_profile_sets_the_limit_and_the_loader_checks_it(
    tmp_path: Path,
) -> None:
    profile = load_material_profile(Path("profiles/materials/petg.json"))

    assert profile["max_service_c"] == 60
    assert "provisional" in profile["max_service_c_note"].lower()
    assert material_service_limit_c("petg") == 60.0
    assert material_service_limit_c("no-such-material") is None

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {"profile_id": "x", "name": "X", "density_g_cm3": 1.0, "max_service_c": 0}
        )
    )
    with pytest.raises(ValueError, match="max_service_c must be greater than zero"):
        load_material_profile(bad)


def run(
    capsys: pytest.CaptureFixture[str], command: str, output: Path, *args: str
) -> tuple[int, dict[str, object], str]:
    exit_code = main(
        [
            command,
            "build",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *args,
        ]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_cli_reports_the_estimate_and_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output, _ = run(
        capsys, "enclosure", tmp_path, "--board", "raspberry_pi_pico_2"
    )

    assert exit_code == 0
    thermal = output["thermal"]
    assert isinstance(thermal, dict)
    assert thermal["status"] == "ok" and thermal["complete"] is True
    assert thermal["limit_c"] == 60.0
    assert "not a simulation" in thermal["note"]
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["thermal"]["typical_w"] == thermal["typical_w"]
    assert record["design"]["service_limit_c"] == 60.0


def test_cli_takes_power_ambient_and_allow_hot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hot_args = ("--board", "raspberry_pi_pico_2", "--power-w", "30")
    exit_code, _, err = run(capsys, "enclosure", tmp_path / "a", *hot_args)

    assert exit_code == 1
    assert "estimated air temperature" in err and "--allow-hot" in err

    exit_code, output, _ = run(
        capsys, "enclosure", tmp_path / "b", *hot_args, "--allow-hot"
    )
    thermal = output["thermal"]
    assert isinstance(thermal, dict)
    assert exit_code == 0 and thermal["status"] == "fail"

    exit_code, output, _ = run(
        capsys,
        "enclosure",
        tmp_path / "c",
        "--board",
        "raspberry_pi_pico_2",
        "--ambient-c",
        "40",
    )
    thermal = output["thermal"]
    assert isinstance(thermal, dict) and thermal["ambient_c"] == 40.0


def test_cli_group_counts_each_fitted_pi_and_not_reserved_bays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, pair, _ = run(capsys, "enclosure-group", tmp_path / "a", "--bays", "pi5,pi5")
    _, mixed, _ = run(
        capsys, "enclosure-group", tmp_path / "b", "--bays", "pi5,reserved"
    )
    pair_thermal, mixed_thermal = pair["thermal"], mixed["thermal"]

    assert isinstance(pair_thermal, dict) and isinstance(mixed_thermal, dict)
    assert pair_thermal["typical_w"] == 6.0
    assert mixed_thermal["typical_w"] == 3.0
    assert pair_thermal["complete"] is False
    assert pair_thermal["peak_uses_typical_for"] == ["RASPBERRY_PI_5"]
