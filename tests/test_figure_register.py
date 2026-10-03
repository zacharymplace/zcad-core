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
        figures.load(REGISTER), figures.scan(), figures.catalogue_items()
    )

    assert PAGE.read_text(encoding="utf-8") == expected, (
        "docs/reference/figures.md is out of date: run scripts/figure-register.py "
        "--update"
    )


def test_a_figure_is_sourced_only_with_a_source_and_every_sourced_one_has_one() -> None:
    register = figures.load(REGISTER)

    for key, entry in register.items():
        if entry["status"] in ("sourced", "example"):
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


def test_a_new_constant_a_gone_one_and_a_bare_claim_are_each_named(
    tmp_path: Path,
) -> None:
    found = figures.scan(package(tmp_path, "NEW_MM = 1.0\nKEPT_MM = 2.0\n"))
    register = {
        "module.py:KEPT_MM": {"status": "sourced"},
        "module.py:GONE_MM": {"status": "unstated"},
        "module.py:ODD_MM": {"status": "made_up"},
        "module.py:EXAMPLE_MM": {"status": "example"},
    }
    issues = "\n".join(figures.problems(register, found))

    assert "module.py:NEW_MM is not in the register" in issues
    assert "module.py:GONE_MM is in the register but no such constant" in issues
    assert "module.py:KEPT_MM is sourced but gives no source" in issues
    assert "module.py:ODD_MM has status 'made_up'" in issues
    assert "module.py:EXAMPLE_MM is an example but says nothing" in issues


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
    assert figures.dump(data["figures"]) == REGISTER.read_text(encoding="utf-8")


def test_an_old_register_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "register.json"
    path.write_text('{"schema_version": "0.1.0", "figures": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        figures.load(path)
