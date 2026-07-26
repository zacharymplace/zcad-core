from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq

from zcad_core.geometry.types import (
    BoardEdge,
    EdgeSegment,
    EdgeValidationResult,
)

_EPSILON = 1e-9


@dataclass(frozen=True)
class _Sample:
    start_mm: float
    end_mm: float
    material_ratio: float
    passes: bool


class EdgeOutlineAnalyzer:
    """Validate continuous PCB material along an engagement band.

    Components are deliberately outside this analyzer's scope.
    This class validates only the PCB solid itself, including
    rounded corners, notches, cutouts, and holes entering the band.
    """

    def __init__(
        self,
        pcb: cq.Shape,
        *,
        engagement_depth_mm: float = 2.5,
        sample_resolution_mm: float = 0.25,
        required_material_ratio: float = 0.995,
        z_margin_mm: float = 0.01,
    ) -> None:
        if engagement_depth_mm <= 0:
            raise ValueError("engagement_depth_mm must be positive")

        if sample_resolution_mm <= 0:
            raise ValueError("sample_resolution_mm must be positive")

        if not 0 < required_material_ratio <= 1:
            raise ValueError("required_material_ratio must be in (0, 1]")

        if z_margin_mm < 0:
            raise ValueError("z_margin_mm cannot be negative")

        bounds = pcb.BoundingBox()

        if min(bounds.xlen, bounds.ylen, bounds.zlen) <= 0:
            raise ValueError("PCB must have positive X, Y, and Z extents")

        if engagement_depth_mm >= min(
            bounds.xlen,
            bounds.ylen,
        ):
            raise ValueError("engagement_depth_mm is too large for the PCB")

        if 2 * z_margin_mm >= bounds.zlen:
            raise ValueError("z_margin_mm removes the full PCB thickness")

        self._pcb = pcb
        self._bounds = bounds
        self._engagement_depth_mm = engagement_depth_mm
        self._sample_resolution_mm = sample_resolution_mm
        self._required_material_ratio = required_material_ratio
        self._z_margin_mm = z_margin_mm

    @property
    def engagement_depth_mm(self) -> float:
        return self._engagement_depth_mm

    @property
    def sample_resolution_mm(self) -> float:
        return self._sample_resolution_mm

    def edge_limits(
        self,
        edge: BoardEdge,
    ) -> tuple[float, float]:
        """Return the coordinate range running along an edge."""

        if edge in {
            BoardEdge.NEGATIVE_X,
            BoardEdge.POSITIVE_X,
        }:
            return self._bounds.ymin, self._bounds.ymax

        return self._bounds.xmin, self._bounds.xmax

    def validate_segment(
        self,
        segment: EdgeSegment,
    ) -> EdgeValidationResult:
        """Validate one requested interval."""

        self._validate_segment_limits(segment)

        samples = self._sample_segment(segment)
        blocked_spans = self._collect_spans(
            edge=segment.edge,
            samples=samples,
            passing=False,
            minimum_length_mm=0.0,
        )

        passing_count = sum(sample.passes for sample in samples)
        continuous = not blocked_spans

        return EdgeValidationResult(
            segment=segment,
            engagement_depth_mm=(self._engagement_depth_mm),
            sample_resolution_mm=(self._sample_resolution_mm),
            sample_count=len(samples),
            passing_sample_count=passing_count,
            minimum_material_ratio=min(sample.material_ratio for sample in samples),
            continuous=continuous,
            usable=continuous,
            blocked_spans=blocked_spans,
            reason=(
                None
                if continuous
                else (
                    "The PCB does not provide continuous "
                    "material throughout the requested "
                    "engagement band."
                )
            ),
        )

    def candidate_segments(
        self,
        edge: BoardEdge,
        *,
        minimum_length_mm: float,
    ) -> tuple[EdgeSegment, ...]:
        """Return usable continuous intervals on one edge."""

        if minimum_length_mm <= 0:
            raise ValueError("minimum_length_mm must be positive")

        lower, upper = self.edge_limits(edge)
        samples = self._sample_segment(
            EdgeSegment(
                edge=edge,
                start_mm=lower,
                end_mm=upper,
            )
        )

        return self._collect_spans(
            edge=edge,
            samples=samples,
            passing=True,
            minimum_length_mm=minimum_length_mm,
        )

    def _validate_segment_limits(
        self,
        segment: EdgeSegment,
    ) -> None:
        lower, upper = self.edge_limits(segment.edge)

        if segment.start_mm < lower - _EPSILON:
            raise ValueError("Segment starts outside the PCB envelope")

        if segment.end_mm > upper + _EPSILON:
            raise ValueError("Segment ends outside the PCB envelope")

    def _sample_segment(
        self,
        segment: EdgeSegment,
    ) -> tuple[_Sample, ...]:
        sample_count = max(
            1,
            math.ceil(segment.length_mm / self._sample_resolution_mm),
        )
        sample_length = segment.length_mm / sample_count

        samples: list[_Sample] = []

        for index in range(sample_count):
            start_mm = segment.start_mm + index * sample_length
            end_mm = (
                segment.end_mm
                if index == sample_count - 1
                else start_mm + sample_length
            )

            probe = self._make_probe(
                edge=segment.edge,
                start_mm=start_mm,
                end_mm=end_mm,
            )
            probe_volume = probe.Volume()

            if probe_volume <= _EPSILON:
                raise RuntimeError("Generated edge probe has no volume")

            material_volume = probe.intersect(self._pcb).Volume()
            ratio = max(
                0.0,
                min(
                    1.0,
                    material_volume / probe_volume,
                ),
            )

            samples.append(
                _Sample(
                    start_mm=start_mm,
                    end_mm=end_mm,
                    material_ratio=ratio,
                    passes=(ratio + _EPSILON >= self._required_material_ratio),
                )
            )

        return tuple(samples)

    def _make_probe(
        self,
        *,
        edge: BoardEdge,
        start_mm: float,
        end_mm: float,
    ) -> cq.Shape:
        segment_length = end_mm - start_mm
        segment_center = (start_mm + end_mm) / 2.0
        depth = self._engagement_depth_mm
        z_length = self._bounds.zlen - 2 * self._z_margin_mm
        z_center = (self._bounds.zmin + self._bounds.zmax) / 2.0

        if edge is BoardEdge.NEGATIVE_X:
            x_length = depth
            y_length = segment_length
            x_center = self._bounds.xmin + depth / 2.0
            y_center = segment_center
        elif edge is BoardEdge.POSITIVE_X:
            x_length = depth
            y_length = segment_length
            x_center = self._bounds.xmax - depth / 2.0
            y_center = segment_center
        elif edge is BoardEdge.NEGATIVE_Y:
            x_length = segment_length
            y_length = depth
            x_center = segment_center
            y_center = self._bounds.ymin + depth / 2.0
        elif edge is BoardEdge.POSITIVE_Y:
            x_length = segment_length
            y_length = depth
            x_center = segment_center
            y_center = self._bounds.ymax - depth / 2.0
        else:
            raise ValueError(f"Unsupported board edge: {edge}")

        probe = (
            cq.Workplane("XY")
            .box(
                x_length,
                y_length,
                z_length,
                centered=(True, True, True),
            )
            .translate((x_center, y_center, z_center))
            .val()
        )

        if not isinstance(probe, cq.Shape):
            raise TypeError("CadQuery did not produce a probe shape")

        return probe

    @staticmethod
    def _collect_spans(
        *,
        edge: BoardEdge,
        samples: tuple[_Sample, ...],
        passing: bool,
        minimum_length_mm: float,
    ) -> tuple[EdgeSegment, ...]:
        spans: list[EdgeSegment] = []
        active_start: float | None = None
        active_end: float | None = None

        for sample in samples:
            if sample.passes is passing:
                if active_start is None:
                    active_start = sample.start_mm

                active_end = sample.end_mm
                continue

            if active_start is not None and active_end is not None:
                segment = EdgeSegment(
                    edge=edge,
                    start_mm=active_start,
                    end_mm=active_end,
                )

                if segment.length_mm + _EPSILON >= minimum_length_mm:
                    spans.append(segment)

            active_start = None
            active_end = None

        if active_start is not None and active_end is not None:
            segment = EdgeSegment(
                edge=edge,
                start_mm=active_start,
                end_mm=active_end,
            )

            if segment.length_mm + _EPSILON >= minimum_length_mm:
                spans.append(segment)

        return tuple(spans)
