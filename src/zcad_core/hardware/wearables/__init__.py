"""Wearable medical-device hardware specifications.

Unlike ``hardware.electronics``, these targets are sealed consumer
devices with no manufacturer-published CAD. Every specification in this
package starts with ``geometry_evidence_status == "unmeasured"`` and must
be replaced with caliper-verified capture (see
``docs/roadmaps/validation-lab.md``) before it backs a print candidate.
"""

from zcad_core.hardware.wearables.dexcom import (
    DexcomG7Spec,
    get_dexcom_g7,
)
from zcad_core.hardware.wearables.tandem import (
    TandemMobiSpec,
    get_tandem_mobi,
)

__all__ = [
    "DexcomG7Spec",
    "TandemMobiSpec",
    "get_dexcom_g7",
    "get_tandem_mobi",
]
