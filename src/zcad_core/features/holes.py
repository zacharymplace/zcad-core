"""Reusable hole features."""

import cadquery as cq


def add_through_holes(
    model: cq.Workplane,
    *,
    points: list[tuple[float, float]],
    diameter: float,
    face_selector: str = ">Z",
) -> cq.Workplane:
    """Cut equal-diameter through holes at the supplied coordinates."""
    if diameter <= 0:
        raise ValueError("diameter must be greater than zero")

    if not points:
        raise ValueError("points cannot be empty")

    return model.faces(face_selector).workplane().pushPoints(points).hole(diameter)
