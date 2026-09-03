from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class RetentionStrategy(str, Enum):
    """Registered board-retention strategy."""

    CORNER_CAPTURE = "corner_capture"
    EDGE_CLIP = "edge_clip"
    SNAP_SHELL = "snap_shell"


@runtime_checkable
class RetentionFitReport(Protocol):
    """Minimum verification-report contract."""

    @property
    def passed(self) -> bool:
        """Whether all required verification gates passed."""

        ...


@runtime_checkable
class RetentionBackend(Protocol):
    """Strategy-neutral retention backend lifecycle."""

    def derive(
        self,
        request: object,
    ) -> object:
        """Derive validated strategy parameters."""

        ...

    def apply(
        self,
        model: object,
        parameters: object,
    ) -> object:
        """Apply retention geometry to a model."""

        ...

    def analyze_fit(
        self,
        parameters: object,
    ) -> RetentionFitReport:
        """Verify the derived strategy parameters."""

        ...


@dataclass(frozen=True)
class RetentionExecution:
    """Result of one complete retention lifecycle."""

    strategy: RetentionStrategy
    parameters: object
    model: object
    report: RetentionFitReport

    @property
    def passed(self) -> bool:
        """Whether the execution passed verification."""

        return self.report.passed


class RetentionEngine:
    """Registry and execution service for retention backends."""

    def __init__(self) -> None:
        self._backends: dict[
            RetentionStrategy,
            RetentionBackend,
        ] = {}

    def register(
        self,
        strategy: RetentionStrategy,
        backend: RetentionBackend,
        *,
        replace: bool = False,
    ) -> None:
        """Register a backend for one retention strategy."""

        if not isinstance(
            backend,
            RetentionBackend,
        ):
            raise TypeError("backend must satisfy RetentionBackend")

        if strategy in self._backends and not replace:
            raise ValueError(
                f"Retention backend already registered for {strategy.value}"
            )

        self._backends[strategy] = backend

    def resolve(
        self,
        strategy: RetentionStrategy,
    ) -> RetentionBackend:
        """Resolve the backend registered for a strategy."""

        try:
            return self._backends[strategy]
        except KeyError as error:
            raise KeyError(
                f"No retention backend registered for {strategy.value}"
            ) from error

    def execute(
        self,
        *,
        strategy: RetentionStrategy,
        request: object,
        model: object,
    ) -> RetentionExecution:
        """Execute derivation, geometry, and verification."""

        backend = self.resolve(strategy)
        parameters = backend.derive(request)
        result_model = backend.apply(
            model,
            parameters,
        )
        report = backend.analyze_fit(parameters)

        if not isinstance(
            report,
            RetentionFitReport,
        ):
            raise TypeError("Backend analyze_fit() must return a RetentionFitReport")

        return RetentionExecution(
            strategy=strategy,
            parameters=parameters,
            model=result_model,
            report=report,
        )
