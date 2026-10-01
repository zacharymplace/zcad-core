"""A lumped steady-state temperature estimate for a closed enclosure.

The heat a box sheds is its outer surface times a combined convection and
radiation coefficient times the rise over ambient, so the rise is the power
over that product. For still air around a plastic box the coefficient is
roughly 8 to 10 W/m2K; the estimate uses 8, the pessimistic end.

**This is an estimate, not a simulation.** It ignores conduction into the
plastic and into whatever the box stands on, hot spots, and air moving past
the box, and it counts no vents. Expect it to be off by half either way; a
thermocouple on a printed box is the only real answer.

Each part's power comes from the catalog, with its source. A part with no
figure is unknown, never zero, so an estimate with one is a lower bound on the
temperature: it can prove a box too hot and never that it is cool enough.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from zcad_core.hardware.thermal import PowerFigure, get_power_figure

CONVECTION_W_M2K = 8.0
DEFAULT_AMBIENT_C = 25.0
# Continuous air temperature for PETG: a design value, well under the 70 to 80
# C at which it softens. The material profile's ``max_service_c`` overrides it.
DEFAULT_SERVICE_LIMIT_C = 60.0
# A warning above this fraction of the limit, in degrees C.
WARN_FRACTION = 0.85

ThermalStatus = Literal["ok", "warn", "fail", "unavailable"]


@dataclass(frozen=True)
class ThermalEstimate:
    """The estimate, and what it rests on."""

    ambient_c: float
    limit_c: float
    coefficient_w_m2k: float
    surface_m2: float
    # What the catalog and the declared power add up to.
    typical_w: float
    peak_w: float
    declared_w: float
    # Parts with no figure at all, and parts with a typical one but no peak,
    # whose typical figure stands in for their peak.
    missing: tuple[str, ...]
    missing_peak: tuple[str, ...]
    sources: tuple[str, ...]
    # Whether the box has no vent, fan, or lid slot, so that a measured
    # temperature calibrates the passive coefficient and nothing else.
    closed: bool = True
    # Where the coefficient came from, when a pooled profile of measured
    # trials set it instead of the default.
    coefficient_source: str = "the default, an assumption"

    @property
    def conductance_w_k(self) -> float:
        return self.coefficient_w_m2k * self.surface_m2

    @property
    def rise_typical_c(self) -> float:
        return self.typical_w / self.conductance_w_k

    @property
    def rise_peak_c(self) -> float:
        return self.peak_w / self.conductance_w_k

    @property
    def temperature_typical_c(self) -> float:
        return self.ambient_c + self.rise_typical_c

    @property
    def temperature_peak_c(self) -> float:
        return self.ambient_c + self.rise_peak_c

    @property
    def complete(self) -> bool:
        """Whether every part has both a typical and a peak figure, so this is
        an estimate and not a lower bound."""

        return not self.missing and not self.missing_peak

    @property
    def status(self) -> ThermalStatus:
        if self.peak_w <= 0:
            return "unavailable"

        temperature = self.temperature_peak_c

        if temperature > self.limit_c:
            return "fail"

        if temperature >= WARN_FRACTION * self.limit_c:
            return "warn"

        return "ok"

    def message(self) -> str:
        bound = "" if self.complete else "at least "
        text = (
            f"estimated air temperature {bound}{self.temperature_peak_c:.0f} C "
            f"({bound}{self.rise_peak_c:.0f} C over a {self.ambient_c:.0f} C "
            f"room) against a {self.limit_c:.0f} C limit"
        )

        if self.missing:
            text += f"; no power figure for {', '.join(self.missing)}"

        if self.missing_peak:
            text += (
                f"; no peak figure for {', '.join(self.missing_peak)}, whose "
                "typical figure stands in"
            )

        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "complete": self.complete,
            "ambient_c": self.ambient_c,
            "limit_c": self.limit_c,
            "typical_w": round(self.typical_w, 3),
            "peak_w": round(self.peak_w, 3),
            "declared_w": self.declared_w,
            "rise_typical_c": round(self.rise_typical_c, 1),
            "rise_peak_c": round(self.rise_peak_c, 1),
            "temperature_peak_c": round(self.temperature_peak_c, 1),
            "surface_m2": round(self.surface_m2, 4),
            "coefficient_w_m2k": self.coefficient_w_m2k,
            "coefficient_source": self.coefficient_source,
            "closed": self.closed,
            "missing": list(self.missing),
            "peak_uses_typical_for": list(self.missing_peak),
            "sources": list(self.sources),
            "note": (
                "An estimate from a lumped balance, not a simulation; it counts "
                "no vents or fan airflow, and "
                + (
                    "is off by half either way."
                    if self.coefficient_source.startswith("the default")
                    else "uses a coefficient measured on printed boxes, which "
                    "covers this box only if it is like theirs."
                )
            ),
        }


def surface_m2(outer_size_mm: tuple[float, float, float]) -> float:
    """The outer surface of a box, in square metres."""

    width, depth, height = outer_size_mm

    return 2 * (width * depth + width * height + depth * height) / 1e6


def estimate_thermal(
    parts: Sequence[str],
    *,
    outer_size_mm: tuple[float, float, float],
    declared_power_w: float = 0.0,
    ambient_c: float = DEFAULT_AMBIENT_C,
    limit_c: float = DEFAULT_SERVICE_LIMIT_C,
    coefficient_w_m2k: float = CONVECTION_W_M2K,
    closed: bool = True,
    coefficient_source: str = "the default, an assumption",
    figures: Mapping[str, PowerFigure] | None = None,
) -> ThermalEstimate:
    """Estimate a closed box built around ``parts``, which are catalogue
    identifiers, plus ``declared_power_w`` for anything the catalog lacks.
    ``figures`` supply a part's power where the catalog has none, such as a
    board from a file."""

    if declared_power_w < 0:
        raise ValueError("declared_power_w must not be negative")

    if limit_c <= ambient_c:
        raise ValueError("The service limit must be above the ambient temperature")

    typical = declared_power_w
    peak = declared_power_w
    missing: list[str] = []
    missing_peak: list[str] = []
    sources: list[str] = []

    for part in parts:
        figure = (figures or {}).get(part) or get_power_figure(part)

        if figure is None:
            missing.append(part)
            continue

        typical += figure.typical_w
        peak += figure.peak_w if figure.peak_w is not None else figure.typical_w

        if figure.peak_w is None:
            missing_peak.append(part)

        described = (
            f"{part}: typical {figure.typical_w:g} W"
            + (f", peak {figure.peak_w:g} W" if figure.peak_w is not None else "")
            + f" - {figure.source.describe()}"
        )

        if described not in sources:
            sources.append(described)

    return ThermalEstimate(
        ambient_c=ambient_c,
        limit_c=limit_c,
        coefficient_w_m2k=coefficient_w_m2k,
        surface_m2=surface_m2(outer_size_mm),
        typical_w=typical,
        peak_w=peak,
        declared_w=declared_power_w,
        missing=tuple(dict.fromkeys(missing)),
        missing_peak=tuple(dict.fromkeys(missing_peak)),
        sources=tuple(sources),
        closed=closed,
        coefficient_source=coefficient_source,
    )


def require_not_too_hot(estimate: ThermalEstimate, *, allow_hot: bool) -> None:
    """Refuse a box estimated past the material's limit, unless told not to."""

    if estimate.status != "fail" or allow_hot:
        return

    raise ValueError(
        f"The {estimate.message()}. This is an estimate, off by half either "
        "way, and it credits no vents: lower the declared power, or pass "
        "allow_hot / --allow-hot if you have measured and know better"
    )
