"""The register of figures taken on trust: it covers every constant, and says so."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core import figures

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs/figures/register.json"
PAGE = ROOT / "docs/reference/figures.md"


def package(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "module.py").write_text(source, encoding="utf-8")

    return root


def test_every_constant_is_recorded_and_every_entry_names_one() -> None:
    issues = figures.problems(figures.load(REGISTER), figures.scan())

    assert issues == [], "\n".join(issues) + (
        "\nrun scripts/figure-register.py --update, then give each new figure its "
        "status in docs/figures/register.json"
    )


def test_the_page_is_the_register_as_it_stands() -> None:
    expected = figures.render(
        figures.load(REGISTER),
        figures.scan(),
        figures.catalogue_items(),
        figures.load_review(REGISTER),
    )

    assert PAGE.read_text(encoding="utf-8") == expected, (
        "docs/reference/figures.md is out of date: run scripts/figure-register.py "
        "--update"
    )


def test_a_figure_that_claims_a_source_says_what_it_is() -> None:
    register = figures.load(REGISTER)

    for key, entry in register.items():
        if entry["status"] in figures.NEEDS_SOURCE:
            assert entry.get("source", "").strip(), key


def test_the_scan_finds_numeric_constants_and_their_comments(tmp_path: Path) -> None:
    root = package(
        tmp_path,
        "# A margin, for a reason.\n# Over two lines.\nSKIN_MM = 0.4\n"
        "_RANGE_MM = (-0.2, 1.0)\nNAMES = ('a', 'b')\nlower = 3\nFLAG = True\n"
        "SUM_MM = 2 * 1.5\nTEXT = 'x'\n",
    )
    found = {figure.name: figure for figure in figures.scan(root)}

    assert sorted(found) == ["SKIN_MM", "SUM_MM", "_RANGE_MM"]
    assert found["SKIN_MM"].comment == "A margin, for a reason. Over two lines."
    assert found["SKIN_MM"].key == "module.py:SKIN_MM"
    assert found["_RANGE_MM"].value == "(-0.2, 1.0)"
    assert found["SUM_MM"].comment == ""


DEFAULTS = """
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Spec:
    # A wall, for a reason.
    wall_mm: float = 1.2
    origin_mm: float = 0.0
    offset: tuple[float, float] = (0.0, 0.0)
    axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    flag: bool = True
    name: str = "x"
    parts: tuple[float, ...] = field(default_factory=tuple)
    unset: float | None = None


class Plain:
    clearance_mm: float = 0.3


def build(depth_mm=2.5, *, margin_mm=0.4, none=None, text="x", zero=0.0, flag=True):
    def inner(step_mm=0.5):
        return step_mm

    return inner


class Maker:
    def make(self, size_mm=10.0, *, gap_mm=0.25):
        return size_mm
"""


def test_the_scan_finds_the_non_zero_defaults_of_dataclasses_and_parameters(
    tmp_path: Path,
) -> None:
    found = {figure.key: figure for figure in figures.scan(package(tmp_path, DEFAULTS))}

    assert sorted(found) == [
        "module.py:Maker.make(gap_mm)",
        "module.py:Maker.make(size_mm)",
        "module.py:Spec.axis",
        "module.py:Spec.wall_mm",
        "module.py:build(depth_mm)",
        "module.py:build(margin_mm)",
        "module.py:build.inner(step_mm)",
    ]
    assert found["module.py:Spec.wall_mm"].comment == "A wall, for a reason."
    assert found["module.py:Spec.wall_mm"].value == "1.2"
    assert found["module.py:build(margin_mm)"].value == "0.4"


def test_a_zero_default_a_flag_a_string_and_a_plain_class_are_not_figures(
    tmp_path: Path,
) -> None:
    names = {figure.name for figure in figures.scan(package(tmp_path, DEFAULTS))}

    for absent in (
        "Spec.origin_mm",
        "Spec.offset",
        "Spec.flag",
        "Spec.name",
        "Spec.parts",
        "Spec.unset",
        "Plain.clearance_mm",
        "build(zero)",
        "build(flag)",
        "build(none)",
        "build(text)",
    ):
        assert absent not in names


def test_the_real_register_covers_defaults_as_well_as_constants() -> None:
    keys = {figure.key for figure in figures.scan()}

    assert any(":" in key and "(" in key for key in keys), "parameter defaults"
    assert any(key.endswith("RaspberryPi5Spec.board_width_mm") for key in keys), (
        "dataclass field defaults"
    )
    assert any(key.endswith(":DEFAULT_ENGAGEMENT_MM") for key in keys), "constants"


def test_a_new_constant_a_gone_one_and_a_bare_claim_are_each_named(
    tmp_path: Path,
) -> None:
    found = figures.scan(package(tmp_path, "NEW_MM = 1.0\nKEPT_MM = 2.0\n"))
    register = {
        "module.py:KEPT_MM": {"status": "sourced"},
        "module.py:GONE_MM": {"status": "unstated"},
        "module.py:ODD_MM": {"status": "made_up"},
        "module.py:EXAMPLE_MM": {"status": "example"},
        "module.py:GUESS_MM": {"status": "estimated"},
        "module.py:TRIED_MM": {"status": "measured"},
    }
    issues = "\n".join(figures.problems(register, found))

    assert "module.py:NEW_MM is not in the register" in issues
    assert "module.py:GONE_MM is in the register but no such figure" in issues
    assert "module.py:KEPT_MM is sourced but says nothing of where" in issues
    assert "module.py:ODD_MM has status 'made_up'" in issues
    assert "module.py:EXAMPLE_MM is example but says nothing of where" in issues
    assert "module.py:GUESS_MM is estimated but says nothing of where" in issues
    assert "module.py:TRIED_MM is measured but names no joint profile figure" in issues


def test_updating_adds_new_constants_as_unstated_and_keeps_what_is_known(
    tmp_path: Path,
) -> None:
    found = figures.scan(package(tmp_path, "NEW_MM = 1.0\nKEPT_MM = 2.0\n"))
    register = {
        "module.py:KEPT_MM": {"status": "design_default", "note": "the author's"},
        "module.py:GONE_MM": {"status": "sourced", "source": "x"},
    }
    merged = figures.updated(register, found)

    assert merged == {
        "module.py:KEPT_MM": {"status": "design_default", "note": "the author's"},
        "module.py:NEW_MM": {"status": "unstated"},
    }
    assert figures.problems(merged, found) == []


def test_a_new_figure_is_never_taken_as_sourced_by_default() -> None:
    merged = figures.updated({}, figures.scan())

    assert {entry["status"] for entry in merged.values()} == {"unstated"}


def test_the_catalogue_lists_what_each_item_says_is_unverified() -> None:
    items = figures.catalogue_items()
    fans = [item for item in items if item["kind"] == "fan"]

    assert {item["kind"] for item in items} == {"fan", "bushing", "pogo pin"}
    assert any(item["unverified"] for item in fans)
    assert any(not item["document_read"] for item in fans)


def test_the_register_file_round_trips() -> None:
    data = json.loads(REGISTER.read_text(encoding="utf-8"))

    assert data["schema_version"] == figures.SCHEMA_VERSION
    assert figures.dump(data["figures"], data.get("review", "")) == REGISTER.read_text(
        encoding="utf-8"
    )


def test_a_review_note_survives_the_file_and_reaches_the_page(tmp_path: Path) -> None:
    found = figures.scan(package(tmp_path, "NEW_MM = 1.0\n"))
    register = figures.updated({}, found)
    path = tmp_path / "register.json"
    path.write_text(figures.dump(register, "Checked the code; found nothing."))

    assert figures.load_review(path) == "Checked the code; found nothing."
    assert figures.load(path) == register
    assert "Checked the code; found nothing." in figures.render(
        register, found, [], figures.load_review(path)
    )
    assert "Last review" not in figures.render(register, found, [])
    assert "review" not in json.loads(figures.dump(register))


def test_the_real_register_records_what_its_review_did_and_did_not_find() -> None:
    review = figures.load_review(REGISTER)

    assert "Not found" in review
    assert "Limits" in review


def test_an_old_register_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "register.json"
    path.write_text('{"schema_version": "0.1.0", "figures": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        figures.load(path)
