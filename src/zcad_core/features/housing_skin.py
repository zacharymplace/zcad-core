"""The skin side of a wearable housing: the face a body touches.

It gets two things and no more:

- **A rounded edge.** Every outer edge of the skin-facing face has at least the radius
  the housing sets (``skin_edge_radius_mm``, 0.8 mm by default). That is a comfort
  setting, **not a medical figure**: the engine states nothing about skin, comfort or
  contact. The edge round the housing's own body is rounded, and so is the free edge of
  each flat feature that lies on the skin plane (a band's ear, an adhesive flange, a
  lanyard's tab). A slot's edge, where a band passes, is not rounded.
- **No feature that stands off the face** except a way of wearing's: the build reports
  how far each stands proud of it. Only a belt clip does, and it stands on the back,
  where the belt goes.

The skin side is the lowest face of the housing's body, ``z == body.zmin``.
"""

from __future__ import annotations

from typing import Any

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape

_FLAT_MM = 1e-6


class SkinEdgeError(ValueError):
    """The skin side's edges cannot be rounded to the radius asked."""


def radius_limit_mm(floor_mm: float, wall_mm: float) -> float:
    """The most an outer skin edge can be rounded: the floor's thickness or the
    wall's, whichever is less, since a larger radius would round away more than the
    material there."""

    return min(floor_mm, wall_mm)


def _skin_faces(solid: cq.Solid) -> list[cq.Face]:
    zmin = solid.BoundingBox().zmin
    faces = []

    for face in solid.Faces():
        box = face.BoundingBox()

        if (
            face.geomType() == "PLANE"
            and abs(box.zmin - zmin) < _FLAT_MM
            and abs(box.zmax - zmin) < _FLAT_MM
            and face.normalAt().z < -0.9
        ):
            faces.append(face)

    return faces


def round_skin_edge(model: cq.Workplane, radius_mm: float) -> cq.Workplane:
    """The body with the outer edge of its skin face rounded to ``radius_mm``;
    ``model`` unchanged for zero."""

    if radius_mm <= 0:
        return model

    solids = workplane_shape(model).Solids()

    if len(solids) != 1:
        raise SkinEdgeError("The skin side can only be rounded on one solid")

    solid = solids[0]
    edges = [edge for face in _skin_faces(solid) for edge in face.outerWire().Edges()]

    if not edges:
        raise SkinEdgeError("The housing has no flat skin face to round")

    try:
        rounded = solid.fillet(radius_mm, edges)
    except ValueError as error:
        raise SkinEdgeError(
            f"The skin side's edge cannot be rounded to {radius_mm:g} mm: try a "
            "smaller radius"
        ) from error

    return cq.Workplane("XY").add(rounded)


def round_free_skin_edge(
    model: cq.Workplane, radius_mm: float, region: tuple[float, float, float, float]
) -> cq.Workplane:
    """A flat feature on the skin plane with the edges of its bottom face that lie
    outside the housing's body (``region``: its ``x`` and ``y`` extent) rounded; the
    edges that join the body are left."""

    if radius_mm <= 0:
        return model

    solid = workplane_shape(model).Solids()[0]
    edges = []
    xmin, xmax, ymin, ymax = region

    for face in _skin_faces(solid):
        for edge in face.outerWire().Edges():
            centre = edge.Center()
            inside = xmin < centre.x < xmax and ymin < centre.y < ymax

            if not inside:
                edges.append(edge)

    if not edges:
        return model

    try:
        return cq.Workplane("XY").add(solid.fillet(radius_mm, edges))
    except ValueError as error:
        raise SkinEdgeError(
            f"A flat feature on the skin plane cannot be rounded to {radius_mm:g} mm: "
            "try a smaller radius, or a thicker floor"
        ) from error


def proud_of_skin_face_mm(final: cq.Workplane, body_zmin: float) -> float:
    """How far anything stands below the skin face: zero when the face is the
    lowest thing."""

    return max(body_zmin - workplane_shape(final).BoundingBox().zmin, 0.0)


def skin_side_summary(
    radius_mm: float, proud_mm: float, wear: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the build says of the skin side: the radius and what it is, which edges
    were rounded, and what stands proud of the face."""

    return {
        "edge_radius_mm": radius_mm,
        "edge_radius_note": (
            "A comfort setting, not a medical figure: the engine states nothing about "
            "skin, comfort or contact."
        ),
        "rounded": (
            "the outer edge of the skin face, and the free edge of each flat feature "
            "on the skin plane"
            if radius_mm > 0
            else "nothing: the radius is zero"
        ),
        "not_rounded": "a slot's edge, where a band passes",
        "proud_of_the_skin_face_mm": round(proud_mm, 3),
        "stands_proud": [w["kind"] for w in wear if w.get("proud_mm", 0.0) > 0],
    }
