"""The production retention lifecycle shared by corner capture and edge clip.

Each strategy derives its own request and rewrites its own fit report; the
steps around those (running the backend on the PCB, refusing a failed
report, exporting the retention STEP) are the same for both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cadquery as cq

from zcad_core.retention.engine import (
    RetentionBackend,
    RetentionEngine,
    RetentionExecution,
    RetentionFitReport,
    RetentionStrategy,
)


class _FailingReport(RetentionFitReport, Protocol):
    @property
    def failures(self) -> tuple[object, ...]: ...


def run_backend(
    strategy: RetentionStrategy,
    backend: RetentionBackend,
    request: object,
    pcb: cq.Shape,
) -> RetentionExecution:
    """Derive, apply, and verify one strategy's geometry on the bare PCB."""

    engine = RetentionEngine()
    engine.register(strategy, backend)

    return engine.execute(
        strategy=strategy,
        request=request,
        model=cq.Workplane("XY").newObject([pcb]),
    )


def verified_execution(
    execution: RetentionExecution,
    production_report: _FailingReport,
    *,
    label: str,
) -> RetentionExecution:
    """The execution with its production report, refused if any check failed."""

    production_execution = RetentionExecution(
        strategy=execution.strategy,
        parameters=execution.parameters,
        model=execution.model,
        report=production_report,
    )

    if not production_execution.passed:
        failed_checks = ", ".join(
            str(getattr(getattr(result, "check", None), "value", result))
            for result in production_report.failures
        )

        raise ValueError(
            f"Production {label} execution failed verification: {failed_checks}"
        )

    return production_execution


def export_retention_step(execution: RetentionExecution, output_step: Path) -> None:
    """Write the retention model to its STEP, refusing a missing export."""

    output_step.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(execution.model, cq.Workplane):
        raise TypeError("Retention execution did not produce a cadquery Workplane")

    cq.exporters.export(execution.model, str(output_step))

    if not output_step.is_file():
        raise RuntimeError("Production STEP export was not created")
