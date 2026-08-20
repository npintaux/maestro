"""Domain models for Pipeline-Reducer pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PipelineContext:
    """Immutable data context passing through pipeline stages.

    Attributes:
        pipeline_id: Unique trace or execution identifier.
        data: Accumulated payload and transformations.
        metadata: Stage execution timestamps and diagnostics.
        errors: List of error messages encountered during processing.
    """

    pipeline_id: str
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def with_data(self, key: str, value: Any) -> PipelineContext:
        """Returns a new PipelineContext with updated data.

        Args:
            key: Data attribute key.
            value: Attribute value.

        Returns:
            A new immutable PipelineContext instance.
        """
        updated_data = dict(self.data)
        updated_data[key] = value
        return PipelineContext(
            pipeline_id=self.pipeline_id,
            data=updated_data,
            metadata=self.metadata,
            errors=self.errors,
        )

    def with_error(self, error_message: str) -> PipelineContext:
        """Returns a new PipelineContext with an error appended.

        Args:
            error_message: Explanatory failure reason.

        Returns:
            A new immutable PipelineContext instance containing the error.
        """
        return PipelineContext(
            pipeline_id=self.pipeline_id,
            data=self.data,
            metadata=self.metadata,
            errors=(*self.errors, error_message),
        )
