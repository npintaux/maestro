"""In-memory test fake adapter implementing the EntityRepository port."""

from __future__ import annotations

from ..domain.models import Entity
from ..domain.ports import EntityRepository


class InMemoryEntityRepository(EntityRepository):
    """In-memory dictionary-backed implementation of EntityRepository for testing."""

    def __init__(self, initial_entities: dict[str, Entity] | None = None) -> None:
        """Initializes the memory repository with an optional initial state.

        Args:
            initial_entities: Optional mapping of entity ID to Entity objects.
        """
        self._storage: dict[str, Entity] = dict(initial_entities or {})

    def get_by_id(self, entity_id: str) -> Entity | None:
        """Fetch entity from memory by ID.

        Args:
            entity_id: Unique entity identifier.

        Returns:
            The Entity if found, or None if not found.
        """
        return self._storage.get(entity_id)

    def save(self, entity: Entity) -> None:
        """Persist or overwrite an entity in memory.

        Args:
            entity: The entity instance to save.
        """
        self._storage[entity.entity_id] = entity

    def delete(self, entity_id: str) -> bool:
        """Delete an entity from memory by ID.

        Args:
            entity_id: Unique entity identifier.

        Returns:
            True if entity was present and deleted, False otherwise.
        """
        if entity_id in self._storage:
            del self._storage[entity_id]
            return True
        return False
