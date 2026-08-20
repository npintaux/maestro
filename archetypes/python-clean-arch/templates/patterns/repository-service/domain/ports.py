"""Abstract repository port defining the persistence interface."""

from __future__ import annotations

import abc

from .models import Entity


class EntityRepository(abc.ABC):
    """Abstract port for entity persistence and retrieval."""

    @abc.abstractmethod
    def get_by_id(self, entity_id: str) -> Entity | None:
        """Fetch entity by primary key.

        Args:
            entity_id: Unique entity identifier.

        Returns:
            The Entity if found, or None if not found.
        """
        ...

    @abc.abstractmethod
    def save(self, entity: Entity) -> None:
        """Persist or update an entity.

        Args:
            entity: The entity instance to save.
        """
        ...

    @abc.abstractmethod
    def delete(self, entity_id: str) -> bool:
        """Delete an entity by primary key.

        Args:
            entity_id: Unique entity identifier.

        Returns:
            True if entity was deleted, False if entity did not exist.
        """
        ...
