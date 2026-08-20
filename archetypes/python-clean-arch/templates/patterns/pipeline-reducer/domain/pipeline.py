"""Pipeline runner executing registered stages sequentially."""

from __future__ import annotations

from collections.abc import Sequence

from .models import PipelineContext
from .ports import PipelineStage


class PipelineRunner:
    """Orchestrates sequential execution of pipeline transformation stages."""

    def __init__(self, stages: Sequence[PipelineStage]) -> None:
        """Initializes the runner with an ordered sequence of stages.

        Args:
            stages: Sequence of PipelineStage instances to execute in order.
        """
        self._stages = tuple(stages)

    @property
    def stages(self) -> tuple[PipelineStage, ...]:
        """Returns the tuple of registered stages."""
        return self._stages

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        """Executes all stages sequentially on the context.

        Args:
            initial_context: The initial input PipelineContext.

        Returns:
            The final reduced PipelineContext after all stages complete.
        """
        current = initial_context
        for stage in self._stages:
            # If earlier stage recorded fatal errors, abort subsequent stages
            if current.errors:
                break
            current = stage.process(current)

        return current
