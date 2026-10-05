"""The thermal estimate of a group enclosure, and the start and completion of its print trial."""

from __future__ import annotations

import argparse
import json

from zcad_core.cli._common import emit
from zcad_core.features.enclosure_group import Bay, GroupEnclosure
from zcad_core.features.enclosure_group_trial import (
    complete_group_trial,
    start_group_trial,
)
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_SERVICE_LIMIT_C,
    ThermalEstimate,
    estimate_thermal,
    require_not_too_hot,
)
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.hardware.thermal import PowerFigure
from zcad_core.profiles import load_thermal_profile, material_service_limit_c


def _heat_sources(
    bays: tuple[Bay, ...],
) -> tuple[list[str], dict[str, PowerFigure]]:
    """The parts that give off heat, by catalog identifier, and the figures a
    board file brings of its own. A fitted Pi counts; a reserved bay is empty
    until a Pi goes in it. A board with no power section is counted as unknown, and
    the estimate says so."""

    parts: list[str] = []
    figures: dict[str, PowerFigure] = {}

    for bay in bays:
        if bay.kind == "pi5":
            # Every Pi bay is built around the Active Cooler, whose fan the
            # catalog has no figure for, as the single enclosure names it.
            parts.extend(("RASPBERRY_PI_5", "RASPBERRY_PI_5:active-cooler-fan"))
        elif bay.kind == "board" and bay.board is not None:
            parts.append(bay.board.identifier)

            if bay.board.power_figure is not None:
                figures[bay.board.identifier] = bay.board.power_figure
        elif bay.kind == "fan" and bay.fan is not None:
            parts.append(bay.fan)

    return parts, figures


def _moves_air(group: GroupEnclosure, bays: tuple[Bay, ...]) -> bool:
    """Whether anything lets air through: slots over a Pi's fan or a board's part,
    a vent pattern, or a fan."""

    slots = group.design.vents and any(
        bay.kind == "pi5"
        or (
            bay.kind == "board"
            and bay.board is not None
            and any(part.lid_vent for part in bay.board.components)
        )
        for bay in bays
    )

    return bool(
        slots or group.design.vent_area_mm2 or any(bay.kind == "fan" for bay in bays)
    )


def _group_thermal(
    group: GroupEnclosure, bays: tuple[Bay, ...], args: argparse.Namespace
) -> ThermalEstimate:
    """The temperature estimate for the row, counting each fitted Pi, each board
    that gives a power figure, and each fan; a reserved bay is empty until a Pi
    goes in it."""

    width, depth, _ = group.outer_size_mm
    height = group.cavity_top_z_mm + group.design.lid_mm
    parts, figures = _heat_sources(bays)
    coefficient, source = CONVECTION_W_M2K, "the default, an assumption"

    if args.thermal_profile is not None:
        profile = load_thermal_profile(args.thermal_profile)
        coefficient, source = profile.coefficient_w_m2k, profile.describe()

    estimate = estimate_thermal(
        parts,
        outer_size_mm=(width, depth, height),
        declared_power_w=args.power_w,
        ambient_c=args.ambient_c,
        coefficient_w_m2k=coefficient,
        coefficient_source=source,
        figures=figures,
        closed=not _moves_air(group, bays),
        limit_c=material_service_limit_c(args.material_profile)
        or DEFAULT_SERVICE_LIMIT_C,
    )
    require_not_too_hot(estimate, allow_hot=args.allow_hot)

    return estimate


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_group_trial(args.build_record)
    payload: dict[str, object] = {
        "trial": str(trial),
        "observations": str(trial / "observations.json"),
        "measurements": str(trial / "measurements.json"),
        "thermal": str(trial / "thermal.json"),
    }

    if (trial / "lid.json").is_file():
        payload["lid"] = str(trial / "lid.json")

    if (trial / "stack_top.json").is_file():
        payload["stack_top"] = str(trial / "stack_top.json")

    emit(payload)

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_group_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
        }
    )

    return 0
