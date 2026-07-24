"""Reusable embossed-label features."""

import cadquery as cq


def add_embossed_label(
    model: cq.Workplane,
    *,
    text: str,
    x: float,
    y: float,
    base_height: float,
    text_size: float,
    emboss_height: float,
) -> cq.Workplane:
    """Union centered embossed text onto the top surface of a model."""
    if not text.strip():
        raise ValueError("text cannot be empty")

    if base_height <= 0:
        raise ValueError("base_height must be greater than zero")

    if text_size <= 0:
        raise ValueError("text_size must be greater than zero")

    if emboss_height <= 0:
        raise ValueError("emboss_height must be greater than zero")

    label = (
        cq.Workplane("XY")
        .workplane(offset=base_height / 2)
        .center(
            x,
            y,
        )
        .text(
            text,
            text_size,
            emboss_height,
            halign="center",
            valign="center",
        )
    )

    return model.union(label)
