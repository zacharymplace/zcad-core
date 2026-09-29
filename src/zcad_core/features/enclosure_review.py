"""A review package for a built enclosure: what to look at before printing.

The package holds a coloured, exploded GLB of the base, lid, and hardware,
the assembled STEP, orthographic SVG views, and ``enclosure-review.json``,
which records the part sizes, the nearest gap from each part to each piece of
hardware, the screws to buy, and the checks the enclosure must pass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly
from zcad_core.features.enclosure import Enclosure
from zcad_core.geometry.intersection import intersection_volume

ENCLOSURE_REVIEW_SCHEMA_VERSION = "1.0.0"

# Standard metric screw lengths; the review recommends the longest that the
# lid and insert take.
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20, 25, 30)
_TOLERANCE_MM3 = 1e-6
# A part closer than this to hardware is recorded as contact: expected where
# the board rests on its supports, worth a look anywhere else.
_CONTACT_MM = 0.05
# The board rests on its standoffs or cradle; the display rests against its
# retainer's pads.
_EXPECTED_CONTACT = {("base", "board"), ("lid", "display")}
_VIEWS = (
    ("top", (0.0, 0.0, 1.0)),
    ("front", (0.0, -1.0, 0.0)),
    ("right", (1.0, 0.0, 0.0)),
    ("isometric", (1.0, -1.0, 1.0)),
)
_COLOURS = {
    "base": cq.Color(0.16, 0.38, 0.82),
    "lid": cq.Color(0.55, 0.70, 0.95),
    "pcb": cq.Color(0.08, 0.55, 0.22),
    "connector": cq.Color(0.68, 0.70, 0.74),
    "display": cq.Color(0.12, 0.12, 0.14),
}


@dataclass(frozen=True)
class EnclosureReview:
    """Where the package was written and whether its checks passed."""

    glb_path: Path
    step_path: Path
    report_path: Path
    view_paths: tuple[Path, ...]
    passed: bool
    report: dict[str, Any]


def export_enclosure_review(
    enclosure: Enclosure,
    assembly: DeviceAssembly,
    *,
    output_directory: Path,
    exploded_gap_mm: float = 15.0,
) -> EnclosureReview:
    """Write the review package; refuses to overwrite an existing one."""

    if exploded_gap_mm < 0:
        raise ValueError("exploded_gap_mm must not be negative")

    glb_path = output_directory / "enclosure-review.glb"
    step_path = output_directory / "enclosure-review.step"
    report_path = output_directory / "enclosure-review.json"
    view_paths = tuple(
        output_directory / f"enclosure-review-{name}.svg" for name, _ in _VIEWS
    )
    outputs = (glb_path, step_path, report_path, *view_paths)
    existing = [str(path) for path in outputs if path.exists()]

    if existing:
        raise FileExistsError(
            f"Refusing to overwrite enclosure review: {', '.join(existing)}"
        )

    output_directory.mkdir(parents=True, exist_ok=True)
    base, lid = _single_shape(enclosure.base), _single_shape(enclosure.lid)
    hardware = {
        component.identifier: (
            _single_shape(component.transformed_geometry()),
            str(component.metadata.get("kind", "")),
        )
        for component in assembly.components
    }
    lifted_lid = lid.moved(cq.Location(cq.Vector(0, 0, exploded_gap_mm)))

    _assembly(base, lifted_lid, hardware).export(str(glb_path))
    _assembly(base, lid, hardware).export(str(step_path))
    _write_views(
        [base, lifted_lid, *(shape for shape, _ in hardware.values())], view_paths
    )

    report = _report(enclosure, base=base, lid=lid, hardware=hardware)
    report["artifacts"] = {
        "glb": str(glb_path),
        "step": str(step_path),
        **{
            f"{name}_view": str(path)
            for (name, _), path in zip(_VIEWS, view_paths, strict=True)
        },
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for path in outputs:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Enclosure review artifact was not written: {path}")

    return EnclosureReview(
        glb_path=glb_path,
        step_path=step_path,
        report_path=report_path,
        view_paths=view_paths,
        passed=bool(report["passed"]),
        report=report,
    )


def recommended_screw_length_mm(enclosure: Enclosure) -> int:
    """The longest standard screw the lid and insert take."""

    insert_depth = enclosure.fastener.heat_set_insert_depth_mm or 0.0
    usable = enclosure.design.lid_mm + insert_depth
    fitting = [length for length in _SCREW_LENGTHS_MM if length <= usable]

    if not fitting:
        raise ValueError("No standard screw is short enough for this lid")

    return fitting[-1]


def _display_fasteners(enclosure: Enclosure) -> dict[str, Any] | None:
    """The self-tapping screws that hold a display to its lid posts."""

    reach = enclosure.display_screw_reach_mm

    if reach is None:
        return None

    fitting = [length for length in _SCREW_LENGTHS_MM if length <= reach]

    return {
        "size": enclosure.design.display_fastener,
        "count": enclosure.display_screw_count,
        "kind": "self-tapping, into plastic",
        "recommended_screw_length_mm": fitting[-1] if fitting else None,
    }


def _single_shape(model: cq.Workplane) -> cq.Shape:
    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _assembly(
    base: cq.Shape, lid: cq.Shape, hardware: dict[str, tuple[cq.Shape, str]]
) -> cq.Assembly:
    assembly = cq.Assembly()
    assembly.add(base, name="enclosure-base", color=_COLOURS["base"])
    assembly.add(lid, name="enclosure-lid", color=_COLOURS["lid"])

    for identifier, (shape, kind) in hardware.items():
        assembly.add(
            shape,
            name=identifier,
            color=_COLOURS.get(kind, _COLOURS["connector"]),
        )

    return assembly


def _write_views(shapes: list[cq.Shape], paths: tuple[Path, ...]) -> None:
    compound = cq.Compound.makeCompound(shapes)

    for (_, projection), path in zip(_VIEWS, paths, strict=True):
        svg = cq.exporters.getSVG(
            compound,
            opts={
                "width": 1200,
                "height": 900,
                "marginLeft": 40,
                "marginTop": 40,
                "projectionDir": projection,
                "showAxes": False,
                "showHidden": True,
                "strokeWidth": 0.5,
            },
        )
        path.write_text(svg, encoding="utf-8")


def _inside(shape: cq.Shape, point: cq.Vector) -> bool:
    return any(solid.isInside(point) for solid in shape.Solids())


def _bounds(shape: cq.Shape) -> dict[str, float]:
    box = shape.BoundingBox()

    return {
        "x_mm": round(box.xlen, 3),
        "y_mm": round(box.ylen, 3),
        "z_mm": round(box.zlen, 3),
        "volume_mm3": round(shape.Volume(), 3),
    }


def _clearances(
    parts: dict[str, cq.Shape], hardware: dict[str, tuple[cq.Shape, str]]
) -> list[dict[str, Any]]:
    """The gap and overlap between every part and piece of hardware."""

    rows = []

    for part_name, part in parts.items():
        for identifier, (shape, _) in hardware.items():
            gap = part.distance(shape)
            rows.append(
                {
                    "part": part_name,
                    "hardware": identifier,
                    "gap_mm": round(gap, 3),
                    "contact": gap < _CONTACT_MM,
                    "overlap_mm3": round(intersection_volume(part, shape), 6),
                }
            )

    return rows


def _checks(
    enclosure: Enclosure,
    *,
    base: cq.Shape,
    lid: cq.Shape,
    clearances: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    spec = enclosure.specification
    cavity_top = spec.bottom_z_mm + spec.inner_height_mm
    pockets_open = all(
        not _inside(base, cq.Vector(x, y, cavity_top - 1.0))
        and not _inside(lid, cq.Vector(x, y, cavity_top + enclosure.design.lid_mm / 2))
        for x, y in enclosure.fastener_positions
    )
    connector_mid_z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2
    plug_bottom = connector_mid_z - enclosure.design.cable_plug_height_mm / 2
    unexpected_contact = sorted(
        f"{row['part']}/{row['hardware']}"
        for row in clearances
        if row["contact"] and (row["part"], row["hardware"]) not in _EXPECTED_CONTACT
    )

    return {
        "no_interference": {
            "passed": all(row["overlap_mm3"] <= _TOLERANCE_MM3 for row in clearances),
            "detail": "No part overlaps any hardware.",
        },
        "single_solid_parts": {
            "passed": all(len(part.Solids()) == 1 for part in (base, lid)),
            "detail": "The base and lid each print as one solid.",
        },
        "screw_path_open": {
            "passed": pockets_open,
            "detail": "Every lid hole is open above an empty insert pocket.",
        },
        "plug_body_clears_floor": {
            "passed": plug_bottom >= spec.bottom_z_mm,
            "detail": (
                f"The cable plug body reaches {round(plug_bottom, 3)} mm; "
                f"the floor is at {round(spec.bottom_z_mm, 3)} mm."
            ),
        },
        "only_expected_contact": {
            "passed": not unexpected_contact,
            "detail": (
                "Only the board touches the base (on its supports) and the "
                "display the lid (on its retainer pads)."
                if not unexpected_contact
                else "Unexpected contact: " + ", ".join(unexpected_contact)
            ),
        },
    }


def _report(
    enclosure: Enclosure,
    *,
    base: cq.Shape,
    lid: cq.Shape,
    hardware: dict[str, tuple[cq.Shape, str]],
) -> dict[str, Any]:
    clearances = _clearances({"base": base, "lid": lid}, hardware)
    checks = _checks(enclosure, base=base, lid=lid, clearances=clearances)
    spec = enclosure.specification

    return {
        "schema_version": ENCLOSURE_REVIEW_SCHEMA_VERSION,
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "design": asdict(enclosure.design),
        "side_clearance_mm": {
            "x": enclosure.side_clearance_mm[0],
            "y": enclosure.side_clearance_mm[1],
        },
        "board_support": enclosure.board_support,
        "cavity_mm": {
            "x": round(spec.inner_width_mm, 3),
            "y": round(spec.inner_depth_mm, 3),
            "z": round(spec.inner_height_mm, 3),
        },
        "parts": {"base": _bounds(base), "lid": _bounds(lid)},
        "fasteners": {
            "size": enclosure.fastener.identifier,
            "count": len(enclosure.fastener_positions),
            "heat_set_insert_mm": {
                "diameter": enclosure.fastener.heat_set_insert_diameter_mm,
                "depth": enclosure.fastener.heat_set_insert_depth_mm,
            },
            "recommended_screw_length_mm": recommended_screw_length_mm(enclosure),
            "positions_mm": [
                list(position) for position in enclosure.fastener_positions
            ],
        },
        "display_fasteners": _display_fasteners(enclosure),
        "cable_opening_mm": {
            "edge": spec.cable_edge,
            "connector": [
                round(spec.cable_width_mm, 3),
                round(spec.cable_height_mm, 3),
            ],
            "plug": [
                enclosure.design.cable_plug_width_mm,
                enclosure.design.cable_plug_height_mm,
            ],
        },
        "clearances": clearances,
    }
