"""A register of the figures the engine takes on trust.

The engine states no strength, holding force or load claim, and a figure it
did not measure or read must not look like one it did. Most of its figures are
module-level constants: a margin, a clearance, a limit. This module finds every
one by reading the source (not by importing it), and checks each against a
register file that says where its value came from:

- ``sourced``: from a named standard, datasheet or format, with the source
  given. The source is as the code cites it; the register does not re-check it.
- ``design_default``: the engine's own choice, which the code itself says is a
  default, a design value or a guess, and that a trial or the user may replace.
- ``example``: an illustrative figure, not claimed right for any real part.
- ``unstated``: no basis is stated. This is where a figure starts, so a new
  constant is never silently taken to be sourced.

A constant with no entry, or an entry for one that is gone, fails the register
check, so no figure is added without being recorded, and a rename cannot leave
a stale claim behind. Only module-level numeric constants are covered: a
default inside a function or a dataclass, and a number in a data file, are not.
The catalogued hardware (fans, bushings, pogo pins) already says which of its
figures are unverified, and the register lists those from the catalogues.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
STATUSES = ("sourced", "design_default", "example", "unstated")
STATUS_MEANING = {
    "sourced": "From a named standard, datasheet or format (the source is as the code cites it; not re-checked)",
    "design_default": "The engine's own choice, which the code says is a default, a design value or a guess",
    "example": "An illustrative figure, not claimed right for any real part",
    "unstated": "No basis is stated in the code",
}
SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class Figure:
    """A module-level numeric constant."""

    key: str
    path: str
    line: int
    name: str
    value: str
    comment: str


def _numeric(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int | float) and not isinstance(node.value, bool)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _numeric(node.operand)

    if isinstance(node, ast.Tuple | ast.List):
        return bool(node.elts) and all(_numeric(item) for item in node.elts)

    if isinstance(node, ast.BinOp):
        return _numeric(node.left) and _numeric(node.right)

    return False


def _comment_above(lines: list[str], line: int) -> str:
    block: list[str] = []
    index = line - 2

    while index >= 0 and lines[index].strip().startswith("#"):
        block.insert(0, lines[index].strip().lstrip("#").strip())
        index -= 1

    return " ".join(block)


def scan(package: Path = PACKAGE) -> list[Figure]:
    """Every module-level numeric constant (an upper-case name) in the package."""

    found = []

    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        relative = path.relative_to(package).as_posix()

        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue

            if not _numeric(value):
                continue

            for target in targets:
                if isinstance(target, ast.Name) and target.id.lstrip("_").isupper():
                    found.append(
                        Figure(
                            key=f"{relative}:{target.id}",
                            path=relative,
                            line=node.lineno,
                            name=target.id,
                            value=ast.unparse(value),
                            comment=_comment_above(lines, node.lineno),
                        )
                    )

    return found


def load(path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path} is not figure register version {SCHEMA_VERSION}")

    figures: dict[str, dict[str, str]] = data["figures"]

    return figures


def problems(register: dict[str, dict[str, str]], figures: list[Figure]) -> list[str]:
    """What is wrong between the register and the source: an empty list when
    every constant is recorded, every entry names one, and each is well formed."""

    found = {figure.key for figure in figures}
    issues = []

    for key in sorted(found - set(register)):
        issues.append(
            f"{key} is not in the register: add it (as unstated if its basis is not known)"
        )

    for key in sorted(set(register) - found):
        issues.append(
            f"{key} is in the register but no such constant exists: remove or rename it"
        )

    for key, entry in sorted(register.items()):
        status = entry.get("status")

        if status not in STATUSES:
            issues.append(
                f"{key} has status {status!r}, not one of {', '.join(STATUSES)}"
            )
        elif status == "sourced" and not entry.get("source", "").strip():
            issues.append(f"{key} is sourced but gives no source")
        elif status == "example" and not entry.get("source", "").strip():
            issues.append(f"{key} is an example but says nothing of where it is from")

    return issues


def updated(
    register: dict[str, dict[str, str]], figures: list[Figure]
) -> dict[str, dict[str, str]]:
    """The register with each missing constant added as ``unstated`` and each
    entry for a missing one dropped; every entry kept as it was."""

    keys = {figure.key for figure in figures}
    merged = {key: entry for key, entry in register.items() if key in keys}

    for figure in figures:
        merged.setdefault(figure.key, {"status": "unstated"})

    return dict(sorted(merged.items()))


def dump(register: dict[str, dict[str, str]]) -> str:
    return (
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "statuses": STATUS_MEANING,
                "figures": register,
            },
            indent=2,
        )
        + "\n"
    )


def catalogue_items() -> list[dict[str, Any]]:
    """The catalogued hardware, with the figures each says are unverified."""

    # Imported here: the register reads source files and needs no hardware module
    # to scan them.
    from zcad_core.hardware.bushings import get_bushing, list_bushings
    from zcad_core.hardware.fans import get_fan, list_fans
    from zcad_core.hardware.pogo import get_pogo_pin, list_pogo_pins

    items = []

    for kind, names, get in (
        ("fan", list_fans(), get_fan),
        ("bushing", list_bushings(), get_bushing),
        ("pogo pin", list_pogo_pins(), get_pogo_pin),
    ):
        for name in names:
            source = get(name).source
            items.append(
                {
                    "kind": kind,
                    "identifier": name,
                    "document_read": bool(source.read),
                    "unverified": list(source.unverified),
                    "source": source.title,
                }
            )

    return items


def summary(register: dict[str, dict[str, str]]) -> Counter[str]:
    return Counter(entry.get("status", "?") for entry in register.values())


def render(
    register: dict[str, dict[str, str]],
    figures: list[Figure],
    catalogue: list[dict[str, Any]],
) -> str:
    """The register as a docs page."""

    by_key = {figure.key: figure for figure in figures}
    counts = summary(register)
    lines = [
        "<!-- Generated by scripts/figure-register.py from docs/figures/register.json; do not edit. -->",
        "",
        "# Figures taken on trust",
        "",
        (
            "The engine states no strength, holding force or load claim, and a figure it "
            "did not measure or read must not look like one it did. This page lists every "
            "module-level numeric constant in the engine and where its value is said to "
            "come from, and the catalogued hardware figures that are not verified."
        ),
        "",
        (
            "**Scope.** Module-level numeric constants only. A default inside a function "
            "or a dataclass, and a number in a data file, are not covered. A status is "
            "only as good as what the code says: a `sourced` figure is as the code cites "
            "it and has not been re-checked against the standard. An `unstated` figure is "
            "not wrong; it has no basis written down. Adding a constant without recording "
            "it fails the test suite."
        ),
        "",
        f"## The {len(register)} constants",
        "",
        "| Status | Count | Meaning |",
        "| --- | ---: | --- |",
    ]

    for status in STATUSES:
        lines.append(
            f"| `{status}` | {counts.get(status, 0)} | {STATUS_MEANING[status]} |"
        )

    for status in ("sourced", "design_default", "example"):
        rows = sorted(
            key for key, entry in register.items() if entry.get("status") == status
        )

        if not rows:
            continue

        lines += ["", f"## {status.replace('_', ' ').capitalize()}", ""]
        lines += ["| Constant | Value | Basis |", "| --- | --- | --- |"]

        for key in rows:
            figure = by_key[key]
            entry = register[key]
            basis = entry.get("source") or entry.get("note") or figure.comment
            lines.append(f"| `{key}` | `{_cell(figure.value)}` | {_cell(basis)} |")

    lines += ["", "## Catalogued hardware", ""]
    lines += [
        (
            "Each fan, bushing and pogo pin records where its figures came from, whether "
            "the document itself was read, and which figures no document read supports."
        ),
        "",
        "| Item | Kind | Document read | Unverified figures |",
        "| --- | --- | --- | --- |",
    ]

    for item in sorted(catalogue, key=lambda i: (i["kind"], i["identifier"])):
        unverified = ", ".join(item["unverified"]) or "none listed"
        read = "yes" if item["document_read"] else "no (search excerpt)"
        lines.append(
            f"| `{item['identifier']}` | {item['kind']} | {read} | {unverified} |"
        )

    unstated = sorted(
        key for key, entry in register.items() if entry.get("status") == "unstated"
    )
    lines += ["", f"## Unstated ({len(unstated)})", ""]
    lines += [
        (
            "No basis is written down for these. Moving one out of this list means "
            "finding where its value came from, or saying it is the engine's own choice, "
            "in `docs/figures/register.json`."
        ),
        "",
    ]
    current = ""

    for key in unstated:
        figure = by_key[key]

        if figure.path != current:
            current = figure.path
            lines += ["", f"**`{current}`**", ""]

        lines.append(f"- `{figure.name}` = `{_cell(figure.value)}`")

    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())
