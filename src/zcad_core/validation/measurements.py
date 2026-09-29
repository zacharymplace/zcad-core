"""Dimensional measurements of printed parts, shared by every trial record."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_MEASUREMENT_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class PhysicalMeasurement:
    """One dimensional measurement of the printed fixture or fitted board.

    ``nominal_mm`` is the designed value when there is one (for example the
    export-validation vertical play), so the deviation that drives the next
    revision is recorded rather than recomputed from memory.
    """

    name: str
    value_mm: float
    nominal_mm: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not _MEASUREMENT_NAME.fullmatch(self.name):
            raise ValueError(
                f"Measurement name must be lowercase snake_case: {self.name!r}"
            )

        if not math.isfinite(self.value_mm):
            raise ValueError(f"Measurement {self.name} needs a finite value_mm")

        if self.nominal_mm is not None and not math.isfinite(self.nominal_mm):
            raise ValueError(f"Measurement {self.name} has a non-finite nominal_mm")

    @property
    def deviation_mm(self) -> float | None:
        """Measured minus nominal, when a nominal is recorded."""

        return None if self.nominal_mm is None else self.value_mm - self.nominal_mm
