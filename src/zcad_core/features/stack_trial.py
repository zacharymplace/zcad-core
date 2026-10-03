"""Print records for stackable items: what was built, and how it stacked.

``stack build`` writes a ``stack-build.json`` build record beside the exported parts: the
stack file and the profile by hash with the profile's source, each item as built (its settings,
what the build said of it, and its part's STL hash), the checks a trial asks, and the dimensions
it measures. A trial then records one print of exactly those parts, in the style of
:mod:`zcad_core.features.enclosure_trial`:

1. :func:`start_stack_trial` writes ``trials/trial-NNN/`` with ``observations.json`` and
   ``measurements.json`` listing only the checks and dimensions that apply to these items, and
   ``stacking.json`` for the readings of stacking them.
2. Fill them in after printing and stacking.
3. :func:`complete_stack_trial` validates them and writes ``stack-trial.json``. A completed
   trial is never overwritten.

``latch.json`` holds the readings of the latches and detents an item has, if it has any: whether
a hooked item **clicked on** and **off**, the **force** a spring scale reads separating it, and a
**count of snaps** with whether anything wore; for a drawer with a detent, whether it clicked shut
and open, the **force** to pull it out of its dimples, and the same count. The engine states no
limit for any, and no holding force.

``stacking.json`` holds four kinds of reading for each item: a **wobble**, the gap a feeler
gauge finds when the item is pressed down at one side; the **force** a spring scale reads
separating it from what it sits on; a **count of stackings** with whether anything wore; and
a list of **other makers' parts** it was tried on, each with whether it sat. The engine states
no limit for any reading, and makes no claim of compatibility from one.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.features.enclosure_trial import (
    MEASUREMENTS,
    OBSERVATIONS,
    EnclosureTrialDisposition,
    _measurements,
    _observations,
    _positive,
    _read,
    sha256,
)
from zcad_core.features.stack import Stack
from zcad_core.features.stack_file import Item
from zcad_core.geometry.cadquery_support import workplane_shape

STACK_BUILD_SCHEMA_VERSION = "1.1.0"
STACK_TRIAL_SCHEMA_VERSION = "1.1.0"
RECORD_KIND = "stack-build"
BUILD_RECORD = "stack-build.json"
TRIAL_RECORD = "stack-trial.json"
STACKING = "stacking.json"
LATCH = "latch.json"

NO_LIMIT = (
    "The engine states no limit for any reading here, and no figure to compare one with: "
    "it records what was measured and what was seen, and claims no compatibility from it."
)
_GUIDANCE = {
    "printed_cleanly": (
        "The part printed without warping, stringing, or a failed foot, lip or pocket"
    ),
    "sits_flat": (
        "It sits on a baseplate, or on a bin of its cells, resting flat, with its foot "
        "down in the pockets or the lip"
    ),
    "stacks_square": (
        "A second one stacks on it with the foot in the lip all round, square, with no "
        "gap you can see at any corner"
    ),
    "pockets_clean": "Every cell's pocket is clean, and a bin's foot goes in without forcing",
    "magnets_seat": (
        "Each magnet pushes into its pocket flush and stays; the engine does not say which "
        "way it faces, and you check that the pair attract"
    ),
    "screw_reaches_insert": (
        "A screw from below passes the floor and the foot's recess and reaches the heat-set "
        "insert, its head sitting clear"
    ),
    "sits_on_its_bin": "The cap sits in the bin's lip, flat, with no rocking",
    "drawers_slide": "Each drawer goes in and out of every slot without binding or scraping",
    "slides_free": "The drawer slides along its ledges the whole way without binding",
    "latch_clicks": (
        "It presses onto what it sits on and the hooks click into the keepers, and it lifts "
        "off to a pull and the hooks let go, with nothing cracking or whitening"
    ),
    "keepers_clean": (
        "Every keeper is clean and open, a hook goes into it without forcing, and the "
        "wall behind it is sound"
    ),
    "detent_clicks": (
        "The drawer clicks into its dimples pushed shut and clicks out pulled, on both "
        "sides, with the tongues springing back and nothing cracking"
    ),
    "dimples_clean": "Every dimple in the frame's side walls is clean, open and sound",
}


def _snap_checks(item: Item) -> list[str]:
    """What a trial asks of an item's latch or detent: hooks click, keepers are clean, a
    drawer's bumps click, a frame's dimples are clean."""

    checks: list[str] = []

    if item.latch_sides:
        if item.kind in ("bin", "frame", "cap"):
            checks.append("latch_clicks")

        if item.kind in ("baseplate", "bin", "frame"):
            checks.append("keepers_clean")

    if item.detent:
        checks.append("detent_clicks" if item.kind == "drawer" else "dimples_clean")

    return checks


def _item_checks(item: Item) -> list[str]:
    """What a trial asks of one item, named ``<item>.<check>``."""

    checks = ["printed_cleanly"]

    if item.kind == "baseplate":
        checks.append("pockets_clean")
    elif item.kind == "drawer":
        checks.append("slides_free")
    elif item.kind == "cap":
        checks.append("sits_on_its_bin")
    else:
        checks += ["sits_flat", "stacks_square"]

    if item.kind == "frame":
        checks.append("drawers_slide")

    if item.holding == "magnet":
        checks.append("magnets_seat")
    elif item.holding == "bolt":
        checks.append("screw_reaches_insert")

    checks += _snap_checks(item)

    return [f"{item.name}.{check}" for check in checks]


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    return _GUIDANCE[name.rsplit(".", 1)[1]]


def _measure_key(name: str, taken: dict[str, float]) -> str:
    """An item's name as a measurement's, lowercase with underscores, kept apart from
    another item that comes to the same."""

    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "item"
    base, number = key, 2

    while f"{key}_width_mm" in taken:
        key = f"{base}_{number}"
        number += 1

    return key


def nominal_measurements(stack: Stack) -> dict[str, float]:
    """The sizes a trial measures with calipers, in mm, from the solids as built."""

    nominals: dict[str, float] = {}

    for name, model in stack.parts.items():
        key = _measure_key(name, nominals)
        box = workplane_shape(model).BoundingBox()
        nominals[f"{key}_width_mm"] = round(box.xlen, 3)
        nominals[f"{key}_depth_mm"] = round(box.ylen, 3)
        nominals[f"{key}_height_mm"] = round(box.zlen, 3)
        summary = stack.summary["items"].get(name, {})
        latch, detent = summary.get("latch"), summary.get("detent")

        if latch is not None:
            nominals[f"{key}_hook_stand_out_mm"] = latch["protrusion_mm"]
            nominals[f"{key}_keeper_depth_mm"] = latch["keeper_depth_mm"]

        if detent is not None:
            nominals[f"{key}_bump_stand_out_mm"] = detent["protrusion_mm"]
            nominals[f"{key}_dimple_depth_mm"] = detent["dimple_depth_mm"]

    return nominals


def item_record(item: Item) -> dict[str, Any]:
    """An item's settings, as a record keeps them."""

    return asdict(item)


def item_from_record(entry: dict[str, Any]) -> Item:
    """The item a record's settings describe."""

    return Item(
        kind=str(entry["kind"]),
        name=str(entry["name"]),
        cells=(int(entry["cells"][0]), int(entry["cells"][1])),
        units=int(entry["units"]),
        wall_mm=float(entry["wall_mm"]),
        floor_mm=float(entry["floor_mm"]),
        rim_mm=float(entry["rim_mm"]),
        dividers=(int(entry["dividers"][0]), int(entry["dividers"][1])),
        label_tab=bool(entry["label_tab"]),
        scoop=bool(entry["scoop"]),
        holding=str(entry["holding"]),
        magnet=str(entry["magnet"]),
        fastener=str(entry["fastener"]),
        drawers=int(entry["drawers"]),
        frame=str(entry["frame"]),
        pull=bool(entry["pull"]),
        latch_sides=tuple(str(side) for side in entry.get("latch_sides", [])),
        latch_engagement_mm=(
            None
            if entry.get("latch_engagement_mm") is None
            else float(entry["latch_engagement_mm"])
        ),
        detent=bool(entry.get("detent", False)),
        detent_engagement_mm=(
            None
            if entry.get("detent_engagement_mm") is None
            else float(entry["detent_engagement_mm"])
        ),
        stop=bool(entry.get("stop", False)),
    )


def write_stack_record(
    output_directory: Path,
    *,
    stack: Stack,
    design_name: str,
    printer_profile_id: str,
    part_stls: dict[str, Path],
) -> Path:
    """Write ``stack-build.json``; refuses to replace one."""

    path = output_directory / BUILD_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    spec = stack.spec
    profile = stack.summary
    checks = [check for item in spec.items for check in _item_checks(item)]
    record = {
        "schema_version": STACK_BUILD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": design_name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "stack_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "profile": {
            "identifier": profile["profile"],
            "path": str(spec.profile_path),
            "sha256": profile["profile_sha256"],
            "pitch_mm": profile["pitch_mm"],
            "height_unit_mm": profile["height_unit_mm"],
        },
        "items": {
            item.name: {
                "item": item_record(item),
                "summary": profile["items"][item.name],
                "part": {
                    "stl_path": str(part_stls[item.name]),
                    "stl_sha256": sha256(part_stls[item.name]),
                },
            }
            for item in spec.items
        },
        "printer_profile_id": printer_profile_id,
        "fit_checks": stack.checks,
        "checks": checks,
        "nominal_measurements_mm": nominal_measurements(stack),
        "not_claimed": list(stack.notes),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


def _stacking_template(build: dict[str, Any]) -> dict[str, Any]:
    """The stacking readings: blanks for a feeler gauge, a spring scale and a count, and a
    place to name another maker's part. Leave a reading blank when it was not taken."""

    return {
        "not_a_limit": NO_LIMIT,
        "items": {
            name: {
                "guidance": (
                    "wobble_mm: the gap a feeler gauge finds at a corner when the item is "
                    "pressed down at the opposite side; separation_force_n: the highest "
                    "force a spring scale reads pulling it off what it sits on; "
                    "stackings_counted: how many times it was stacked and lifted off, and "
                    "anything_wore whether it or what it sits on wore or cracked"
                ),
                "wobble_mm": None,
                "separation_force_n": None,
                "stackings_counted": None,
                "anything_wore": None,
                "notes": "",
            }
            for name in build["items"]
            if build["items"][name]["item"]["kind"] != "drawer"
        },
        "other_makers": [
            {
                "part": "",
                "sits_on": None,
                "notes": "",
                "guidance": (
                    "Name a baseplate or bin of another maker that you tried it on, say "
                    "whether it sat, and leave this entry blank if you tried none"
                ),
            }
        ],
    }


def _snap_items(build: dict[str, Any]) -> dict[str, str]:
    """The items whose snaps a trial reads: ``hook`` for one that carries hooks and ``drawer``
    for a drawer with a detent. A frame's dimples and a baseplate's keepers are read through
    what clicks into them."""

    snaps: dict[str, str] = {}

    for name, entry in build["items"].items():
        item = entry["item"]

        if item["kind"] == "drawer" and item.get("detent"):
            snaps[name] = "drawer"
        elif item["kind"] in ("bin", "frame", "cap") and item.get("latch_sides"):
            snaps[name] = "hook"

    return snaps


def _latch_template(build: dict[str, Any]) -> dict[str, Any] | None:
    """The latch readings: yes-or-no for each click, a spring scale and a count. Leave a
    reading blank when it was not taken."""

    snaps = _snap_items(build)

    if not snaps:
        return None

    items: dict[str, Any] = {}

    for name, kind in snaps.items():
        summary = build["items"][name]["summary"]

        if kind == "drawer":
            items[name] = {
                "designed": summary["detent"],
                "guidance": (
                    "clicked_shut and clicked_open: whether the drawer clicked into its dimples "
                    "and out of them; pull_force_n: the highest force a spring scale reads "
                    "pulling it out of the dimples; snaps_counted: how many times it was "
                    "clicked shut and pulled, and anything_wore whether a tongue or a dimple "
                    "wore, cracked or went slack"
                ),
                "clicked_shut": None,
                "clicked_open": None,
                "pull_force_n": None,
                "snaps_counted": None,
                "anything_wore": None,
                "notes": "",
            }
        else:
            items[name] = {
                "designed": summary["latch"],
                "guidance": (
                    "clicked_on and clicked_off: whether the hooks clicked into the keepers "
                    "and let go; separation_force_n: the highest force a spring scale reads "
                    "pulling it off; snaps_counted: how many times it was snapped on and "
                    "pulled off, and anything_wore whether a tongue, a hook or a keeper "
                    "wore, cracked or went slack"
                ),
                "clicked_on": None,
                "clicked_off": None,
                "separation_force_n": None,
                "snaps_counted": None,
                "anything_wore": None,
                "notes": "",
            }

    return {"not_a_limit": NO_LIMIT, "items": items}


def start_stack_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation, measurement and stacking templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations = {
        check: {"result": "pending", "guidance": check_guidance(check), "notes": ""}
        for check in build["checks"]
    }
    measurements = {
        name: {"nominal_mm": nominal, "value_mm": None, "notes": ""}
        for name, nominal in build["nominal_measurements_mm"].items()
    }
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )
    (trial / STACKING).write_text(
        json.dumps(_stacking_template(build), indent=2) + "\n", encoding="utf-8"
    )
    latch = _latch_template(build)

    if latch is not None:
        (trial / LATCH).write_text(json.dumps(latch, indent=2) + "\n", encoding="utf-8")

    return trial


def _wobble(entry: dict[str, Any], where: str) -> float | None:
    value = entry.get("wobble_mm")

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(
            f"{where}: wobble_mm must be a number from zero, not {value!r}"
        )

    return float(value)


def _count(entry: dict[str, Any], where: str) -> tuple[int | None, bool | None]:
    """The count of stackings and whether anything wore. Wear needs a count: an item is
    only as worn as the number of times it was stacked."""

    count, wore = entry.get("stackings_counted"), entry.get("anything_wore")

    if count is None:
        if wore is not None:
            raise ValueError(f"{where}: anything_wore needs stackings_counted")

        return None, None

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: stackings_counted must be a whole number from 1")

    if not isinstance(wore, bool):
        raise TypeError(f"{where}: anything_wore must be true or false")

    return count, wore


def _item_reading(name: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    where = f"stacking.json items.{name}"
    wobble = _wobble(entry, where)
    force = _positive(entry, "separation_force_n", where)
    count, wore = _count(entry, where)

    if wobble is None and force is None and count is None:
        return None

    return {
        "item": name,
        "wobble_mm": wobble,
        "separation_force_n": force,
        "stackings_counted": count,
        "anything_wore": wore,
        "notes": entry.get("notes", ""),
    }


def _other_makers(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The other makers' parts it was tried on. A blank entry is skipped; one with a
    part names whether it sat."""

    tried = []

    for index, entry in enumerate(entries):
        part = str(entry.get("part", "")).strip()
        sits = entry.get("sits_on")

        if not part and sits is None:
            continue

        where = f"stacking.json other_makers[{index}]"

        if not part:
            raise ValueError(f"{where}: sits_on needs the part's name")

        if not isinstance(sits, bool):
            raise TypeError(f"{where}: sits_on must be true or false")

        tried.append({"part": part, "sits_on": sits, "notes": entry.get("notes", "")})

    return tried


def _stacking_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's stacking readings, validated; ``None`` when none was taken."""

    path = trial / STACKING
    entry = _read(path) if path.is_file() else {}
    items = entry.get("items", {})
    unknown = sorted(set(items) - set(build["items"]))

    if unknown:
        raise ValueError(f"stacking.json items: not built in this stack: {unknown}")

    readings = [r for name, e in items.items() if (r := _item_reading(name, e))]
    others = _other_makers(entry.get("other_makers", []))

    if not readings and not others:
        return None

    return {"items": readings, "other_makers": others, "not_a_limit": NO_LIMIT}


def _yes_no(entry: dict[str, Any], name: str, where: str) -> bool | None:
    value = entry.get(name)

    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{where}: {name} must be true or false")

    return value


def _snap_reading(name: str, kind: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """One item's latch readings, validated; ``None`` when none was taken."""

    where = f"latch.json items.{name}"
    first, second, force_name = (
        ("clicked_shut", "clicked_open", "pull_force_n")
        if kind == "drawer"
        else ("clicked_on", "clicked_off", "separation_force_n")
    )
    clicked = (_yes_no(entry, first, where), _yes_no(entry, second, where))
    force = _positive(entry, force_name, where)
    count, wore = entry.get("snaps_counted"), entry.get("anything_wore")

    if count is None:
        if wore is not None:
            raise ValueError(f"{where}: anything_wore needs snaps_counted")
    elif isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: snaps_counted must be a whole number from 1")
    elif not isinstance(wore, bool):
        raise TypeError(f"{where}: anything_wore must be true or false")

    if clicked == (None, None) and force is None and count is None:
        return None

    return {
        "item": name,
        first: clicked[0],
        second: clicked[1],
        force_name: force,
        "snaps_counted": count,
        "anything_wore": wore,
        "notes": entry.get("notes", ""),
    }


def _latch_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's latch readings, validated and set beside what was designed; ``None``
    when none was taken."""

    path = trial / LATCH
    payload = _read(path) if path.is_file() else {}
    entries = payload.get("items", {})
    snaps = _snap_items(build)
    unknown = sorted(set(entries) - set(snaps))

    if unknown:
        raise ValueError(
            f"latch.json items: no latch or detent to read in this stack: {unknown}"
        )

    readings = []

    for name in sorted(entries):
        reading = _snap_reading(name, snaps[name], entries[name])

        if reading is not None:
            summary = build["items"][name]["summary"]
            reading["designed"] = summary[
                "detent" if snaps[name] == "drawer" else "latch"
            ]
            readings.append(reading)

    if not readings:
        return None

    return {"items": readings, "not_a_limit": NO_LIMIT}


def complete_stack_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in trial and write its record."""

    record_path = trial / TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as the next trial"
        )

    build_path = trial.parent.parent / BUILD_RECORD
    build = _read(build_path)
    changed = [
        name
        for name, entry in build["items"].items()
        if not Path(entry["part"]["stl_path"]).is_file()
        or sha256(Path(entry["part"]["stl_path"])) != entry["part"]["stl_sha256"]
    ]

    if changed:
        raise ValueError(
            f"The printed parts no longer match the build record: {changed}"
        )

    observations = _observations(trial, build["checks"])
    measurements = _measurements(trial)
    stacking = _stacking_readings(trial, build)
    latch = _latch_readings(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and stacking is None
        and latch is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement or stacking reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": STACK_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
        "profile_sha256": build["profile"]["sha256"],
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "disposition": disposition.value,
        "passed": disposition is EnclosureTrialDisposition.PASS,
        "failed_checks": failed,
        "observations": observations,
        "measurements": [
            {
                "name": m.name,
                "value_mm": m.value_mm,
                "nominal_mm": m.nominal_mm,
                "notes": m.notes,
                "deviation_mm": m.deviation_mm,
            }
            for m in measurements
        ],
        "stacking": stacking,
        "latch": latch,
        "notes": notes,
        "not_claimed": build.get("not_claimed", []),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path
