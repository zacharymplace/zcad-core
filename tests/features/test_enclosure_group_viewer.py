from __future__ import annotations

import base64
import json
import math
import tomllib
from array import array
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import Bay
from zcad_core.features.enclosure_group_viewer import (
    DATA_FILE,
    DEFAULT_CONFIGS,
    PAGE_FILE,
    ViewerConfig,
    viewer_data,
    viewer_page,
)

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def data() -> list[dict[str, Any]]:
    return viewer_data()


def floats(encoded: str) -> array[float]:
    values: array[float] = array("f")
    values.frombytes(base64.b64decode(encoded))

    return values


def indices(encoded: str) -> array[int]:
    values: array[int] = array("H")
    values.frombytes(base64.b64decode(encoded))

    return values


def test_the_default_set_is_the_five_standard_configurations(
    data: list[dict[str, Any]],
) -> None:
    assert [entry["key"] for entry in data] == [
        "pair",
        "divided",
        "low",
        "raised",
        "shelf",
    ]
    assert [config.key for config in DEFAULT_CONFIGS] == [e["key"] for e in data]
    assert all(entry["name"] and entry["blurb"] for entry in data)


def test_every_mesh_is_well_formed(data: list[dict[str, Any]]) -> None:
    for entry in data:
        for mesh in (entry["base"], entry["lid"], *entry["pis"]):
            vertices = floats(mesh["v"])
            triangles = indices(mesh["i"])

            assert len(vertices) % 3 == 0
            assert len(triangles) % 3 == 0
            assert len(triangles) > 0
            assert max(triangles) < len(vertices) // 3
            assert all(math.isfinite(value) for value in vertices)


def test_the_base_mesh_spans_the_reported_size(data: list[dict[str, Any]]) -> None:
    for entry in data:
        vertices = floats(entry["base"]["v"])
        extents = [
            (min(vertices[axis::3]), max(vertices[axis::3])) for axis in range(3)
        ]

        for (low, high), size in zip(extents, entry["size"], strict=True):
            assert low == pytest.approx(0.0, abs=1e-3)
            assert high == pytest.approx(size, abs=1e-3)


def test_each_pi_bay_has_an_envelope_and_an_open_bay_has_none(
    data: list[dict[str, Any]],
) -> None:
    by_key = {entry["key"]: entry for entry in data}

    assert len(by_key["pair"]["pis"]) == 2
    assert len(by_key["shelf"]["pis"]) == 2
    assert [bay["kind"] for bay in by_key["shelf"]["bays"]] == ["pi5", "pi5", "open"]


def test_the_bay_layout_reaches_the_page_for_its_dimension_chain(
    data: list[dict[str, Any]],
) -> None:
    pair = next(entry for entry in data if entry["key"] == "pair")

    assert pair["wall"] == 2.0
    assert [bay["gap"] for bay in pair["bays"]] == [[0.0, 25.0], [81.5, 106.5]]
    assert [bay["slot"] for bay in pair["bays"]] == [[25.0, 81.5], [106.5, 163.0]]
    assert pair["size"] == [176.0, 96.0, 25.4]


def test_the_bay_summary_carries_heights_and_dividers(
    data: list[dict[str, Any]],
) -> None:
    by_key = {entry["key"]: entry for entry in data}
    raised = by_key["raised"]["bays"]

    assert [bay["standoff"] for bay in raised] == [12.0, 4.0]
    assert [bay["room"] for bay in raised] == [22.0, 30.0]
    assert [bay["divider"] for bay in by_key["divided"]["bays"]] == [False, True]
    assert by_key["divided"]["size"][0] == pytest.approx(178.75)


def test_no_configuration_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one configuration"):
        viewer_data(())


def test_duplicate_keys_are_refused() -> None:
    twin = ViewerConfig("same", "One", "", ("pi5",))

    with pytest.raises(ValueError, match="keys must be unique"):
        viewer_data((twin, twin))


def test_a_configuration_that_will_not_build_is_named() -> None:
    bad = ViewerConfig("bad", "Bad", "", (Bay("open", standoff_height_mm=5.0),))

    with pytest.raises(ValueError, match="configuration 'bad'.*no board to stand off"):
        viewer_data((bad,))


def test_a_configuration_that_fails_its_checks_is_refused() -> None:
    crushed = ViewerConfig("crushed", "Crushed", "", (Bay(headroom_mm=10.0),))

    with pytest.raises(ValueError, match="'crushed' fails its checks"):
        viewer_data((crushed,))


def test_the_page_reads_the_data_file_it_is_written_beside() -> None:
    page = viewer_page()

    assert page.startswith("<title>Pi 5 Enclosure Viewer</title>")
    assert f'fetch("{DATA_FILE}")' in page
    assert "<!doctype" not in page.lower()


def test_the_page_pins_its_scripts_with_integrity_hashes() -> None:
    page = viewer_page()
    scripts = [line for line in page.splitlines() if "<script src=" in line]

    assert len(scripts) == 2
    for line in scripts:
        assert 'integrity="sha384-' in line
        assert 'crossorigin="anonymous"' in line
    assert "three.js/r128/" in scripts[0]
    assert "three@0.128.0" in scripts[1]


def test_a_standalone_page_carries_its_own_skeleton() -> None:
    fragment = viewer_page()
    standalone = viewer_page(standalone=True)

    assert standalone.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in standalone
    assert fragment in standalone
    assert standalone.rstrip().endswith("</html>")


def test_the_template_ships_in_the_package_data() -> None:
    pyproject = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())
    patterns = pyproject["tool"]["setuptools"]["package-data"]["zcad_core"]

    assert "features/data/*.html" in patterns


def run(
    capsys: pytest.CaptureFixture[str], directory: Path, *args: str
) -> tuple[int, dict[str, Any], str]:
    exit_code = main(
        ["enclosure-group", "viewer", "--output-directory", str(directory), *args]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_the_command_writes_the_page_and_the_five_configurations(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output, _ = run(capsys, tmp_path)
    written = json.loads((tmp_path / DATA_FILE).read_text())

    assert exit_code == 0
    assert (tmp_path / PAGE_FILE).read_text() == viewer_page()
    assert [entry["key"] for entry in written] == [
        "pair",
        "divided",
        "low",
        "raised",
        "shelf",
    ]
    assert output["data_bytes"] == (tmp_path / DATA_FILE).stat().st_size
    assert output["standalone"] is False
    assert [c["key"] for c in output["configurations"]] == [e["key"] for e in written]
    assert output["view"] == f"python3 -m http.server --directory {tmp_path}"


def test_the_command_builds_custom_rows_and_a_standalone_page(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output, _ = run(
        capsys,
        tmp_path,
        "--bays",
        "pi5,pi5:divider=notch",
        "--bays",
        "pi5:standoff=8",
        "--standalone",
    )
    written = json.loads((tmp_path / DATA_FILE).read_text())

    assert exit_code == 0
    assert [entry["key"] for entry in written] == ["custom-1", "custom-2"]
    assert [entry["name"] for entry in written] == [
        "pi5,pi5:divider=notch",
        "pi5:standoff=8",
    ]
    assert (tmp_path / PAGE_FILE).read_text().startswith("<!doctype html>")
    assert output["standalone"] is True


def test_the_command_never_overwrites_an_existing_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / DATA_FILE).write_text("keep")

    exit_code, _, err = run(capsys, tmp_path, "--bays", "pi5")

    assert exit_code == 1
    assert "Refusing to overwrite" in err
    assert (tmp_path / DATA_FILE).read_text() == "keep"
    assert not (tmp_path / PAGE_FILE).exists()


@pytest.mark.parametrize(
    ("bays", "message"),
    [
        ("hat", "bay kind must be one of"),
        ("pi5:open=1", "bay option must be"),
        ("pi5:headroom=10", "fails its checks"),
    ],
)
def test_the_command_refuses_a_row_it_cannot_show(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str, message: str
) -> None:
    exit_code, _, err = run(capsys, tmp_path, "--bays", bays)

    assert exit_code == 1
    assert message in err
    assert not (tmp_path / DATA_FILE).exists()
