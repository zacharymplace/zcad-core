"""Build one example of each product not yet built for real, into evidence/examples/.

The z-cadalog shows every design under evidence/, which until a product is built for real leaves
it out. This builds one of each from the example inputs the repository ships (the ``template``
commands' example readings, the KiCad example board, and the test suite's plate as a part), so
the catalog can show what each product makes. The catalog marks everything under
``evidence/examples/`` as an **example**: built from example readings, never a real object, and
never trialled.

A template's example readings carry a guard (``needs_review``, or a source beginning "EXAMPLE")
that every build refuses until a person replaces them. Here the figures stay exactly as the
template wrote them, and each guard is replaced by a source that says so:
``Template example values, unchanged and not measured``. Those inputs are kept beside each build,
under evidence/examples/ and nowhere else.

Each product goes in ``evidence/examples/<product>/``: its inputs, and the build in ``<product>-example/``.
Nothing existing is overwritten: the script refuses if evidence/examples/ exists.

Usage:
    python scripts/build-examples.py [--evidence-root evidence]
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
MARK = "Template example values, unchanged and not measured: "


def _run(*arguments: str) -> dict[str, Any]:
    from zcad_core.cli import main as zcad

    output = StringIO()

    with redirect_stdout(output):
        code = zcad(list(arguments))

    if code != 0:
        raise RuntimeError(f"zcad-validation {' '.join(arguments[:2])} failed")

    text = output.getvalue().strip()

    return json.loads(text) if text.startswith("{") else {}


def _edit(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _plate(path: Path) -> Path:
    """The test suite's part: a 50 x 30 x 10 mm plate, its vertical edges rounded 4 mm."""

    import cadquery as cq

    plate = (
        cq.Workplane("XY")
        .box(50, 30, 10, centered=(True, True, False))
        .edges("|Z")
        .fillet(4)
    )
    cq.exporters.export(plate, str(path))

    return path


def _accept_capture(data: dict[str, Any]) -> None:
    del data["needs_review"]
    data["edge_features_checked"] = True
    data["source"] = MARK + str(data.get("source", "the capture template"))


def holder(folder: Path) -> Path:
    capture = folder / "object-capture.json"
    _run("capture", "template", "--device", "custom", "--output", str(capture))
    _edit(capture, _accept_capture)
    holder_file = folder / "holder-file.json"
    _run("holder", "template", "--capture", str(capture), "--output", str(holder_file))
    _run(
        "holder",
        "build",
        "--holder-file",
        str(holder_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "holder.json"


def nest(folder: Path) -> Path:
    nest_file = folder / "nest-file.json"
    _run(
        "nest",
        "template",
        "--part",
        str(_plate(folder / "part.step")),
        "--output",
        str(nest_file),
    )
    _run(
        "nest",
        "build",
        "--nest-file",
        str(nest_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "nest.json"


def jig(folder: Path) -> Path:
    jig_file = folder / "jig-file.json"
    _run(
        "jig",
        "template",
        "--part",
        str(_plate(folder / "part.step")),
        "--output",
        str(jig_file),
    )

    def mark_iron(data: dict[str, Any]) -> None:
        data["iron"]["source"] = MARK + "the jig template's example iron"

    _edit(jig_file, mark_iron)
    _run(
        "jig",
        "build",
        "--jig-file",
        str(jig_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "jig.json"


def stack(folder: Path) -> Path:
    profile = folder / "stack-profile.json"
    _run("stack", "template", "--kind", "stack-profile", "--output", str(profile))

    def mark_source(data: dict[str, Any]) -> None:
        data["source"] = MARK + str(data["source"]).split(": ", 1)[-1]

    _edit(profile, mark_source)
    stack_file = folder / "stack-file.json"
    _run(
        "stack",
        "template",
        "--kind",
        "stack",
        "--profile-file",
        str(profile),
        "--output",
        str(stack_file),
    )
    _run(
        "stack",
        "build",
        "--stack-file",
        str(stack_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "stack-build.json"


def housing(folder: Path) -> Path:
    board = folder / "board.json"
    _run("board", "template", "--output", str(board))
    housing_file = folder / "housing-file.json"
    _run(
        "housing",
        "template",
        "--style",
        "case",
        "--input-file",
        str(board),
        "--output",
        str(housing_file),
    )
    _run(
        "housing",
        "build",
        "--housing-file",
        str(housing_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "housing-build.json"


def guide(folder: Path) -> Path:
    guide_file = folder / "guide-file.json"
    _run(
        "guide",
        "template",
        "--part",
        str(_plate(folder / "part.step")),
        "--output",
        str(guide_file),
    )
    _run(
        "guide",
        "build",
        "--guide-file",
        str(guide_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "guide.json"


def pcb_fixture(folder: Path) -> Path:
    kicad = REPOSITORY / "examples" / "kicad"
    board = folder / "board.json"
    _run(
        "board",
        "import",
        "--kicad",
        str(kicad / "sensor-board.kicad_pcb"),
        "--identifier",
        "SENSOR_BOARD",
        "--heights",
        str(kicad / "heights.json"),
        "--cable-connector",
        "J1",
        "--output",
        str(board),
    )
    fixture_file = folder / "fixture-file.json"
    _run(
        "fixture", "template", "--board-file", str(board), "--output", str(fixture_file)
    )
    _run(
        "fixture",
        "build",
        "--fixture-file",
        str(fixture_file),
        "--output-directory",
        str(folder / f"{folder.name}-example"),
    )
    return folder / f"{folder.name}-example" / "fixture.json"


PRODUCTS: dict[str, Callable[[Path], Path]] = {
    "holder": holder,
    "nest": nest,
    "jig": jig,
    "stack": stack,
    "housing": housing,
    "guide": guide,
    "pcb-fixture": pcb_fixture,
}


def build_examples(evidence: Path) -> dict[str, str]:
    examples = evidence / "examples"

    if examples.exists():
        raise FileExistsError(
            f"{examples} exists: the examples are built once and never overwritten"
        )

    built = {}

    for product, make in PRODUCTS.items():
        folder = examples / product
        folder.mkdir(parents=True)
        built[product] = str(make(folder))

    return built


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    # The builds find the printer profiles from the repository root.
    os.chdir(REPOSITORY)
    print(json.dumps({"examples": build_examples(evidence)}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
