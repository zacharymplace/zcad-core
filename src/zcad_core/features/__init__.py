"""Reusable modeling features for Z$ CAD."""

from zcad_core.features.board_cradle import (
    BoardCradleParameters,
    add_board_cradle,
)
from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
    merge_close_openings,
)
from zcad_core.features.display_cutouts import (
    DisplayBezelParameters,
    DisplayWindowParameters,
    add_display_bezel,
    cut_display_window,
)
from zcad_core.features.display_retainer import (
    DisplayPostParameters,
    DisplayRetainerParameters,
    add_display_posts,
    add_display_retainer,
)
from zcad_core.features.enclosure import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
)
from zcad_core.features.enclosure_review import (
    EnclosureReview,
    export_enclosure_review,
    recommended_screw_length_mm,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import (
    BoardHolePattern,
    MountableBoardSpec,
    PcbStandoffParameters,
    add_board_standoffs,
    add_pcb_standoff,
    board_hole_pattern,
    centered_mounting_hole_positions,
)
from zcad_core.features.snap_retention import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)

__all__ = [
    "BoardCradleParameters",
    "BoardHolePattern",
    "ConnectorCutoutParameters",
    "DisplayBezelParameters",
    "DisplayPostParameters",
    "DisplayRetainerParameters",
    "DisplayWindowParameters",
    "Enclosure",
    "EnclosureDesign",
    "EnclosureReview",
    "InsertBossParameters",
    "MountableBoardSpec",
    "PcbStandoffParameters",
    "SnapRetentionClipParameters",
    "add_board_cradle",
    "add_board_standoffs",
    "add_display_bezel",
    "add_display_posts",
    "add_display_retainer",
    "add_heat_set_insert_boss",
    "add_pcb_standoff",
    "add_snap_retention_clip",
    "board_hole_pattern",
    "build_enclosure",
    "centered_mounting_hole_positions",
    "cut_connector_opening",
    "cut_display_window",
    "export_enclosure_review",
    "merge_close_openings",
    "recommended_screw_length_mm",
]
