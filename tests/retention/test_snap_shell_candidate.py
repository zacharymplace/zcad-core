"""Wearable snap-shell candidates: clip placement and building from a capture."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from zcad_core.hardware.wearables import EdgeFeature, WearableCapture, capture_template
from zcad_core.retention import SnapShellPolicy
from zcad_core.retention.snap_shell_candidate import Body, clip_locations

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY / "scripts"


def body(*features: EdgeFeature) -> Body:
    return Body(51.3, 37.3, 14.2, "caliper-verified", "test", features=features)


def test_clips_stand_at_the_middle_of_each_edge_with_nothing_in_the_way() -> None:
    locations = clip_locations(
        body(), ("north", "south", "east", "west"), SnapShellPolicy()
    )

    assert [(l.label, l.x_mm, l.y_mm) for l in locations] == [
        ("north", 0.0, 18.65),
        ("south", 0.0, -18.65),
        ("east", 25.65, 0.0),
        ("west", -25.65, 0.0),
    ]


def test_a_clip_slides_to_the_nearest_place_clear_of_a_feature() -> None:
    port = EdgeFeature("fill-port", "north", center_offset_mm=0.0, width_mm=5.0)

    (north,) = clip_locations(body(port), ("north",), SnapShellPolicy())

    # Half the clip (1.5) and half the port (2.5) apart, and the 1 mm margin.
    assert (north.x_mm, north.y_mm) == (5.0, 18.65)


def test_an_edge_with_no_clear_place_is_refused() -> None:
    contacts = EdgeFeature(
        "charging-contacts", "east", center_offset_mm=0.0, width_mm=30.0
    )

    with pytest.raises(
        ValueError, match="No place on the east edge clears charging-contacts"
    ):
        clip_locations(body(contacts), ("east",), SnapShellPolicy())


def test_a_clip_keeps_off_a_rounded_corner_as_the_cradle_tab_does() -> None:
    # 1.5 mm off the middle of the 37.3 mm east edge would clear this button, and
    # a square corner allows it; a 10 mm corner leaves the clip 5.15 mm to slide.
    button = EdgeFeature("button", "east", center_offset_mm=0.0, width_mm=10.0)
    square = body(button)
    rounded = Body(
        51.3,
        37.3,
        14.2,
        "caliper-verified",
        "test",
        features=(button,),
        capture=WearableCapture(
            device="tandem-mobi",
            length_mm=51.3,
            width_mm=37.3,
            thickness_mm=14.2,
            edge_features=(button,),
            measured_by="A. Tester",
            measured_on="2026-10-01",
            caliper="digital caliper",
            source="test",
            sha256="0" * 64,
            path=Path("mobi.json"),
            outline_radius_mm=10.0,
        ),
    )

    (east,) = clip_locations(square, ("east",), SnapShellPolicy())
    assert east.y_mm == 7.5
    with pytest.raises(ValueError, match="No place on the east edge clears button"):
        clip_locations(rounded, ("east",), SnapShellPolicy())


def test_a_tab_needs_its_whole_span_clear_of_a_feature() -> None:
    # A post 3 mm wide clears a 5 mm port 4.5 mm off the middle; a tab's
    # post and beam, 15 mm, must slide past it to 11 mm.
    port = EdgeFeature("port", "north", center_offset_mm=0.0, width_mm=5.0)
    tabs = SnapShellPolicy(tab_length_mm=12.0)

    (post,) = clip_locations(body(port), ("north",), SnapShellPolicy())
    (tab,) = clip_locations(body(port), ("north",), tabs)

    assert post.x_mm == 5.0
    assert tab.x_mm == 11.0


def load(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), SCRIPTS / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "git_commit", lambda root: "c" * 40)
    return module


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "profiles").symlink_to(REPOSITORY / "profiles")
    # Export validation reads the candidate's paths from the working directory.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def capture(path: Path, device: str, features: list[dict[str, Any]]) -> Path:
    data = capture_template(device)
    del data["needs_review"]
    data.update(
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="buttons up",
        source="one device, three passes",
        edge_features=features,
        edge_features_checked=True,
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_capture_builds_a_verified_candidate_with_clips_clear_of_its_features(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = load("build-tandem-mobi-snap-shell-candidate", monkeypatch)
    script.main([], root=root)
    mobi = capture(
        root / "mobi.json",
        "tandem-mobi",
        [
            {
                "identifier": "fill-port",
                "edge": "north",
                "center_offset_mm": 0.0,
                "width_mm": 5.0,
            },
            # The others a Mobi capture must list, away from the north edge.
            *(
                {
                    "identifier": name,
                    "edge": "south",
                    "center_offset_mm": offset,
                    "width_mm": 5.0,
                }
                for name, offset in (("button", -18.0), ("charging-contacts", 18.0))
            ),
        ],
    )

    script.main(
        [
            "--revision",
            "r002",
            "--parent",
            "r001",
            "--reason",
            "Caliper capture",
            "--capture",
            str(mobi),
        ],
        root=root,
    )

    folder = root / "evidence/tandem-mobi-pump/validation-lab/candidates/r002"
    report = json.loads((folder / "automated-validation.json").read_text("utf-8"))
    candidate = json.loads((folder / "candidate.json").read_text("utf-8"))
    # Verified because the shell was measured against the captured envelope:
    # no material in it, each lip over its top face, one solid.
    assert candidate["automated_decision"] == "verified_candidate"
    assert report["clips_into_device_mm3"] == 0.0
    assert all(check["passed"] for check in report["fit_checks"].values())
    assert (
        "No shell material is inside"
        in (report["fit_checks"]["device_clearance"]["detail"])
    )
    assert report["policy"]["ledge_mm"] == 1.5
    assert report["geometry_evidence_status"] == "caliper-verified"
    assert report["metadata_publication"]["approved"]
    assert report["capture"]["measured_by"] == "A. Tester"
    assert (folder / "capture.json").read_bytes() == mobi.read_bytes()
    assert report["source"]["step_path"].endswith(
        "tandem-mobi-caliper-envelope-r002.step"
    )
    north = next(l for l in report["snap_shell_locations"] if l["label"] == "north")
    assert north["x_mm"] == 5.0


def test_a_capture_of_another_device_is_refused_before_anything_is_written(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g7 = capture(root / "g7.json", "dexcom-g7", [])

    with pytest.raises(SystemExit, match="captures a dexcom-g7, not a tandem-mobi"):
        load("build-tandem-mobi-snap-shell-candidate", monkeypatch).main(
            ["--capture", str(g7)], root=root
        )

    assert not (root / "evidence").exists()


def test_the_dexcom_script_now_refuses_to_overwrite_its_pinned_files(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = load("build-dexcom-g7-snap-shell-candidate", monkeypatch)
    script.main([], root=root)

    # A post on the 4.7 mm G7 would strain over the limit; its tabs bend
    # along the edge and pass, so the placeholder build is only provisional.
    report = json.loads(
        (
            root
            / "evidence/dexcom-g7-sensor/validation-lab/candidates/r001"
            / "automated-validation.json"
        ).read_text("utf-8")
    )
    assert report["decision"] == "provisional_synthetic_candidate"
    assert all(check["passed"] for check in report["fit_checks"].values())
    assert (
        "1 mm tab bending over 9.00 mm"
        in (report["fit_checks"]["clip_strain"]["detail"])
    )
    assert report["policy"]["tab_length_mm"] == 12.0
    assert report["clips_into_device_mm3"] == 0.0
    envelope = (
        root / "evidence/dexcom-g7-sensor/step/dexcom-g7-placeholder-envelope.step"
    )
    before = envelope.read_bytes()

    with pytest.raises(SystemExit, match="Refusing to regenerate over pinned files"):
        script.main([], root=root)

    assert envelope.read_bytes() == before
