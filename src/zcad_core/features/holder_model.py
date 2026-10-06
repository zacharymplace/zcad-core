"""An object for a holder given as a STEP model, turned to hang as the holder holds it.

The holder file names the model, its SHA-256, and which of the model's own axes points ``up`` in
the holder (the way the object comes out) and which points ``out`` to the room. The model is
turned so those become the holder's +Z and +Y, with the third axis, ``out`` x ``up``, along +X so
the turn is a rotation and never a mirror. It is then set centred along the wall, its back face at
``y == 0`` and its lowest point on the floor, ``z == 0``.

Its pocket is the nest's: the model's shadow seen from above in the holder, which is the way the
object goes in and comes out, so any shape releases straight up whatever it does beneath its widest
point.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from OCP.gp import gp_Trsf  # type: ignore[import-untyped]

from zcad_core.geometry.silhouette import Silhouette, silhouette

AXES: dict[str, tuple[float, float, float]] = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}


@dataclass(frozen=True)
class HolderModel:
    """A model as it stands in the holder, with its shadow seen from above."""

    path: Path
    sha256: str
    solid_index: int | None
    up: str
    out: str
    # Centred along X, its back at y == 0, its lowest point at z == 0.
    shape: cq.Shape
    # The shadow about the centre of the model's footprint.
    shadow: Silhouette
    size_mm: tuple[float, float, float]
    solids: int

    @property
    def name(self) -> str:
        return self.path.name


def perpendicular(up: str, out: str) -> bool:
    a, b = AXES[up], AXES[out]

    return abs(sum(x * y for x, y in zip(a, b, strict=True))) < 1e-9


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def rotation(up: str, out: str) -> gp_Trsf:
    """The turn that takes the model's ``out`` to +Y and ``up`` to +Z."""

    if not perpendicular(up, out):
        raise ValueError(f"up ({up}) and out ({out}) must be different, square axes")

    along = _cross(AXES[out], AXES[up])
    turn = gp_Trsf()
    # Each row is where one of the holder's axes comes from in the model, with no move.
    turn.SetValues(*along, 0.0, *AXES[out], 0.0, *AXES[up], 0.0)

    return turn


def load_holder_model(
    path: Path,
    expected_sha256: str,
    solid_index: int | None,
    up: str,
    out: str,
) -> HolderModel:
    """The model a holder names, refused if it is missing, has changed since the holder file
    named it, holds no solids, or casts a shadow in more than one piece."""

    if not path.is_file():
        raise ValueError(f"The model is missing: {path}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    if digest != expected_sha256:
        raise ValueError(
            f"The model {path} has changed since the holder file named it: its SHA-256 is "
            f"{digest}, not {expected_sha256}"
        )

    # Imported here: reading a model needs CadQuery's STEP reader.
    from zcad_core.hardware.electronics.board_import import load_solids

    solids = load_solids(path)

    if not solids:
        raise ValueError(f"{path.name} holds no solids")

    if solid_index is not None:
        if solid_index > len(solids):
            raise ValueError(
                f"object.solid_index is {solid_index}; the model has {len(solids)} solids"
            )

        chosen = [solids[solid_index - 1]]
    else:
        chosen = solids

    shape: cq.Shape = (
        chosen[0] if len(chosen) == 1 else cq.Compound.makeCompound(chosen)
    )
    shape = shape.moved(cq.Location(rotation(up, out)))
    bounds = shape.BoundingBox()
    shape = shape.moved(
        cq.Location(
            cq.Vector(-(bounds.xmin + bounds.xmax) / 2, -bounds.ymin, -bounds.zmin)
        )
    )
    footprint = shape.moved(cq.Location(cq.Vector(0, -bounds.ylen / 2, 0)))

    return HolderModel(
        path=path,
        sha256=digest,
        solid_index=solid_index,
        up=up,
        out=out,
        shape=shape,
        shadow=silhouette(footprint),
        size_mm=(bounds.xlen, bounds.ylen, bounds.zlen),
        solids=len(chosen),
    )
