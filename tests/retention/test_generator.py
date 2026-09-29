from __future__ import annotations

import ast
import re
import sys

import pytest

from zcad_core.retention.generator import (
    GENERATOR_FINGERPRINT,
    GENERATOR_VERSION,
    _without_docstrings,
    generator_fingerprint,
)


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 11),
    reason="The fingerprint is defined on Python 3.11, the project's version",
)
def test_generator_code_matches_its_version() -> None:
    assert generator_fingerprint() == GENERATOR_FINGERPRINT, (
        "The retention-geometry generator's code changed. If generated "
        "geometry changes, bump GENERATOR_VERSION and add a history line in "
        "src/zcad_core/retention/generator.py; either way, set "
        f"GENERATOR_FINGERPRINT to {generator_fingerprint()!r}."
    )


def test_version_is_semantic() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", GENERATOR_VERSION)


def test_fingerprint_ignores_comments_docstrings_and_formatting() -> None:
    original = 'def f(x):\n    """Add one."""\n    return x+1  # increment\n'
    reformatted = "def f(x):\n\n    return (x + 1)\n"
    changed = "def f(x):\n    return x + 2\n"

    def dump(source: str) -> str:
        return ast.dump(_without_docstrings(ast.parse(source)))

    assert dump(original) == dump(reformatted)
    assert dump(original) != dump(changed)
