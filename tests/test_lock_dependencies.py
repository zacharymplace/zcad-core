"""constraints.txt pins the environment the tests pass in."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from packaging.utils import canonicalize_name

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lock-dependencies.py"


@pytest.fixture(scope="module")
def lock() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lock_dependencies", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_this_environment_is_the_one_pinned(lock: ModuleType) -> None:
    # A package upgraded, or one added to pyproject.toml, without relocking:
    # the evidence would no longer say which versions made it.
    installed = lock.needed(lock.PROJECT_EXTRAS)
    pins = lock.pinned(lock.CONSTRAINTS.read_text(encoding="utf-8"))

    assert lock.drift(installed, pins) == []


def test_the_pins_follow_pyproject_and_what_it_pulls_in(lock: ModuleType) -> None:
    installed = lock.needed(lock.PROJECT_EXTRAS)

    # Named in pyproject.toml's dev extra, and so needed even before the
    # editable install's metadata catches up.
    assert canonicalize_name("pytest-xdist") in installed
    # Not named anywhere here: CadQuery's geometry kernel, pulled in by it.
    assert canonicalize_name("cadquery-ocp") in installed
    assert canonicalize_name("zcad-core") not in installed


def test_drift_names_what_is_unpinned_or_moved(lock: ModuleType) -> None:
    installed = {
        canonicalize_name("numpy"): "2.4.6",
        canonicalize_name("scipy"): "1.18.0",
        canonicalize_name("vtk"): "9.6.2",
    }
    pins = lock.pinned(
        "# header\n"
        "numpy==2.4.6\n"
        "scipy==1.17.1\n"
        # Another platform's: not installed here, so not a problem.
        "appnope==0.1.4\n"
    )

    assert lock.drift(installed, pins) == [
        "scipy is 1.18.0 here but pinned at 1.17.1",
        "vtk 9.6.2 is installed but not pinned",
    ]


def test_every_pin_is_exact(lock: ModuleType) -> None:
    lines = [
        line
        for line in lock.CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    names = [line.partition("==")[0] for line in lines]

    assert names == sorted(names)
    assert all(line.count("==") == 1 for line in lines)
