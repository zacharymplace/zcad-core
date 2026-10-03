"""What a board-file check collects, and the readers of a field it checks as it reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class _Findings:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _number(
    section: Any,
    name: str,
    where: str,
    findings: _Findings,
    *,
    low: float | None = None,
    high: float | None = None,
    required: bool = True,
) -> float | None:
    """A number in ``section``, noting any problem; ``None`` when unusable."""

    value = section.get(name) if isinstance(section, Mapping) else None

    if value is None:
        if required:
            findings.error(f"{where}.{name} is missing")

        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        findings.error(f"{where}.{name} must be a number, not {value!r}")

        return None

    number = float(value)

    if low is not None and number < low:
        findings.error(f"{where}.{name} is {number:g}, below the least, {low:g}")

        return None

    if high is not None and number > high:
        findings.error(f"{where}.{name} is {number:g}, above the most, {high:g}")

        return None

    return number


def _edge_length(edge: str, width: float, length: float) -> float:
    """How long an edge is: the one at +Y or -Y runs along X, the board's width."""

    return width if edge.endswith("_y") else length


def _section(
    data: Mapping[str, Any], name: str, findings: _Findings, *, required: bool = True
) -> Mapping[str, Any] | None:
    value = data.get(name)

    if value is None:
        if required:
            findings.error(f"{name} is missing")

        return None

    if not isinstance(value, Mapping):
        findings.error(f"{name} must be an object")

        return None

    return value


def _pair(value: Any, where: str, findings: _Findings) -> tuple[float, float] | None:
    ok = (
        isinstance(value, Sequence)
        and not isinstance(value, str)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    )

    if not ok:
        findings.error(f"{where} must be a pair of numbers [x, y]")

        return None

    return float(value[0]), float(value[1])
