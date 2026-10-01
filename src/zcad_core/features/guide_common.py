"""What a guide file's checks share: collecting findings, and reading numbers
and sections out of a JSON object."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class Findings:
    """Errors make a file unusable; warnings do not."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []


def number(
    section: Mapping[str, Any],
    name: str,
    where: str,
    findings: Findings,
    *,
    low: float,
    high: float,
    required: bool = True,
) -> float | None:
    """A number in a range, or ``None`` with the problem recorded."""

    value = section.get(name)

    if value is None:
        if required:
            findings.errors.append(f"{where}.{name} is missing")

        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        findings.errors.append(f"{where}.{name} must be a number, not {value!r}")

        return None

    if not low <= value <= high:
        findings.errors.append(
            f"{where}.{name} is {value:g}, outside {low:g} to {high:g}"
        )

        return None

    return float(value)


def section(
    data: Mapping[str, Any], name: str, findings: Findings, *, required: bool = True
) -> Mapping[str, Any] | None:
    """An object in the file, or ``None`` with the problem recorded."""

    value = data.get(name)

    if value is None:
        if required:
            findings.errors.append(f"{name} is missing")

        return None

    if not isinstance(value, Mapping):
        findings.errors.append(f"{name} must be an object")

        return None

    return value
