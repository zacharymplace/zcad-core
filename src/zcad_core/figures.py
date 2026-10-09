"""A register of the figures the engine takes on trust.

The engine states no strength, holding force or load claim, and a figure it
did not measure or read must not look like one it did. This module finds every
figure by reading the source (not by importing it), and checks each against a
register file that says where its value came from. A figure is:

- a module-level numeric constant: a margin, a clearance, a limit;
- the numeric default of a dataclass field, such as a board's width or a
  policy's wall thickness;
- the numeric default of a function or method parameter.

A default of zero is the absence of a figure (no offset, none) and is not
listed. The statuses are:

- ``sourced``: from a named standard, datasheet or format, with the source
  given. The source is as the code cites it; the register does not re-check it.
- ``estimated``: read off a drawing's scale, or a stated rough estimate: from a
  named source that does not state it outright, as the code says.
- ``measured``: the engine's own default until a build applies a joint profile
  that measured it (:mod:`zcad_core.profiles.joints`); the entry's ``measures``
  names the profile's figure.
- ``design_default``: the engine's own choice, which the code itself says is a
  default, a design value or a guess, and that a trial or the user may replace.
- ``example``: an illustrative figure, not claimed right for any real part.
- ``unstated``: no basis is stated. This is where a figure starts, so a new
  figure is never silently taken to be sourced.

A figure with no entry, or an entry for one that is gone, fails the register
check, so no figure is added without being recorded, and a rename cannot leave
a stale claim behind. Not covered: a number inside a function body, a default
given by ``field(...)`` or a factory, a class attribute of a class that is not
a dataclass, a keyword argument at a call (a module-level instance such as a
display's), and a number in a data file. The catalogued hardware (fans,
bushings, pogo pins) already says which of its figures are unverified, and the
register lists those from the catalogues.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
STATUSES = ("sourced", "estimated", "measured", "design_default", "example", "unstated")
STATUS_MEANING = {
    "sourced": "From a named standard, datasheet or format (the source is as the code cites it; not re-checked)",
    "estimated": "Read off a drawing's scale or a stated rough estimate: the source does not state it outright",
    "measured": "The engine's default until a build applies a joint profile that measured it",
    "design_default": "The engine's own choice, which the code says is a default, a design value or a guess",
    "example": "An illustrative figure, not claimed right for any real part",
    "unstated": "No basis is stated in the code",
}
# Statuses that must say where the figure is from.
NEEDS_SOURCE = ("sourced", "estimated", "example")
SCHEMA_VERSION = "1.1.0"


@dataclass(frozen=True)
class Figure:
    """A numeric constant, field default or parameter default."""

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


def _zero(node: ast.AST) -> bool:
    """A default that is all zeros: no offset, none."""

    if isinstance(node, ast.Constant):
        return bool(node.value == 0)

    if isinstance(node, ast.UnaryOp):
        return _zero(node.operand)

    if isinstance(node, ast.Tuple | ast.List):
        return all(_zero(item) for item in node.elts)

    return False


def _comment_above(lines: list[str], line: int) -> str:
    block: list[str] = []
    index = line - 2

    while index >= 0 and lines[index].strip().startswith("#"):
        block.insert(0, lines[index].strip().lstrip("#").strip())
        index -= 1

    return " ".join(block)


def _figure(
    relative: str, name: str, node: ast.AST, value: ast.AST, lines: list[str]
) -> Figure:
    line = getattr(node, "lineno", 0)

    return Figure(
        key=f"{relative}:{name}",
        path=relative,
        line=line,
        name=name,
        value=ast.unparse(value),
        comment=_comment_above(lines, line),
    )


def _constants(tree: ast.Module, lines: list[str], relative: str) -> list[Figure]:
    found = []

    for node in tree.body:
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
                found.append(_figure(relative, target.id, node, value, lines))

    return found


def _is_dataclass(node: ast.ClassDef) -> bool:
    return any(
        ast.unparse(decorator).split("(")[0] in ("dataclass", "dataclasses.dataclass")
        for decorator in node.decorator_list
    )


def _field_figures(
    cls: ast.ClassDef, scope: list[str], lines: list[str], relative: str
) -> list[Figure]:
    found = []

    for item in cls.body:
        if (
            isinstance(item, ast.AnnAssign)
            and item.value is not None
            and isinstance(item.target, ast.Name)
            and _numeric(item.value)
            and not _zero(item.value)
        ):
            name = ".".join([*scope, cls.name, item.target.id])
            found.append(_figure(relative, name, item, item.value, lines))

    return found


def _parameter_figures(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    scope: list[str],
    lines: list[str],
    relative: str,
) -> list[Figure]:
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    pairs = list(
        zip(
            positional[len(positional) - len(arguments.defaults) :],
            arguments.defaults,
            strict=True,
        )
    )
    pairs += [
        (argument, default)
        for argument, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        )
        if default is not None
    ]
    qualified = ".".join([*scope, function.name])

    return [
        _figure(relative, f"{qualified}({argument.arg})", default, default, lines)
        for argument, default in pairs
        if _numeric(default) and not _zero(default)
    ]


def _defaults(
    node: ast.AST, scope: list[str], lines: list[str], relative: str
) -> list[Figure]:
    found = []

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            if _is_dataclass(child):
                found += _field_figures(child, scope, lines, relative)

            found += _defaults(child, [*scope, child.name], lines, relative)
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            found += _parameter_figures(child, scope, lines, relative)
            found += _defaults(child, [*scope, child.name], lines, relative)
        else:
            found += _defaults(child, scope, lines, relative)

    return found


def scan(package: Path = PACKAGE) -> list[Figure]:
    """Every figure in the package: module-level numeric constants, and the
    non-zero numeric defaults of dataclass fields and function parameters."""

    found = []

    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(text)
        found += _constants(tree, lines, relative)
        found += _defaults(tree, [], lines, relative)

    return found


def load(path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path} is not figure register version {SCHEMA_VERSION}")

    figures: dict[str, dict[str, str]] = data["figures"]

    return figures


def load_review(path: Path) -> str:
    """What the last review for a stated basis did and found, in the register
    file's own words, or an empty string when none is recorded."""

    return str(json.loads(path.read_text(encoding="utf-8")).get("review", ""))


def problems(register: dict[str, dict[str, str]], figures: list[Figure]) -> list[str]:
    """What is wrong between the register and the source: an empty list when
    every figure is recorded, every entry names one, and each is well formed."""

    found = {figure.key for figure in figures}
    issues = []

    for key in sorted(found - set(register)):
        issues.append(
            f"{key} is not in the register: add it (as unstated if its basis is not known)"
        )

    for key in sorted(set(register) - found):
        issues.append(
            f"{key} is in the register but no such figure exists: remove or rename it"
        )

    for key, entry in sorted(register.items()):
        status = entry.get("status")

        if status not in STATUSES:
            issues.append(
                f"{key} has status {status!r}, not one of {', '.join(STATUSES)}"
            )
        elif status in NEEDS_SOURCE and not entry.get("source", "").strip():
            issues.append(f"{key} is {status} but says nothing of where it is from")
        elif status == "measured" and not entry.get("measures", "").strip():
            issues.append(f"{key} is measured but names no joint profile figure")

    return issues


def updated(
    register: dict[str, dict[str, str]], figures: list[Figure]
) -> dict[str, dict[str, str]]:
    """The register with each missing figure added as ``unstated`` and each
    entry for a missing one dropped; every entry kept as it was."""

    keys = {figure.key for figure in figures}
    merged = {key: entry for key, entry in register.items() if key in keys}

    for figure in figures:
        merged.setdefault(figure.key, {"status": "unstated"})

    return dict(sorted(merged.items()))


def dump(register: dict[str, dict[str, str]], review: str = "") -> str:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "statuses": STATUS_MEANING,
    }

    if review:
        payload["review"] = review

    payload["figures"] = register

    return json.dumps(payload, indent=2) + "\n"


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
    review: str = "",
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
            "numeric constant, dataclass field default and function parameter default in "
            "the engine, and where its value is said to come from, and the catalogued "
            "hardware figures that are not verified."
        ),
        "",
        (
            "**Scope.** Module-level numeric constants, and the non-zero numeric "
            "defaults of dataclass fields and function parameters. A default of zero "
            "(no offset, none) is not a figure and is not listed. Not covered: a number "
            "inside a function body, a default given by `field(...)` or a factory, a "
            "keyword argument at a call (so a module-level instance such as a display's "
            "is not listed), and a number in a data file. A status is only as good as "
            "what the code says: a `sourced` figure is as the code cites it and has not "
            "been re-checked against the standard. An `unstated` figure is not wrong; it "
            "has no basis written down. Adding a figure without recording it fails the "
            "test suite."
        ),
        "",
        f"## The {len(register)} figures",
        "",
        "| Status | Count | Meaning |",
        "| --- | ---: | --- |",
    ]

    for status in STATUSES:
        lines.append(
            f"| `{status}` | {counts.get(status, 0)} | {STATUS_MEANING[status]} |"
        )

    for status in ("sourced", "estimated", "measured", "design_default", "example"):
        rows = sorted(
            key for key, entry in register.items() if entry.get("status") == status
        )

        if not rows:
            continue

        lines += ["", f"## {status.replace('_', ' ').capitalize()}", ""]
        lines += ["| Figure | Value | Basis |", "| --- | --- | --- |"]

        for key in rows:
            figure = by_key[key]
            entry = register[key]
            basis = entry.get("source") or entry.get("note") or figure.comment

            if status == "measured":
                basis = (
                    f"{basis} Measured as the joint profile's `{entry['measures']}`."
                )
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
    if review:
        lines += ["", "### Last review for a stated basis", "", review, ""]

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
