"""``stack check-stack``: whether one item stacks on another.

Two items stack when they share a profile (by its hash), are the right kinds and sizes,
**agree on what holds them**, and, laid together as real solids, do not overlap:

- a **bin** or a **frame** goes on a **baseplate** whose cells cover its own, or on a bin or
  frame with the same cells; a **cap** goes on a bin or a frame with the same cells;
- a baseplate goes on nothing, nothing goes on a cap, and a drawer slides into a frame; and
- a bin on a baseplate agrees with it on what holds them: the same magnet, the same
  fastener, or both the lip alone. A bin on a bin is held by the lip alone, and a holding in
  either one's foot meets nothing there.

The engine states no load rating, no stable height and no holding force.
"""

from __future__ import annotations

import json
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
from zcad_core.features.stack_profile import StackProfile, load_profile


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

    if lower.kind != "baseplate":
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


# What has a lip, so takes the foot of the item above.
LIPPED = ("bin", "frame")


def _shape_errors(upper: Item, lower: Item) -> list[str]:
    if upper.kind == "baseplate":
        return [f"{upper.name} is a baseplate: it goes under bins and on nothing"]

    if upper.kind == "drawer":
        return [f"{upper.name} is a drawer: it slides into a frame and does not stack"]

    if lower.kind in ("cap", "drawer", "plate"):
        return [f"nothing stacks on {lower.name}, a {lower.kind}: its top is not a lip"]

    up = f"{upper.cells[0]} x {upper.cells[1]}"
    down = f"{lower.cells[0]} x {lower.cells[1]}"

    if lower.kind in LIPPED:
        if upper.cells == lower.cells:
            return []

        message = (
            f"{upper.name} is {up} cells and {lower.name} is {down}: it stacks on one "
            "of the same cells, since the foot sits in the lip all round"
        )

        return [message]

    if upper.kind == "cap":
        return [f"{upper.name} is a cap: it goes on a bin or a frame, not a baseplate"]

    if upper.cells[0] > lower.cells[0] or upper.cells[1] > lower.cells[1]:
        return [f"{upper.name} is {up} cells, more than the {down} of {lower.name}"]

    return []


@dataclass(frozen=True)
class Resolved:
    """An item and the profile it is built to, from a stack file or a build record."""

    item: Item
    profile: StackProfile


def _from_file(
    path: Path, name: str, printer: Mapping[str, Any]
) -> tuple[Resolved | None, list[str]]:
    report = check_stack_file(path, printer)

    if not report.valid:
        return None, [f"{path.name}: {e}" for e in report.errors]

    spec = load_stack(path)

    return Resolved(_item(spec, name), load_stack_profile(spec)), []


def _from_record(path: Path) -> tuple[Resolved | None, list[str]]:
    """A stack plate from an enclosure's or a group's build record."""

    record = json.loads(path.read_text(encoding="utf-8"))
    stack = record.get("stack") if isinstance(record, dict) else None

    if not isinstance(stack, dict):
        message = (
            f"{path.name} has no stack plate: build it with --mount stack and a "
            "--stack-profile"
        )

        return None, [message]

    entry = stack["profile"]
    profile_path = Path(entry["path"])

    if not profile_path.is_file():
        return None, [f"{path.name}: the profile {profile_path} is missing"]

    profile = load_profile(profile_path)

    if profile.sha256 != entry["sha256"]:
        message = (
            f"{path.name}: the profile {profile_path} has changed since the build: its "
            f"hash is {profile.sha256[:12]}, not {entry['sha256'][:12]}"
        )

        return None, [message]

    cells = (int(stack["cells"][0]), int(stack["cells"][1]))
    item = Item(
        kind="plate",
        name=str(record.get("design_name", path.stem)),
        cells=cells,
        floor_mm=float(stack["plate_mm"]),
    )

    return Resolved(item, profile), []


def resolve(text: str, printer: Mapping[str, Any]) -> tuple[Resolved | None, list[str]]:
    """One argument of ``check-stack``: ``FILE:NAME`` for an item in a stack file, or the
    path of an enclosure's or a group's build record, for its stack plate."""

    path = Path(text)

    if path.suffix == ".json" and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, dict) and "design_name" in data:
            return _from_record(path)

    file, name = locate(text)

    return _from_file(file, name, printer)


def check_stackable(
    upper_file: Path,
    upper_name: str,
    lower_file: Path,
    lower_name: str,
    printer: Mapping[str, Any],
) -> StackReport:
    """Whether the upper item stacks on the lower, from the two stack files."""

    return check_items(
        f"{upper_file}:{upper_name}", f"{lower_file}:{lower_name}", printer
    )


def check_items(
    upper_text: str, lower_text: str, printer: Mapping[str, Any]
) -> StackReport:
    """Whether the upper stacks on the lower: each a ``FILE:NAME`` or a build record."""

    upper, errors = resolve(upper_text, printer)
    lower, more = resolve(lower_text, printer)
    errors = [*dict.fromkeys([*errors, *more])]

    if upper is None or lower is None:
        return StackReport(False, tuple(errors), (), {})

    return check_resolved(upper, lower, printer)


def check_resolved(
    upper_resolved: Resolved, lower_resolved: Resolved, printer: Mapping[str, Any]
) -> StackReport:
    upper, lower = upper_resolved.item, lower_resolved.item
    upper_profile, lower_profile = upper_resolved.profile, lower_resolved.profile
    upper_hold = holding_for(upper.holding, upper.magnet, upper.fastener)
    lower_hold = holding_for(lower.holding, lower.magnet, lower.fastener)
    errors: list[str] = []

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
        "held_by": (
            "the lip alone" if lower.kind != "baseplate" else _held_by(upper_hold)
        ),
        "not_claimed": NOT_CLAIMED,
    }

    if not errors:
        errors += _overlap_errors(upper, lower, upper_profile, printer, summary)

    return StackReport(not errors, tuple(errors), tuple(warnings), summary)


def _held_by(holding: Holding) -> str:
    return (
        f"{holding.kind} ({holding.identifier})" if holding.holds else "the lip alone"
    )


def _overlap_errors(
    upper: Item,
    lower: Item,
    profile: Any,
    printer: Mapping[str, Any],
    summary: dict[str, Any],
) -> list[str]:
    """Lay the upper solid on the lower and measure any overlap."""

    upper_model, _, upper_summary = build_item(upper, profile, printer)
    lower_model, lower_height, _ = build_item(lower, profile, printer)
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
