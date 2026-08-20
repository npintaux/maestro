"""Abstract stage interface for Pipeline-Reducer pattern."""

from __future__ import annotations

import abc

from .models import PipelineContext


class PipelineStage(abc.ABC):
    """Abstract port representing a single transformation stage in a data pipeline."""

    @property
    @abc.abstractmethod
    def stage_name(self) -> str:
        """Returns the unique name of this pipeline stage."""
        ...

    @abc.abstractmethod
    def process(self, context: PipelineContext) -> PipelineContext:
        """Process the incoming context and return the transformed context.

        Args:
            context: The immutable PipelineContext entering this stage.

        Returns:
            The transformed PipelineContext.
        """
        ...
