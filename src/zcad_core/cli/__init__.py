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
inside their ``--output-directory``. ``slice check`` only reads.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from zcad_core.cli import (
    board,
    candidate,
    compensation,
    coupon,
    enclosure,
    enclosure_group,
    fixture,
    guide,
    housing,
    jig,
    nest,
    review,
    revision,
    slice_check,
    stack,
    status,
    target,
    thermal,
    trial,
    wearable,
)

_COMMAND_GROUPS = (
    target,
    board,
    guide,
    housing,
    candidate,
    fixture,
    trial,
    review,
    revision,
    status,
    enclosure,
    enclosure_group,
    compensation,
    coupon,
    thermal,
    slice_check,
    wearable,
    stack,
    nest,
    jig,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zcad-validation",
        description=(
            "Validation Lab fixtures (target, candidate, fixture, trial, review, "
            "revision, status, report), printable enclosures (enclosure), and "
            "slice checks (slice)."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    for group in _COMMAND_GROUPS:
        group.register(subcommands)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # A slice records the command that built it, so it can be built again.
    args.argv = list(sys.argv[1:] if argv is None else argv)

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
