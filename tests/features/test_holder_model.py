"""A holder for an object given as a STEP model.

The object is a mushroom: a 30 mm stem 60 mm long under a 50 mm cap 20 mm thick, modelled lying
on its side with the stem along +X. Turned so +X is up, it stands on its stem. Its pocket is the
cap's shadow, so it lifts straight out though it is narrower beneath.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest
from OCP.gp import gp_Pnt  # type: ignore[import-untyped]

from zcad_core.cli import main
from zcad_core.features.holder import build_holder
from zcad_core.features.holder_file import (
    check_holder_data,
    holder_template,
    inspect_holder_file,
    load_holder,
    load_holder_object,
)
from zcad_core.features.holder_model import HolderModel, rotation
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
SCREW = {
    "type": "screws",
    "head_diameter_mm": 8.0,
    "shank_diameter_mm": 4.0,
    "source": "a 4 x 30 mm wood screw, measured",
}


def mushroom(path: Path) -> Path:
    shape = (
        cq.Workplane("XY")
        .circle(15)
        .extrude(60)
        .faces(">Z")
        .workplane()
        .circle(25)
        .extrude(20)
        .rotate((0, 0, 0), (0, 1, 0), 90)
    )
    cq.exporters.export(shape, str(path), exportType="STEP")

    return path


def write_holder(tmp_path: Path, **changes: Any) -> Path:
    model = mushroom(tmp_path / "mushroom.step")
    data = holder_template(model=model)
    data["object"]["up"] = "+x"
    data["object"]["out"] = "+y"
    data.update(
        {
            "identifier": "MUSHROOM_HOLDER",
            "name": "Mushroom holder",
            "source": "a turned wooden mushroom, modelled",
            "mount": SCREW,
        }
    )
    data.update(changes)
    path = tmp_path / "holder.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    return path


def build(tmp_path: Path, **changes: Any) -> Any:
    spec = load_holder(write_holder(tmp_path, **changes))

    return build_holder(spec, load_holder_object(spec), PROFILE)


def turned(turn: Any, x: float, y: float, z: float) -> tuple[float, float, float]:
    point = gp_Pnt(x, y, z).Transformed(turn)

    return point.X(), point.Y(), point.Z()


def test_the_turn_takes_the_named_axes_to_up_and_out() -> None:
    turn = rotation("+x", "-z")

    assert turned(turn, 1, 0, 0) == pytest.approx((0, 0, 1))
    assert turned(turn, 0, 0, -1) == pytest.approx((0, 1, 0))
    # Never a mirror: the third axis follows from the other two.
    assert turned(turn, 0, 1, 0) == pytest.approx((-1, 0, 0))

    with pytest.raises(ValueError, match="square axes"):
        rotation("+x", "-x")


def test_a_modelled_object_stands_as_named_and_lifts_out_of_its_shadow(
    tmp_path: Path,
) -> None:
    holder = build(tmp_path)
    model = holder.item

    assert isinstance(model, HolderModel)
    assert model.size_mm == pytest.approx((50.0, 50.0, 80.0), abs=0.01)
    assert holder.passed, holder.checks
    assert holder.checks["object_lifts_out"]
    # A third of 80 mm.
    assert holder.front_mm == pytest.approx(80 / 3)
    assert holder.openings == ()
    width, depth, height = holder.size_mm
    # The cap's 50 mm shadow, 0.2 mm clearance and a 2 mm wall each side, and the plate's
    # 4 mm; the shadow is drawn to a grid, so it may be a pixel or so larger.
    assert width == pytest.approx(54.4, abs=0.3)
    assert depth == pytest.approx(4.0 + 0.4 + 50.0 + 2.0, abs=0.3)
    assert height == pytest.approx(82.0, abs=0.01)
    # The back plate is as wide as the cup, so nothing of the cup stands past it.
    assert holder.mount.plate_half_width_mm == pytest.approx(width / 2, abs=0.01)


def test_a_model_holder_takes_the_mounts_but_not_tabs(tmp_path: Path) -> None:
    holder = build(tmp_path, mount={"type": "keyhole"})

    assert [f.kind for f in holder.fixings] == ["keyhole"] * 2
    assert holder.passed, holder.checks

    with pytest.raises(ValueError, match="Retaining tabs need a captured object"):
        build(tmp_path, retention={"type": "tabs"})


def test_a_changed_model_or_a_missing_solid_is_refused(tmp_path: Path) -> None:
    path = write_holder(tmp_path)
    cq.exporters.export(
        cq.Workplane("XY").box(10, 10, 10), str(tmp_path / "mushroom.step"), "STEP"
    )
    report, _, item = inspect_holder_file(path)

    assert item is None
    assert any("has changed since" in error for error in report.errors)

    path = write_holder(tmp_path)
    data = json.loads(path.read_text())
    data["object"]["solid_index"] = 3
    path.write_text(json.dumps(data))
    report, _, item = inspect_holder_file(path)

    assert item is None
    assert any("the model has 1 solids" in error for error in report.errors)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"up": "+y", "out": "-y"}, "must be square to each other"),
        ({"up": "up"}, "object.up must be one of"),
        ({"solid_index": 0}, "solid_index must be a whole number from 1"),
        ({"capture": "remote.json"}, "must name a capture"),
        ({"down_edge": "south"}, "object has no down_edge for a model"),
    ],
)
def test_a_model_object_that_cannot_be_right_is_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    data = json.loads(write_holder(tmp_path).read_text())
    data["object"].update(change)

    assert any(message in error for error in check_holder_data(data).errors)


def test_a_model_holder_has_no_down_edge_or_face(tmp_path: Path) -> None:
    data = json.loads(write_holder(tmp_path).read_text())
    data["down_edge"] = "south"

    assert any(
        "down_edge is for a captured object" in error
        for error in check_holder_data(data).errors
    )


def test_the_commands_write_check_and_build_a_model_holder(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    model = mushroom(tmp_path / "part.step")
    template = tmp_path / "template.json"
    code = main(
        ["holder", "template", "--model", str(model), "--output", str(template)]
    )
    capsys.readouterr()
    written = json.loads(template.read_text())

    assert code == 0
    assert written["object"]["up"] == "+z"
    assert "down_edge" not in written

    path = write_holder(tmp_path)
    code = main(["holder", "check", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert code == 0, report
    assert report["object"]["kind"] == "model"

    output = tmp_path / "out"
    code = main(
        [
            "holder",
            "build",
            "--holder-file",
            str(path),
            "--output-directory",
            str(output),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["validation_status"] == "PASS"
    record = json.loads((output / "holder.json").read_text())
    assert record["object"]["kind"] == "model"
    assert record["object"]["up"] == "+x"
    assert record["settings"]["down_edge"] is None


def test_a_template_names_a_capture_or_a_model_not_both(tmp_path: Path) -> None:
    model = mushroom(tmp_path / "part.step")

    with pytest.raises(ValueError, match="not both"):
        holder_template(model, model)
