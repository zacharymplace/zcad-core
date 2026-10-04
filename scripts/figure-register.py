#!/usr/bin/env python3
"""Update or check the register of figures taken on trust.

    scripts/figure-register.py            check: exit 1 if the register or the
                                          page is out of date with the source
    scripts/figure-register.py --update   add each new constant as 'unstated',
                                          drop entries for constants that are
                                          gone, and rewrite the page

The register is docs/figures/register.json and the page is
docs/reference/figures.md, which is generated and not edited. Moving a figure
out of 'unstated' is an edit to the register, with its source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The checkout's own source, not whichever copy is installed.
sys.path.insert(0, str(ROOT / "src"))

from zcad_core import figures

REGISTER = ROOT / "docs/figures/register.json"
PAGE = ROOT / "docs/reference/figures.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    found = figures.scan()
    register = figures.load(REGISTER) if REGISTER.exists() else {}
    review = figures.load_review(REGISTER) if REGISTER.exists() else ""

    if args.update:
        merged = figures.updated(register, found)

        for key in sorted(set(register) - set(merged)):
            print(
                f"dropped {key}: no such constant any more (renamed? carry its status over)"
            )

        for key in sorted(set(merged) - set(register)):
            print(f"added {key} as unstated")

        REGISTER.parent.mkdir(parents=True, exist_ok=True)
        REGISTER.write_text(figures.dump(merged, review), encoding="utf-8")
        page = figures.render(merged, found, figures.catalogue_items(), review)
        PAGE.write_text(page, encoding="utf-8")
        counts = figures.summary(merged)
        print(
            f"{len(merged)} figures: "
            + ", ".join(f"{counts.get(s, 0)} {s}" for s in figures.STATUSES)
        )

        return 0

    issues = figures.problems(register, found)

    if register and not issues:
        expected = figures.render(register, found, figures.catalogue_items(), review)

        if not PAGE.exists() or PAGE.read_text(encoding="utf-8") != expected:
            issues.append(
                f"{PAGE.relative_to(ROOT)} is out of date: run scripts/figure-register.py --update"
            )

    for issue in issues:
        print(issue)

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
