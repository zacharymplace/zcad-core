#!/usr/bin/env python3
"""Write or check constraints.txt, the versions zcad-core is tested with.

    scripts/lock-dependencies.py          write constraints.txt from this
                                          environment
    scripts/lock-dependencies.py --check  exit 1 if this environment has
                                          drifted from constraints.txt

Every package zcad-core[dev,docs] needs, directly or through another, is pinned
at the version installed here, so

    pip install -e ".[dev,docs]" -c constraints.txt

rebuilds the environment the evidence was made with. A package installed by
hand that nothing requires is left out. The pins come from one platform, so
another may need a package this one does not; the check only fails for a
package installed here at a version other than its pin, or not pinned at all.
"""

from __future__ import annotations

import argparse
import platform
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints.txt"
PROJECT_EXTRAS = frozenset({"dev", "docs"})


def project_requirements(extras: frozenset[str]) -> list[str]:
    """The project's own requirements, read from pyproject.toml: the installed
    metadata is only as new as the last `pip install -e`, and may lack an
    extra added since."""

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    optional = project.get("optional-dependencies", {})

    return list(project["dependencies"]) + [
        line for extra in sorted(extras) for line in optional.get(extra, [])
    ]


def needed(extras: frozenset[str]) -> dict[NormalizedName, str]:
    """Every distribution the project needs, by name, at its installed version."""

    versions: dict[NormalizedName, str] = {}
    pending = [
        (Requirement(line).name, frozenset(Requirement(line).extras))
        for line in project_requirements(extras)
    ]
    seen: set[tuple[NormalizedName, frozenset[str]]] = set()

    while pending:
        name, wanted = pending.pop()
        key = (canonicalize_name(name), wanted)

        if key in seen:
            continue

        seen.add(key)

        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError as error:
            raise SystemExit(
                f"lock-dependencies: {name} is needed but not installed; install "
                'with pip install -e ".[dev,docs]" -c constraints.txt'
            ) from error

        versions[key[0]] = distribution.version

        for line in distribution.requires or []:
            requirement = Requirement(line)
            # A marker naming an extra applies only when that extra is asked
            # for; with none asked, it is evaluated against no extra at all.
            applies = requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra})
                for extra in (wanted or {""})
            )

            if applies:
                pending.append((requirement.name, frozenset(requirement.extras)))

    return versions


def render(versions: dict[NormalizedName, str]) -> str:
    header = [
        "# The versions zcad-core is tested with. Written by",
        "# scripts/lock-dependencies.py; do not edit by hand. Install with",
        '#   pip install -e ".[dev,docs]" -c constraints.txt',
        f"# Made with Python {platform.python_version()} on {sys.platform}.",
    ]
    pins = [f"{name}=={version}" for name, version in sorted(versions.items())]

    return "\n".join(header + pins) + "\n"


def pinned(text: str) -> dict[NormalizedName, str]:
    pins: dict[NormalizedName, str] = {}

    for line in text.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        name, _, version = line.partition("==")
        pins[canonicalize_name(name)] = version

    return pins


def drift(
    installed: dict[NormalizedName, str], pins: dict[NormalizedName, str]
) -> list[str]:
    """What differs, one line each: a package unpinned, or pinned at another
    version. A pin for a package not installed here is another platform's."""

    problems = []

    for name, version in sorted(installed.items()):
        if name not in pins:
            problems.append(f"{name} {version} is installed but not pinned")
        elif pins[name] != version:
            problems.append(f"{name} is {version} here but pinned at {pins[name]}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    installed = needed(PROJECT_EXTRAS)

    if not args.check:
        CONSTRAINTS.write_text(render(installed), encoding="utf-8")
        print(f"lock-dependencies: pinned {len(installed)} packages")

        return 0

    problems = drift(installed, pinned(CONSTRAINTS.read_text(encoding="utf-8")))

    if problems:
        print("lock-dependencies: this environment differs from constraints.txt:")
        print("\n".join(f"  {problem}" for problem in problems))
        print(
            "Install the pinned versions, or run scripts/lock-dependencies.py "
            "to pin these."
        )

        return 1

    print(f"lock-dependencies: {len(installed)} packages match constraints.txt")

    return 0


if __name__ == "__main__":
    sys.exit(main())
