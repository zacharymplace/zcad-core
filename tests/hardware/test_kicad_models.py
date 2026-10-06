"""Part heights from the 3D models a KiCad footprint names.

The boards are written by hand to the format's documented tokens, and the
models are boxes written by CadQuery, so a height is known exactly. A model
turned about X or Y pins the convention the reader assumes, not KiCad's, so
the import marks it for review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.hardware.electronics.kicad_import import import_kicad
from zcad_core.hardware.electronics.kicad_models import MODEL_CHORD_MM

X0, Y0, X1, Y1 = 100.0, 50.0, 130.0, 90.0
MODEL = "${KICAD8_3DMODEL_DIR}/Package_SO.3dshapes/SOIC-8.wrl"


def line(x0: float, y0: float, x1: float, y1: float) -> str:
    return (
        f'(gr_line (start {x0} {y0}) (end {x1} {y1}) (layer "Edge.Cuts") '
        "(stroke (width 0.05) (type default)))"
    )


OUTLINE = "\n".join(
    [line(X0, Y0, X1, Y0), line(X1, Y0, X1, Y1), line(X1, Y1, X0, Y1)]
    + [line(X0, Y1, X0, Y0)]
)


def model(
    path: str = MODEL,
    *,
    offset: str = "(offset (xyz 0 0 0))",
    scale: tuple[float, float, float] = (1, 1, 1),
    rotate: tuple[float, float, float] = (0, 0, 0),
    hide: bool = False,
) -> str:
    return (
        f'(model "{path}" {"(hide yes)" if hide else ""} {offset} '
        f"(scale (xyz {scale[0]} {scale[1]} {scale[2]})) "
        f"(rotate (xyz {rotate[0]} {rotate[1]} {rotate[2]})))"
    )


def part(reference: str, x: float, y: float, *models: str) -> str:
    return (
        f'(footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" (layer "F.Cu") '
        f'(at {x} {y}) (property "Reference" "{reference}") '
        '(fp_rect (start -3 -2.5) (end 3 2.5) (layer "F.CrtYd") '
        f"(stroke (width 0.05) (type default))) {' '.join(models)})"
    )


def step(directory: Path, relative: str, size: tuple[float, float, float]) -> Path:
    """A box model standing on the board, ``size`` mm, centred in plan."""

    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    box = cq.Workplane("XY").box(*size, centered=(True, True, False))
    cq.exporters.export(box, str(path), exportType="STEP")

    return path


@pytest.fixture
def models(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    step(directory, "Package_SO.3dshapes/SOIC-8.step", (4.9, 3.9, 1.5))

    return directory


def read(tmp_path: Path, body: str, **options: Any) -> Any:
    path = tmp_path / "board.kicad_pcb"
    path.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew") '
        f"(general (thickness 1.6))\n{OUTLINE}\n{body}\n)\n",
        encoding="utf-8",
    )

    return import_kicad(path, **options)


def heights(imported: Any) -> dict[str, tuple[float, str]]:
    return {
        item["reference"]: (item["height_mm"], item["given_by"])
        for item in imported.report["parts"]["heights"]
    }


def test_a_parts_height_is_the_top_of_its_step_model(
    tmp_path: Path, models: Path
) -> None:
    imported = read(tmp_path, part("U1", 115, 70, model()), models_directory=models)
    (item,) = imported.report["parts"]["heights"]

    # The VRML path finds the STEP file beside it, under the variable dropped.
    assert item["height_mm"] == 1.5 + MODEL_CHORD_MM
    assert item["given_by"] == "--models"
    assert item["source"].startswith("3D model Package_SO.3dshapes/SOIC-8.step, ")
    assert imported.data["components"][0]["height_mm"] == 1.51
    assert "1 from 3D models under models" in imported.data["source"]
    assert imported.report["parts"]["models"]["heights"] == 1
    assert imported.report["unverified_transforms"] == []


def test_a_model_found_by_its_file_name_alone(tmp_path: Path) -> None:
    directory = tmp_path / "flat"
    step(directory, "SOIC-8.stp", (4.9, 3.9, 1.2))
    imported = read(tmp_path, part("U1", 115, 70, model()), models_directory=directory)

    assert heights(imported)["U1"][0] == pytest.approx(1.21)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"scale": (1, 1, 2)}, 3.0),
        ({"offset": "(offset (xyz 0 0 0.5))"}, 2.0),
        # KiCad 5's at is in inches: 0.02 in is 0.508 mm.
        ({"offset": "(at (xyz 0 0 0.02))"}, 2.008),
        ({"rotate": (0, 0, 90)}, 1.5),
    ],
)
def test_the_models_scale_offset_and_turn_about_z(
    tmp_path: Path, models: Path, options: dict[str, Any], expected: float
) -> None:
    imported = read(
        tmp_path, part("U1", 115, 70, model(**options)), models_directory=models
    )

    assert heights(imported)["U1"][0] == pytest.approx(expected + MODEL_CHORD_MM)
    assert imported.report["unverified_transforms"] == []


def test_a_model_turned_about_x_is_turned_and_needs_review(
    tmp_path: Path, models: Path
) -> None:
    imported = read(
        tmp_path,
        part("U1", 115, 70, model(rotate=(90, 0, 0))),
        models_directory=models,
    )

    # Turned up on end, the box's 3.9 mm depth stands half above the board.
    assert heights(imported)["U1"][0] == pytest.approx(1.95 + MODEL_CHORD_MM)
    assert imported.report["unverified_transforms"] == [
        "U1: its 3D model turned 90 about X and 0 about Y"
    ]
    assert any(
        item.startswith("footprint_transforms")
        for item in imported.data["needs_review"]
    )


def test_a_heights_file_beats_a_model_which_beats_the_default(
    tmp_path: Path, models: Path
) -> None:
    file = tmp_path / "heights.json"
    file.write_text(json.dumps({"U1": {"height_mm": 1.75, "source": "datasheet"}}))
    body = (
        part("U1", 107, 60, model())
        + part("U2", 123, 60, model())
        + part("U3", 107, 80)
        + part("U4", 123, 80, model("${KIPRJMOD}/models/missing.wrl"))
    )
    imported = read(
        tmp_path,
        body,
        heights_file=file,
        models_directory=models,
        default_height_mm=4.0,
        default_height_source="tallest part, measured",
    )

    assert heights(imported) == {
        "U1": (1.75, "U1"),
        "U2": (1.51, "--models"),
        "U3": (4.0, "--default-height"),
        "U4": (4.0, "--default-height"),
    }
    assert imported.report["parts"]["models"]["not_read"] == [
        {
            "reference": "U4",
            "model": "${KIPRJMOD}/models/missing.wrl",
            "why": "no STEP file for it under --models",
        }
    ]
    assert (
        "1 from heights.json" in imported.data["source"]
        and "1 from 3D models" in imported.data["source"]
        and "2 one default of 4 mm" in imported.data["source"]
    )


def test_a_part_with_a_model_not_found_gets_no_model_height(
    tmp_path: Path, models: Path
) -> None:
    body = part("U1", 115, 70, model(), model("${KIPRJMOD}/lid.wrl"))
    imported = read(tmp_path, body, models_directory=models)

    assert imported.report["parts"]["without_height"] == ["U1"]
    assert "--models" in next(
        item for item in imported.data["needs_review"] if item.startswith("heights")
    )


def test_a_hidden_model_is_skipped(tmp_path: Path, models: Path) -> None:
    body = part("U1", 115, 70, model(), model("${KIPRJMOD}/lid.wrl", hide=True))
    imported = read(tmp_path, body, models_directory=models)

    assert heights(imported)["U1"] == (1.51, "--models")


def test_a_model_path_cannot_reach_outside_the_directory(
    tmp_path: Path, models: Path
) -> None:
    step(tmp_path, "outside.step", (1, 1, 9))
    body = part("U1", 115, 70, model("${KIPRJMOD}/../outside.step"))
    imported = read(tmp_path, body, models_directory=models)

    assert imported.report["parts"]["without_height"] == ["U1"]


def test_models_need_a_directory_and_a_board_with_parts(
    tmp_path: Path, models: Path
) -> None:
    with pytest.raises(ValueError, match="is not a directory"):
        read(tmp_path, part("U1", 115, 70), models_directory=tmp_path / "none")

    with pytest.raises(ValueError, match="--models has nothing to size"):
        read(tmp_path, "", models_directory=models)


def test_the_command_reads_heights_from_models(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, models: Path
) -> None:
    source = tmp_path / "board.kicad_pcb"
    source.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew") '
        f"(general (thickness 1.6))\n{OUTLINE}\n{part('U1', 115, 70, model())}\n)\n",
        encoding="utf-8",
    )
    output = tmp_path / "board.json"
    code = main(
        [
            "board",
            "import",
            "--kicad",
            str(source),
            "--output",
            str(output),
            "--models",
            str(models),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["parts"]["models"]["heights"] == 1
    assert json.loads(output.read_text())["components"][0]["height_mm"] == 1.51


def test_a_step_import_refuses_models(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        [
            "board",
            "import",
            "--step",
            str(tmp_path / "x.step"),
            "--output",
            str(tmp_path / "c.json"),
            "--models",
            str(tmp_path),
        ]
    )

    assert code == 1
    assert "--models is for a KiCad file" in capsys.readouterr().err
