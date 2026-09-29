from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.edge_outline import EdgeOutlineAnalyzer
from zcad_core.geometry.intersection import intersection_volume, solid_intersection
from zcad_core.geometry.types import (
    BoardEdge,
    EdgeSegment,
    EdgeValidationResult,
)

__all__ = [
    "BoardEdge",
    "EdgeOutlineAnalyzer",
    "EdgeSegment",
    "EdgeValidationResult",
    "intersection_volume",
    "solid_intersection",
    "workplane_shape",
]
