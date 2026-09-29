"""Reusable modeling features for Z$ CAD."""

from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
)
from zcad_core.features.display_cutouts import (
    DisplayBezelParameters,
    DisplayWindowParameters,
    add_display_bezel,
    cut_display_window,
)
from zcad_core.features.enclosure import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import (
    MountableBoardSpec,
    PcbStandoffParameters,
    add_board_standoffs,
    add_pcb_standoff,
    centered_mounting_hole_positions,
)
from zcad_core.features.snap_retention import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)

__all__ = [
    "ConnectorCutoutParameters",
    "DisplayBezelParameters",
    "DisplayWindowParameters",
    "Enclosure",
    "EnclosureDesign",
    "InsertBossParameters",
    "MountableBoardSpec",
    "PcbStandoffParameters",
    "SnapRetentionClipParameters",
    "add_board_standoffs",
    "add_display_bezel",
    "add_heat_set_insert_boss",
    "add_pcb_standoff",
    "add_snap_retention_clip",
    "build_enclosure",
    "centered_mounting_hole_positions",
    "cut_connector_opening",
    "cut_display_window",
]
