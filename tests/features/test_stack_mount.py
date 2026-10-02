"""The stack mount: a plate that bolts to an enclosure's pads and stands on the grid."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure import EnclosureDesign
from zcad_core.features.enclosure_group_model import GroupDesign
from zcad_core.features.mount_stack import (
    build_stack_plate,
    recess_depth_mm,
    require_plate_fits_bed,
)
from zcad_core.features.mounts import MOUNTS, build_mount, mount_pads
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import load_profile, profile_template
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import get_fastener
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
M3 = get_fastener("M3")


def write_profile(directory: Path, **changes: Any) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    data.update(changes)
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def pads_for(x: float = 60.0, y: float = 40.0) -> Any:
    return mount_pads(
        x_span_mm=(0.0, x),
        y_span_mm=(0.0, y),
        floor_underside_z_mm=0.0,
        floor_mm=2.0,
        wall_mm=2.0,
        fastener=M3,
    )


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def test_stack_is_a_mount_and_goes_with_its_profile() -> None:
    assert "stack" in MOUNTS

    with pytest.raises(ValueError, match="go together"):
        EnclosureDesign(mount="stack").validate()

    with pytest.raises(ValueError, match="go together"):
        EnclosureDesign(mount="keyhole", stack_profile="p.json").validate()

    with pytest.raises(ValueError, match="go together"):
        GroupDesign(mount="stack").validate()

    EnclosureDesign(mount="stack", stack_profile="p.json").validate()


def test_a_stack_mount_without_a_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a stack profile"):
        build_mount("stack", pads_for(), fastener=M3)


def test_the_plate_is_whole_cells_with_its_feet_below_and_its_top_on_the_pads(
    tmp_path: Path,
) -> None:
    profile = load_profile(write_profile(tmp_path))
    pads = pads_for()
    mount = build_stack_plate(
        pads, fastener=M3, profile=profile, plate_mm=4.0, compensation=0.0
    )
    box = workplane_shape(mount.plate).BoundingBox()
    cells = mount.stack["cells"] if mount.stack else None

    assert cells is not None
    assert box.xlen == pytest.approx(cells[0] * 42.0 - 0.5, abs=0.01)
    assert box.ylen == pytest.approx(cells[1] * 42.0 - 0.5, abs=0.01)
    # The top is the pads' bottoms, the foot hangs 4.75 mm and the plate is 4 mm.
    assert box.zmax == pytest.approx(pads.mating_z_mm, abs=0.001)
    assert box.zlen == pytest.approx(4.75 + 4.0, abs=0.001)
    assert mount.stack is not None
    assert mount.stack["profile"]["sha256"] == profile.sha256
    assert mount.stack["holding"] == "lip"
    # It covers the pads' footprint.
    xs = [x for x, _ in pads.positions]
    assert box.xmin < min(xs) and box.xmax > max(xs)


def test_each_screw_goes_up_through_a_foot_with_its_head_in_a_recess(
    tmp_path: Path,
) -> None:
    profile = load_profile(write_profile(tmp_path))
    pads = pads_for()
    mount = build_stack_plate(
        pads, fastener=M3, profile=profile, plate_mm=4.0, compensation=0.0
    )
    x, y = pads.positions[0]
    bottom = pads.mating_z_mm - (4.75 + 4.0)

    # A recess for the head, a clearance hole above it, and solid foot between.
    assert not inside(mount.plate, x, y, bottom + 1.0)
    assert not inside(mount.plate, x + 2.5, y, bottom + 1.0)
    assert not inside(mount.plate, x, y, bottom + 4.0)
    assert inside(mount.plate, x + 2.5, y, bottom + 4.0)
    assert inside(mount.plate, x + 2.5, y, bottom + 7.0)
    assert not inside(mount.plate, x, y, bottom + 7.0)
    # Its reach is the foot above the recess, the plate and the insert's depth.
    assert recess_depth_mm(M3) == pytest.approx(3.5)
    assert mount.stack is not None
    assert mount.stack["screw_reach_mm"] == pytest.approx(
        (4.75 - 3.5) + 4.0 + pads.pocket_depth_mm
    )
    assert mount.recommended_screw_mm == 10


def test_a_plate_that_would_put_a_screw_on_a_foots_edge_is_refused(
    tmp_path: Path,
) -> None:
    # Cells of 20 mm leave a foot too small for any recess round a pad.
    profile = load_profile(write_profile(tmp_path, pitch_mm=20.0, holding_points=[]))

    with pytest.raises(ValueError, match="No stack plate of"):
        build_stack_plate(
            pads_for(), fastener=M3, profile=profile, plate_mm=4.0, compensation=0.0
        )


def test_a_foot_too_short_for_the_screw_head_is_refused(tmp_path: Path) -> None:
    foot, lip = [[2.0, 0.0], [0.0, 2.0]], [[1.5, 0.0], [0.0, 1.5]]
    profile = load_profile(
        write_profile(
            tmp_path,
            foot=foot,
            lip=lip,
            min_nest_clearance_mm=0.2,
            corner_radius_mm=3.0,
        )
    )

    with pytest.raises(ValueError, match="head needs a recess"):
        build_stack_plate(
            pads_for(), fastener=M3, profile=profile, plate_mm=4.0, compensation=0.0
        )


def test_a_plate_bigger_than_the_bed_is_refused_with_its_cells(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path))
    mount = build_stack_plate(
        pads_for(176.0, 96.0),
        fastener=M3,
        profile=profile,
        plate_mm=4.0,
        compensation=0.0,
    )

    assert mount.stack is not None and mount.stack["cells"][0] == 5

    with pytest.raises(ValueError, match="The stack plate is 5 x"):
        require_plate_fits_bed(mount, PRINTER["build_volume_mm"])

    require_plate_fits_bed(None, PRINTER["build_volume_mm"])


def build_pico(tmp_path: Path, directory: str = "pico") -> Path:
    profile = write_profile(tmp_path)
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--mount",
        "stack",
        "--stack-profile",
        str(profile),
        "--output-directory",
        str(tmp_path / directory),
    )

    assert code == 0
    assert built["validation_status"] == "PASS"
    assert built["mount"]["stack"]["cells"] == [1, 2]
    assert "in a head recess" in built["mount"]["screws"]
    assert "mount" in built["parts"]

    return tmp_path / directory / "enclosure.json"


def write_stack_file(directory: Path, items: list[dict[str, Any]]) -> Path:
    profile = directory / "profile.json"
    data = stack_template(profile)
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def check(upper: Path, lower: str) -> tuple[int, dict[str, Any]]:
    return run("stack", "check-stack", "--upper", str(upper), "--lower", lower)


def test_an_enclosure_with_a_stack_plate_records_it_and_stacks(tmp_path: Path) -> None:
    record = build_pico(tmp_path)
    data = json.loads(record.read_text())
    stack = write_stack_file(
        tmp_path,
        [
            {"kind": "baseplate", "name": "base", "cells": [2, 2]},
            {"kind": "bin", "name": "tub", "cells": [1, 2], "units": 2},
            {"kind": "bin", "name": "small", "cells": [1, 1], "units": 2},
            {"kind": "cap", "name": "lid", "cells": [1, 2]},
        ],
    )

    assert data["stack"]["cells"] == [1, 2]
    assert data["stack"]["profile"]["identifier"] == "EXAMPLE_PROFILE"
    code, report = check(record, f"{stack}:base")
    assert code == 0 and report["stacks"] is True, report
    assert report["upper"].startswith("raspberry-pi-pico-2-enclosure (plate")
    code, report = check(record, f"{stack}:tub")
    assert code == 0 and report["held_by"] == "the lip alone"
    code, report = check(record, f"{stack}:small")
    assert code == 1 and any("of the same cells" in e for e in report["errors"])
    code, report = check(record, f"{stack}:lid")
    assert code == 1 and any("nothing stacks on lid" in e for e in report["errors"])


def test_a_record_without_a_stack_plate_says_how_to_build_one(tmp_path: Path) -> None:
    code, _ = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--output-directory",
        str(tmp_path / "plain"),
    )
    stack = write_stack_file(
        tmp_path, [{"kind": "baseplate", "name": "base", "cells": [2, 2]}]
    )
    code, report = check(tmp_path / "plain" / "enclosure.json", f"{stack}:base")

    assert code == 1
    assert any("has no stack plate" in e for e in report["errors"])


def test_a_plate_on_a_profile_that_changed_is_not_trusted(tmp_path: Path) -> None:
    record = build_pico(tmp_path)
    stack = write_stack_file(
        tmp_path, [{"kind": "baseplate", "name": "base", "cells": [2, 2]}]
    )
    write_profile(tmp_path, min_nest_clearance_mm=0.2)
    code, report = check(record, f"{stack}:base")

    assert code == 1
    assert any("has changed since the build" in e for e in report["errors"])


def test_a_group_enclosure_builds_a_stack_plate_too(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        "pi5",
        "--mount",
        "stack",
        "--stack-profile",
        str(profile),
        "--output-directory",
        str(tmp_path / "group"),
    )

    assert code == 0
    assert built["validation_status"] == "PASS"
    record = tmp_path / "group" / "enclosure-group.json"
    assert json.loads(record.read_text())["stack"]["cells"] == [3, 3]
    stack = write_stack_file(
        tmp_path, [{"kind": "baseplate", "name": "base", "cells": [3, 3]}]
    )
    code, report = check(record, f"{stack}:base")

    assert code == 0 and report["stacks"] is True, report
