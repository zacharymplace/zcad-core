"""The retention-geometry generator's version, and a guard that it is bumped.

Every candidate records the generator version that built its geometry, and a
revision may regenerate its parent's policy only under a new version. The
version therefore has to change whenever the code that produces retention
geometry or validation fixtures changes, and never otherwise.

History:

- 1.0.0: corner capture and edge clip
- 1.1.0: ledges and clips fused to their walls, not floating islands
- 1.2.0: capture geometry and fixture base built up from the PCB's underside
- 1.3.0: clearance holes through the base under parts reaching below the PCB
- 1.4.0: edge-clip spans keep ``board_clearance_mm`` from component footprints

When a change to :data:`GENERATOR_MODULES` alters generated geometry, bump
:data:`GENERATOR_VERSION`, add a history line, and update
:data:`GENERATOR_FINGERPRINT`. When it doesn't (a refactor), update only the
fingerprint. The fingerprint ignores comments, docstrings, and formatting.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path

GENERATOR_VERSION = "1.4.0"

GENERATOR_MODULES = (
    "zcad_core.geometry.cadquery_support",
    "zcad_core.geometry.edge_outline",
    "zcad_core.geometry.types",
    "zcad_core.retention.corner_capture",
    "zcad_core.retention.edge_capture",
    "zcad_core.retention.production_board",
    "zcad_core.retention.production_edge_board",
    "zcad_core.retention.production_edge_execution",
    "zcad_core.retention.production_execution",
    "zcad_core.retention.synthetic_backend",
    "zcad_core.retention.synthetic_edge_backend",
    "zcad_core.retention.validation_fixture",
)

# generator_fingerprint() at GENERATOR_VERSION, computed on Python 3.11 (the
# AST it hashes can differ between Python versions).
GENERATOR_FINGERPRINT = (
    "5717419097a55ba94a0f2d2ee0d5d94cbf28870f548b89bafbc873abcd06ce97"
)


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue

        body = node.body

        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]

    return tree


def generator_fingerprint() -> str:
    """SHA-256 over the generator modules' code, ignoring comments,
    docstrings, and formatting."""

    digest = hashlib.sha256()

    for name in GENERATOR_MODULES:
        spec = importlib.util.find_spec(name)

        if spec is None or spec.origin is None:
            raise ModuleNotFoundError(name)

        tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
        digest.update(name.encode())
        digest.update(ast.dump(_without_docstrings(tree)).encode())

    return digest.hexdigest()
