"""Wearable medical-device hardware specifications.

Unlike ``hardware.electronics``, these targets are sealed consumer
devices with no manufacturer-published CAD. Each specification holds
published dimensions, which a caliper capture (``capture``, and
``docs/guides/wearable-capture.md``) replaces before a candidate built
from it is verified.
"""

from zcad_core.hardware.wearables.capture import (
    CUSTOM,
    DEVICES,
    CaptureCheck,
    EdgeFeature,
    FaceFeature,
    WearableCapture,
    capture_template,
    check_capture,
    check_capture_data,
    load_capture,
)
from zcad_core.hardware.wearables.dexcom import (
    DexcomG7Spec,
    get_dexcom_g7,
)
from zcad_core.hardware.wearables.tandem import (
    TandemMobiSpec,
    get_tandem_mobi,
)

__all__ = [
    "CUSTOM",
    "DEVICES",
    "CaptureCheck",
    "DexcomG7Spec",
    "EdgeFeature",
    "FaceFeature",
    "TandemMobiSpec",
    "WearableCapture",
    "capture_template",
    "check_capture",
    "check_capture_data",
    "get_dexcom_g7",
    "get_tandem_mobi",
    "load_capture",
]
