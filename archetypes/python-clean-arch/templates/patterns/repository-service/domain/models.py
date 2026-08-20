"""Domain models for Repository-Service pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Entity:
    """Immutable domain entity representing stored data.

    Attributes:
        entity_id: Primary unique key.
        payload: Stored entity attributes and payload data.
        created_at: Entity creation timestamp in UTC.
        updated_at: Entity last updated timestamp in UTC.
        is_active: Whether the entity is currently active in the domain lifecycle.
    """

    entity_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True
