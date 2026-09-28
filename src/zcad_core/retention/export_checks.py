"""Retention-specific probes over exported candidate meshes.

These run on the exact STL bytes the export pipeline publishes, so they
check the printable result rather than the modelling intent:

- every connected body must rest on the build plane (no floating islands)
- nothing may sit within ``board_clearance_mm`` above the reference board
- some material must lie above the board footprint to capture it vertically

Board checks need the reference board's bounds; without them they are
reported as NOT_CHECKED rather than silently passing.
"""

from __future__ import annotations

import math
from typing import Any

from zcad_core.validation.stl_mesh import STLMesh

BOARD_BOUNDS_PARAMETER = "reference_board_bounds_mm"
BOARD_CLEARANCE_PARAMETER = "board_clearance_mm"

_PLANE_TOLERANCE_MM = 1e-3
_PROBE_INSET_MM = 0.05
_PROBE_OFFSET_MM = 1e-3
_MAX_PROBES_PER_AXIS = 40
_REPORTED_BODIES = 8


def _check(code: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "status": status, "message": message, **details}


def _supported_bodies(mesh: STLMesh, part_name: str) -> dict[str, Any]:
    bodies = mesh.body_bounds()
    plane_z = bodies[0][0][2]
    floating = [
        {"min_mm": list(low), "max_mm": list(high)}
        for low, high in bodies
        if low[2] > plane_z + _PLANE_TOLERANCE_MM
    ]

    return _check(
        "retention_supported_bodies",
        "FAIL" if floating else "PASS",
        (
            "Every connected body rests on the build plane in the exported "
            "orientation; supports and bridging are not modelled"
        ),
        part_name=part_name,
        body_count=len(bodies),
        build_plane_z_mm=plane_z,
        floating_body_count=len(floating),
        floating_bodies=floating[:_REPORTED_BODIES],
    )


def _footprint_probes(low: list[float], high: list[float]) -> list[tuple[float, float]]:
    axes = []

    for axis in (0, 1):
        start = low[axis] + _PROBE_INSET_MM
        end = high[axis] - _PROBE_INSET_MM

        if end <= start:
            return []

        count = min(_MAX_PROBES_PER_AXIS, max(2, math.ceil(end - start) + 1))
        axes.append([start + (end - start) * i / (count - 1) for i in range(count)])

    return [(x, y) for x in axes[0] for y in axes[1]]


def _board_checks(
    mesh: STLMesh,
    part_name: str,
    bounds: Any,
    clearance: Any,
) -> list[dict[str, Any]]:
    if bounds is None:
        return [
            _check(
                code,
                "NOT_CHECKED",
                "No reference board bounds supplied",
                part_name=part_name,
            )
            for code in ("retention_board_top_clearance", "retention_board_capture")
        ]

    low, high = [float(v) for v in bounds[0]], [float(v) for v in bounds[1]]
    probes = _footprint_probes(low, high)

    if not probes:
        raise ValueError("Reference board footprint is too small to probe")

    top = high[2]
    mesh_top = max(vertex[2] for triangle in mesh.triangles for vertex in triangle)
    checks = []

    if (
        isinstance(clearance, bool)
        or not isinstance(clearance, (int, float))
        or not math.isfinite(clearance)
        or clearance <= 2 * _PROBE_OFFSET_MM
    ):
        checks.append(
            _check(
                "retention_board_top_clearance",
                "NOT_CHECKED",
                "No usable board_clearance_mm supplied",
                part_name=part_name,
            )
        )
    else:
        blocked = [
            [x, y]
            for x, y in probes
            if not mesh.vertical_clearance(
                x, y, top + _PROBE_OFFSET_MM, top + clearance - _PROBE_OFFSET_MM
            )["clear"]
        ]
        checks.append(
            _check(
                "retention_board_top_clearance",
                "FAIL" if blocked else "PASS",
                "No geometry within board_clearance_mm above the board footprint",
                part_name=part_name,
                probe_count=len(probes),
                blocked_probe_count=len(blocked),
                blocked_probes_xy_mm=blocked[:_REPORTED_BODIES],
                clearance_mm=clearance,
            )
        )

    play = []

    if mesh_top > top + 2 * _PROBE_OFFSET_MM:
        for x, y in probes:
            result = mesh.vertical_clearance(x, y, top + _PROBE_OFFSET_MM, mesh_top)

            if not result["clear"]:
                heights = [c["z_mm"] for c in result["contacts"] if "z_mm" in c]
                play.append(min(heights) - top if heights else 0.0)

    checks.append(
        _check(
            "retention_board_capture",
            "PASS" if play else "FAIL",
            (
                "Material lies above the board footprint; vertical play is the "
                "smallest measured gap to it"
            ),
            part_name=part_name,
            probe_count=len(probes),
            captured_probe_count=len(play),
            vertical_play_mm=min(play) if play else None,
        )
    )

    return checks


def retention_stl_checks(
    *,
    design_type: str,
    parts: dict[str, STLMesh],
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    """STL feature validator for :class:`zcad_core.exporters.ExportRequest`."""

    del design_type
    checks = []

    for part_name, mesh in parts.items():
        checks.append(_supported_bodies(mesh, part_name))
        checks.extend(
            _board_checks(
                mesh,
                part_name,
                parameters.get(BOARD_BOUNDS_PARAMETER),
                parameters.get(BOARD_CLEARANCE_PARAMETER),
            )
        )

    return checks
