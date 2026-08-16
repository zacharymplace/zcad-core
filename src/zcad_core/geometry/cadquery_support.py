"""Typed access to cadquery Workplane results.

CadQuery's ``Workplane.val()`` is typed as returning
``Vector | Location | Shape | Sketch`` because a workplane's stack can
hold any of those. Every caller in this codebase only ever expects a
solid ``Shape``, so this narrows that union with an explicit runtime
check instead of asserting past it.
"""

from __future__ import annotations

import cadquery as cq


def workplane_shape(model: cq.Workplane) -> cq.Shape:
    """Return a Workplane's current value as a concrete Shape."""

    value = model.val()

    if not isinstance(value, cq.Shape):
        raise TypeError("CadQuery workplane does not contain a shape")

    return value
