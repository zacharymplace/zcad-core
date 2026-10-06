"""The heights file a KiCad import takes with ``--heights``.

A KiCad PCB has no part heights, so the user gives them: a JSON object whose
keys are a reference (``J1``), a footprint's library name
(``Connector_USB:USB_C_Receptacle_GCT_USB4105``) or a pattern over either
(``C*``, ``Capacitor_SMD:*``), each mapping to ``{"height_mm": H, "source":
"datasheet, p. 4"}``. A reference wins over a library name, which wins over a
pattern; patterns are tried in the file's order. A height with no source is a
guess, and is refused.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The board file's own bounds on a part's height.
HEIGHT_RANGE_MM = (0.05, 200.0)
PATTERN_CHARACTERS = "*?["


@dataclass(frozen=True)
class Height:
    """A part's height and where the figure came from."""

    mm: float
    source: str
    given_by: str


@dataclass(frozen=True)
class Heights:
    """The entries of a heights file, by kind."""

    name: str
    sha256: str
    exact: Mapping[str, Height]
    patterns: tuple[tuple[str, Height], ...]

    def find(self, reference: str, library: str) -> Height | None:
        for key in (reference, library):
            if key in self.exact:
                return self.exact[key]

        for pattern, height in self.patterns:
            if fnmatch.fnmatchcase(reference, pattern) or fnmatch.fnmatchcase(
                library, pattern
            ):
                return height

        return None

    def unused(self, used: set[str]) -> list[str]:
        keys = [*self.exact, *(pattern for pattern, _ in self.patterns)]

        return [key for key in keys if key not in used]


def _entry(key: str, value: Any, name: str) -> Height:
    where = f"{name}: {key!r}"

    if not isinstance(value, Mapping):
        raise TypeError(f"{where} must be an object with height_mm and source")

    unknown = sorted(set(value) - {"height_mm", "source"})

    if unknown:
        raise ValueError(f"{where} has no {', '.join(unknown)}")

    height = value.get("height_mm")
    source = value.get("source")
    low, high = HEIGHT_RANGE_MM

    if isinstance(height, bool) or not isinstance(height, int | float):
        raise TypeError(f"{where} needs height_mm, a number of millimetres")

    if not low <= height <= high:
        raise ValueError(f"{where}: height_mm must be {low:g} to {high:g} mm")

    if not isinstance(source, str) or not source.strip():
        raise ValueError(
            f"{where} needs a source saying where the height came from: a height "
            "with no source is a guess"
        )

    return Height(float(height), source.strip(), key)


def read_heights(path: Path) -> Heights:
    raw = path.read_bytes()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path.name} is not JSON: {error}") from error

    if not isinstance(data, Mapping) or not data:
        raise ValueError(
            f"{path.name} must be a JSON object of reference, library name or "
            'pattern to {"height_mm": H, "source": "..."}'
        )

    exact: dict[str, Height] = {}
    patterns: list[tuple[str, Height]] = []

    for key, value in data.items():
        height = _entry(key, value, path.name)

        if any(character in key for character in PATTERN_CHARACTERS):
            patterns.append((key, height))
        else:
            exact[key] = height

    return Heights(
        name=path.name,
        sha256=hashlib.sha256(raw).hexdigest(),
        exact=exact,
        patterns=tuple(patterns),
    )
