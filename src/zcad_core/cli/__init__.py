"""The zcad-validation command: the Validation Lab and the enclosure builders.

Thin argparse wrapper over the already-tested ``zcad_core.retention``
lifecycle functions and the enclosure builder in ``zcad_core.features``. Every command reads and writes explicit file paths;
none of them infer a directory layout beyond what a caller passes in,
except ``status``, ``report``, and ``candidate promote``, which read (never
write) a ``--target-root`` to discover existing candidates, promotions, and
visual reviews (``report`` looks for ``visual-review.json`` beside each
candidate manifest), and
``candidate register``, which writes its export-validation run beside the
candidate manifest in ``export-validation/``; ``candidate derive`` does the
same inside ``--output-directory``. ``enclosure build`` writes only inside
its ``--output-directory``, ``enclosure trial`` only inside the trials
folder beside a build record, and ``enclosure-group build`` and ``viewer`` only
inside their ``--output-directory``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from zcad_core.cli import (
    candidate,
    compensation,
    enclosure,
    enclosure_group,
    fixture,
    review,
    revision,
    status,
    target,
    trial,
)

_COMMAND_GROUPS = (
    target,
    candidate,
    fixture,
    trial,
    review,
    revision,
    status,
    enclosure,
    enclosure_group,
    compensation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zcad-validation",
        description=(
            "Validation Lab fixtures (target, candidate, fixture, trial, review, "
            "revision, status, report) and printable enclosures (enclosure)."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    for group in _COMMAND_GROUPS:
        group.register(subcommands)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.handler(args))
    except (
        ValueError,
        TypeError,
        FileNotFoundError,
        FileExistsError,
        KeyError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
