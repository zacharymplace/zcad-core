"""The Pi 5 spec and its enclosure envelope are not mirrored or turned.

Raspberry Pi's STEP model shows the board from above, components up. Its
Ethernet jack, USB stacks, header, USB-C connector, and microSD slot are
recorded in ``tests/data/raspberry-pi-5-vendor-features.json``. Only a proper
rotation takes that frame into the spec's, so:

1. find the rotation that puts the model's Ethernet edge on the edge the spec
   gives its Ethernet port;
2. carry every other feature through that same rotation; and
3. require the enclosure's Pi envelope to contain each one.

A mirrored spec fails at step 3, since a reflection is not a rotation. An
earlier version of the spec was mirrored, and no test noticed, because each
port was checked alone, against numbers read off the same drawing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.features.enclosure_group import GroupEnclosure, build_group_enclosure
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi5

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FEATURES = REPOSITORY_ROOT / "tests/data/raspberry-pi-5-vendor-features.json"
SCRIPT = REPOSITORY_ROOT / "scripts/extract-pi5-vendor-features.py"
NORMALS = {
    "positive_x": (1, 0),
    "negative_x": (-1, 0),
    "positive_y": (0, 1),
    "negative_y": (0, -1),
}
# A probe sits this far inside a feature's top face, or under the board.
INSET_MM = 0.6
BELOW_BOARD_MM = 0.7
PROBE_MM = 0.4
# A connector that overhangs the board by more than this also gets a probe this
# far past the edge, where nothing else of the Pi stands.
OVERHANG_MM = 0.5
LIP_MM = 0.25
# What a left-right mirror must lose. The mirrored header lands on the USB-C
# connector's probe point, so it is the probe past the edge, where nothing else
# stands, that catches USB-C.
MIRROR_MUST_MISS = {"gpio_header", "usb_stack_2", "usb_c_lip"}

Point = tuple[float, float]


@pytest.fixture(scope="module")
def vendor() -> dict[str, Any]:
    record: dict[str, Any] = json.loads(FEATURES.read_text(encoding="utf-8"))

    return record


@pytest.fixture(scope="module")
def group() -> GroupEnclosure:
    return build_group_enclosure()


def named(vendor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {feature["name"]: feature for feature in vendor["features"]}


def turn(point: Point, quarter_turns: int) -> Point:
    """Rotate a point counter-clockwise, seen from above, by quarter turns."""

    x, y = point

    for _ in range(quarter_turns % 4):
        x, y = -y, x

    return x, y


def edge_normal(point: Point, board: list[float]) -> Point:
    """The unit axis of the board edge a point sits nearest, judged as a
    fraction of the board's half-size: the USB-C connector is far along the
    long edge but close to the short one."""

    x, y = point[0] / (board[0] / 2), point[1] / (board[1] / 2)

    return (1 if x > 0 else -1, 0) if abs(x) > abs(y) else (0, 1 if y > 0 else -1)


def lip_point(feature: dict[str, Any], board: list[float]) -> Point:
    """A point just past the board edge a feature overhangs, level with the
    feature along that edge."""

    x, y = feature["x_mm"], feature["y_mm"]
    normal = edge_normal((x, y), board)

    if normal[0]:
        return normal[0] * (board[0] / 2 + LIP_MM), y

    return x, normal[1] * (board[1] / 2 + LIP_MM)


def rotation_to_spec(vendor: dict[str, Any]) -> int:
    """The quarter turns that put the model's Ethernet edge on the spec's."""

    ethernet = named(vendor)["ethernet"]
    model = edge_normal((ethernet["x_mm"], ethernet["y_mm"]), vendor["board_mm"])
    port = next(p for p in get_raspberry_pi5().ports if p.identifier == "ETHERNET")

    for quarter_turns in range(4):
        if turn(model, quarter_turns) == NORMALS[port.edge]:
            return quarter_turns

    raise AssertionError("no rotation aligns the Ethernet edges")


def probe_points(
    vendor: dict[str, Any], group: GroupEnclosure
) -> dict[str, tuple[float, float, float]]:
    """Each vendor feature as a point in the enclosure's frame, inside the
    first bay's Pi, carried through the one rotation that fits the Ethernet."""

    quarter_turns = rotation_to_spec(vendor)
    bay = group.bays[0]
    centre_x = group.design.wall_mm + bay.center_x_mm
    centre_y = group.pi_center_y_mm
    points = {}

    for name, feature in named(vendor).items():
        x, y = turn((feature["x_mm"], feature["y_mm"]), quarter_turns)
        z = (
            bay.board_bottom_z_mm - BELOW_BOARD_MM
            if feature["top_mm"] < 0
            else bay.board_top_z_mm + feature["top_mm"] - INSET_MM
        )
        points[name] = (centre_x + x, centre_y + y, z)

        if feature["edge_overhang_mm"] > OVERHANG_MM:
            lip_x, lip_y = turn(lip_point(feature, vendor["board_mm"]), quarter_turns)
            points[f"{name}_lip"] = (centre_x + lip_x, centre_y + lip_y, z)

    return points


def missing(
    envelope: cq.Shape, points: dict[str, tuple[float, float, float]]
) -> set[str]:
    """The features whose probe point lies outside the envelope."""

    def inside(point: tuple[float, float, float]) -> bool:
        x, y, z = point
        probe = cq.Solid.makeBox(
            PROBE_MM,
            PROBE_MM,
            PROBE_MM,
            pnt=cq.Vector(x - PROBE_MM / 2, y - PROBE_MM / 2, z - PROBE_MM / 2),
        )

        return intersection_volume(envelope, probe) > 0.01

    return {name for name, point in points.items() if not inside(point)}


def test_the_vendor_model_is_seen_from_above_with_components_up(
    vendor: dict[str, Any],
) -> None:
    features = named(vendor)

    assert vendor["board_mm"][:2] == pytest.approx([85.0, 56.0], abs=0.1)
    # The tall connectors and the header stand on the top face; the microSD
    # slot hangs below it. A model turned over would mirror every result.
    for name in ("ethernet", "usb_stack_1", "usb_stack_2", "gpio_header", "usb_c"):
        assert features[name]["top_mm"] > 3.0, name
    assert features["micro_sd"]["top_mm"] < 0
    assert features["gpio_header"]["parts"] == 40


def test_the_ethernet_jack_and_usb_stacks_share_an_edge_in_the_model(
    vendor: dict[str, Any],
) -> None:
    features = named(vendor)
    edges = {
        edge_normal(
            (features[name]["x_mm"], features[name]["y_mm"]), vendor["board_mm"]
        )
        for name in ("ethernet", "usb_stack_1", "usb_stack_2")
    }

    assert len(edges) == 1


def test_the_spec_puts_the_usb_c_edge_opposite_the_header() -> None:
    pi = get_raspberry_pi5()
    usb_c = next(p for p in pi.ports if p.identifier == "USB_C_POWER")
    hdmi = [p for p in pi.ports if p.identifier.startswith("MICRO_HDMI")]

    assert {p.edge for p in hdmi} == {usb_c.edge}
    # The header stands one hole-row in from the opposite edge.
    normal = NORMALS[usb_c.edge]
    header_side = -1 if normal[0] > 0 else 1

    assert normal[0] != 0
    assert header_side == -normal[0]


def test_the_envelope_holds_every_feature_of_the_vendor_model(
    vendor: dict[str, Any], group: GroupEnclosure
) -> None:
    points = probe_points(vendor, group)

    assert set(points) == {
        "ethernet",
        "usb_stack_1",
        "usb_stack_2",
        "gpio_header",
        "usb_c",
        "micro_sd",
        "ethernet_lip",
        "usb_stack_1_lip",
        "usb_stack_2_lip",
        "usb_c_lip",
    }
    assert missing(group.hardware["bay-0"], points) == set()


def test_a_mirrored_envelope_fails_the_check(
    vendor: dict[str, Any], group: GroupEnclosure
) -> None:
    # The guard must be able to fail: mirror the envelope left to right about
    # its own centre, as the spec once was, and it must lose the header, which
    # moves to the other side, and the outer USB stack.
    points = probe_points(vendor, group)
    centre_x = group.design.wall_mm + group.bays[0].center_x_mm
    mirrored = group.hardware["bay-0"].mirror("YZ", (centre_x, 0, 0))

    assert MIRROR_MUST_MISS <= missing(mirrored, points)


def test_a_turned_envelope_fails_the_check(
    vendor: dict[str, Any], group: GroupEnclosure
) -> None:
    # A quarter turn is a proper rotation, but the wrong one: the Ethernet
    # edge lands on a side edge, so the check must catch it too.
    points = probe_points(vendor, group)
    centre = (
        group.design.wall_mm + group.bays[0].center_x_mm,
        group.pi_center_y_mm,
        0,
    )
    turned = group.hardware["bay-0"].rotate(centre, (centre[0], centre[1], 1), 90)

    assert len(missing(turned, points)) >= 3


@pytest.mark.slow
def test_the_recorded_features_match_the_vendor_model(vendor: dict[str, Any]) -> None:
    model = REPOSITORY_ROOT / vendor["source_model_path"]

    if not model.is_file():
        pytest.skip("the vendor model is in the evidence checkout")

    assert (
        hashlib.sha256(model.read_bytes()).hexdigest() == vendor["source_model_sha256"]
    ), "re-run scripts/extract-pi5-vendor-features.py for the new model"

    module_spec = importlib.util.spec_from_file_location("extract_pi5_vendor", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    fresh = module.extract(model)

    assert fresh["board_mm"] == pytest.approx(vendor["board_mm"], abs=0.01)
    assert [f["name"] for f in fresh["features"]] == [
        f["name"] for f in vendor["features"]
    ]
    for new, recorded in zip(fresh["features"], vendor["features"], strict=True):
        for key in ("x_mm", "y_mm", "top_mm", "bottom_mm"):
            assert new[key] == pytest.approx(recorded[key], abs=0.01), (
                recorded["name"],
                key,
            )
        assert new["parts"] == recorded["parts"]
