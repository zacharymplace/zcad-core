"""Part heights from the 3D models a KiCad footprint names (``--models DIR``).

A footprint's ``(model "PATH" (offset (xyz X Y Z)) (scale (xyz ...)) (rotate
(xyz ...)))`` names a model file and how it sits on the footprint. The path
usually starts with a variable such as ``${KICAD8_3DMODEL_DIR}``, which is
dropped: the rest is looked for under the directory the user gives, then its
file name alone, as a STEP file (``.step`` or ``.stp``) beside a VRML one, as
KiCad's libraries ship both. Only STEP is read.

A part's height is the highest point of its model above the board: the
model's points, scaled, turned and raised by the offset, at most one 0.01 mm
chord short of a curved surface, so that much is added. A model turned about
X or Y is turned by an assumed convention, right-handed, X then Y then Z, not
yet checked against KiCad, so the part is listed for review. A turn about Z
does not change a height. A hidden model is skipped; a part any of whose
models is not found gets no model height, since the one missing may be its
tallest. KiCad 5's ``(at (xyz ...))``, in inches, is read where ``offset`` is
not given.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import cadquery as cq
import numpy as np

from zcad_core.hardware.electronics import kicad_sexp
from zcad_core.hardware.electronics.board_import import load_solids
from zcad_core.hardware.electronics.kicad_heights import Height
from zcad_core.hardware.electronics.kicad_sexp import Node

# A curved surface is tessellated to this chord error, which is added back.
MODEL_CHORD_MM = 0.01
STEP_SUFFIXES = (".step", ".stp", ".STEP", ".STP")
INCH_MM = 25.4
# How a height from a model is marked, against a heights file's key.
MODEL_HEIGHT = "--models"
Triple = tuple[float, float, float]


@dataclass(frozen=True)
class ModelRef:
    """A footprint's model: the path it names and how it sits."""

    path: str
    offset_mm: Triple = (0.0, 0.0, 0.0)
    scale: Triple = (1.0, 1.0, 1.0)
    rotate: Triple = (0.0, 0.0, 0.0)


def _xyz(model: Node, token: str) -> Triple | None:
    form = kicad_sexp.child(model, token)
    xyz = kicad_sexp.child(form, "xyz") if form is not None else None

    if xyz is None:
        return None

    x, y, z = kicad_sexp.numbers(xyz, 3)

    return (x, y, z)


def _hidden(model: Node) -> bool:
    hide = kicad_sexp.child(model, "hide")

    return "hide" in model[2:] or (
        hide is not None and (len(hide) < 2 or hide[1] == "yes")
    )


def model_refs(footprint: Node) -> tuple[ModelRef, ...]:
    """The footprint's models that are shown, as it names them."""

    found = []

    for model in kicad_sexp.children(footprint, "model"):
        if len(model) < 2 or _hidden(model):
            continue

        offset = _xyz(model, "offset")

        if offset is None:
            inches = _xyz(model, "at") or (0.0, 0.0, 0.0)
            offset = (inches[0] * INCH_MM, inches[1] * INCH_MM, inches[2] * INCH_MM)

        found.append(
            ModelRef(
                path=str(model[1]),
                offset_mm=offset,
                scale=_xyz(model, "scale") or (1.0, 1.0, 1.0),
                rotate=_xyz(model, "rotate") or (0.0, 0.0, 0.0),
            )
        )

    return tuple(found)


def _turned_off_level(rotate: Triple) -> bool:
    return any(angle % 360 != 0 for angle in rotate[:2])


def _rotation(rotate: Triple) -> np.ndarray:
    """Right-handed turns about X, then Y, then Z: the assumed convention."""

    ax, ay, az = (math.radians(angle) for angle in rotate)
    rx = np.array(
        [[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]]
    )
    ry = np.array(
        [[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]]
    )
    rz = np.array(
        [[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]]
    )

    return rz @ ry @ rx


@dataclass
class ModelHeights:
    """The models under one directory, read once each."""

    directory: Path
    not_found: list[dict[str, str]] = field(default_factory=list)
    _points: dict[Path, np.ndarray] = field(default_factory=dict)
    _sha: dict[Path, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.directory.is_dir():
            raise ValueError(f"--models {self.directory} is not a directory")

    def locate(self, path: str) -> Path | None:
        """The STEP file a model path names, under the directory."""

        relative = re.sub(r"^\$[{(][^})]*[})][/\\]?", "", path).replace("\\", "/")
        root = self.directory.resolve()

        for candidate in (PurePosixPath(relative), PurePosixPath(relative).name):
            base = PurePosixPath(candidate)
            names = [base] if base.suffix.lower() in (".step", ".stp") else []
            names += [base.with_suffix(suffix) for suffix in STEP_SUFFIXES]

            for name in names:
                found = (root / name).resolve()

                if found.is_relative_to(root) and found.is_file():
                    return found

        return None

    def _model_points(self, path: Path) -> np.ndarray | None:
        if path not in self._points:
            try:
                solids = load_solids(path)
            except ValueError:
                solids = []

            if not solids:
                return None

            vertices, _ = cq.Compound.makeCompound(solids).tessellate(MODEL_CHORD_MM)
            self._points[path] = np.array([v.toTuple() for v in vertices])
            self._sha[path] = hashlib.sha256(path.read_bytes()).hexdigest()

        return self._points[path]

    def _top(self, path: Path, model: ModelRef) -> float | None:
        points = self._model_points(path)

        if points is None:
            return None

        placed = (points * np.array(model.scale)) @ _rotation(model.rotate).T

        return float(placed[:, 2].max()) + model.offset_mm[2] + MODEL_CHORD_MM

    def _miss(self, reference: str, model: str, why: str) -> None:
        self.not_found.append({"reference": reference, "model": model, "why": why})

    def height(
        self, reference: str, models: tuple[ModelRef, ...], unverified: list[str]
    ) -> Height | None:
        """The part's height from its models, or ``None`` with why noted."""

        tops: list[tuple[float, Path]] = []

        for model in models:
            path = self.locate(model.path)

            if path is None:
                self._miss(reference, model.path, "no STEP file for it under --models")

                return None

            top = self._top(path, model)

            if top is None:
                self._miss(reference, model.path, "the STEP file holds no solids")

                return None

            tops.append((top, path))

        if not tops:
            return None

        top, path = max(tops)

        if top <= MODEL_CHORD_MM:
            self._miss(
                reference, str(path), "the model reaches no higher than the board"
            )

            return None

        if any(_turned_off_level(model.rotate) for model in models):
            turns = next(m.rotate for m in models if _turned_off_level(m.rotate))
            unverified.append(
                f"{reference}: its 3D model turned {turns[0]:g} about X and "
                f"{turns[1]:g} about Y"
            )

        name = path.relative_to(self.directory.resolve()).as_posix()

        return Height(
            round(top, 3), f"3D model {name}, SHA-256 {self._sha[path]}", MODEL_HEIGHT
        )
