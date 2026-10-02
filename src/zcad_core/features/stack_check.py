"""``stack check-stack``: whether one item stacks on another.

Two items stack when they share a profile (by its hash), are the right kinds and sizes,
**agree on what holds them**, and, laid together as real solids, do not overlap:

- a **bin** goes on a **baseplate** whose cells cover its own, or on a **bin** with the same
  cells;
- a baseplate goes on nothing; and
- a bin on a baseplate agrees with it on what holds them: the same magnet, the same
  fastener, or both the lip alone. A bin on a bin is held by the lip alone, and a holding in
  either one's foot meets nothing there.

The engine states no load rating, no stable height and no holding force.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.stack import (
    NOT_CLAIMED,
    TOLERANCE_MM3,
    build_item,
    overlap_mm3,
)
from zcad_core.features.stack_file import (
    Item,
    StackSpec,
    check_stack_file,
    load_stack,
    load_stack_profile,
)
from zcad_core.features.stack_holding import Holding, holding_for


@dataclass(frozen=True)
class StackReport:
    """Whether two items stack, and every reason they do not."""

    stacks: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, Any]


def locate(text: str) -> tuple[Path, str]:
    """A ``FILE:NAME`` argument: the stack file and the item in it."""

    path, _, name = text.rpartition(":")

    if not path or not name:
        raise ValueError(f"{text!r} must be FILE:NAME, a stack file and an item in it")

    return Path(path), name


def _item(spec: StackSpec, name: str) -> Item:
    for item in spec.items:
        if item.name == name:
            return item

    raise ValueError(
        f"{spec.file_path} has no item {name!r}: it has "
        f"{[item.name for item in spec.items]}"
    )


def _describe(item: Item, holding: Holding) -> str:
    held = (
        f"{holding.kind} ({holding.identifier})" if holding.holds else "the lip alone"
    )

    return f"{item.name} ({item.kind}, held by {held})"


def _holding_errors(
    upper: Item, lower: Item, upper_hold: Holding, lower_hold: Holding
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if lower.kind == "bin":
        for item, hold in ((upper, upper_hold), (lower, lower_hold)):
            if hold.holds:
                warnings.append(
                    f"{item.name} holds by {hold.kind} in its foot, which meets nothing "
                    "when a bin stacks on a bin: they are held by the lip alone"
                )

        return errors, warnings

    if (upper_hold.kind, upper_hold.identifier) != (
        lower_hold.kind,
        lower_hold.identifier,
    ):
        errors.append(
            f"They disagree on what holds them: {_describe(upper, upper_hold)} on "
            f"{_describe(lower, lower_hold)}"
        )

    return errors, warnings


def _shape_errors(upper: Item, lower: Item) -> list[str]:
    if upper.kind == "baseplate":
        return [f"{upper.name} is a baseplate: it goes under bins and on nothing"]

    up, down = (
        f"{upper.cells[0]} x {upper.cells[1]}",
        f"{lower.cells[0]} x {lower.cells[1]}",
    )

    if lower.kind == "bin":
        if upper.cells == lower.cells:
            return []

        message = (
            f"{upper.name} is {up} cells and {lower.name} is {down}: a bin stacks on a "
            "bin of the same cells, since the foot sits in the lip all round"
        )

        return [message]

    if upper.cells[0] > lower.cells[0] or upper.cells[1] > lower.cells[1]:
        return [f"{upper.name} is {up} cells, more than the {down} of {lower.name}"]

    return []


def check_stackable(
    upper_file: Path,
    upper_name: str,
    lower_file: Path,
    lower_name: str,
    printer: Mapping[str, Any],
) -> StackReport:
    """Whether the upper item stacks on the lower, from the two stack files."""

    errors: list[str] = []

    for path in dict.fromkeys((upper_file, lower_file)):
        report = check_stack_file(path, printer)
        errors += [f"{path.name}: {e}" for e in report.errors]

    if errors:
        return StackReport(False, tuple(errors), (), {})

    upper_spec, lower_spec = load_stack(upper_file), load_stack(lower_file)
    upper, lower = _item(upper_spec, upper_name), _item(lower_spec, lower_name)
    upper_profile = load_stack_profile(upper_spec)
    lower_profile = load_stack_profile(lower_spec)
    upper_hold = holding_for(upper.holding, upper.magnet, upper.fastener)
    lower_hold = holding_for(lower.holding, lower.magnet, lower.fastener)

    if upper_profile.sha256 != lower_profile.sha256:
        errors.append(
            f"They are built to different profiles: {upper_profile.identifier} "
            f"({upper_profile.sha256[:12]}) and {lower_profile.identifier} "
            f"({lower_profile.sha256[:12]})"
        )

    errors += _shape_errors(upper, lower)
    held_errors, warnings = _holding_errors(upper, lower, upper_hold, lower_hold)
    errors += held_errors
    summary: dict[str, Any] = {
        "upper": _describe(upper, upper_hold),
        "lower": _describe(lower, lower_hold),
        "held_by": "the lip alone" if lower.kind == "bin" else _held_by(upper_hold),
        "not_claimed": NOT_CLAIMED,
    }

    if not errors:
        errors += _overlap_errors(upper, lower, upper_profile, summary)

    return StackReport(not errors, tuple(errors), tuple(warnings), summary)


def _held_by(holding: Holding) -> str:
    return (
        f"{holding.kind} ({holding.identifier})" if holding.holds else "the lip alone"
    )


def _overlap_errors(
    upper: Item, lower: Item, profile: Any, summary: dict[str, Any]
) -> list[str]:
    """Lay the upper solid on the lower and measure any overlap."""

    upper_model, _, upper_summary = build_item(upper, profile)
    lower_model, lower_height, _ = build_item(lower, profile)
    pitch = profile.pitch_mm
    # The upper's first cell sits over the lower's first cell, corner to corner.
    dx = (upper.cells[0] - lower.cells[0]) * pitch / 2
    dy = (upper.cells[1] - lower.cells[1]) * pitch / 2
    seated = upper_model.translate((dx, dy, lower_height))
    overlap = overlap_mm3(seated, lower_model)
    summary["stack_height_mm"] = round(
        lower_height + float(upper_summary.get("overall_height_mm", 0.0)), 3
    )

    if overlap > TOLERANCE_MM3:
        return [f"The solids overlap by {overlap:.2f} mm3 when laid together"]

    return []
