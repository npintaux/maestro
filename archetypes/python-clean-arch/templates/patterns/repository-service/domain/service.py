"""Domain service orchestrating entity retrieval and business validations."""

from __future__ import annotations

from .exceptions import DuplicateEntityError, EntityNotFoundError, InactiveEntityError
from .models import Entity
from .ports import EntityRepository


class LookupService:
    """Domain service managing entity lifecycle and lookup logic."""

    def __init__(self, repository: EntityRepository) -> None:
        """Initializes the service with a repository port.

        Args:
            repository: Injected EntityRepository implementation.
        """
        self._repository = repository

    def get_entity(self, entity_id: str) -> Entity:
        """Resolves an active entity by ID.

        Args:
            entity_id: The unique identifier of the entity.

        Returns:
            The resolved Entity.

        Raises:
            EntityNotFoundError: If the entity does not exist.
            InactiveEntityError: If the entity exists but is deactivated.
        """
        entity = self._repository.get_by_id(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"Entity '{entity_id}' not found.")
        if not entity.is_active:
            raise InactiveEntityError(f"Entity '{entity_id}' is deactivated.")
        return entity

    def create_entity(self, entity: Entity) -> Entity:
        """Persists a new entity in the repository.

        Args:
            entity: The entity instance to create.

        Returns:
            The persisted Entity.

        Raises:
            DuplicateEntityError: If an entity with the same ID already exists.
        """
        existing = self._repository.get_by_id(entity.entity_id)
        if existing is not None:
            raise DuplicateEntityError(f"Entity '{entity.entity_id}' already exists.")
        self._repository.save(entity)
        return entity
