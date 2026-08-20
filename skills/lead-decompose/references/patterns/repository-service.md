# Pattern 2: Repository-Service (CRUD / Key-Value / Query)

> **Computational Shape**: Data Retrieval / Persistence / Direct Key-Value Lookup.  
> **Applicability**: Redirect resolvers (e.g. `GET /v1/r/{code}`), metadata lookups, user profile queries, CRUD operations without complex branching.

---

## 1. Architecture Overview
Decouples domain business operations from underlying storage (Firestore, Cloud SQL, Spanner, Redis) via a pure `Repository(abc.ABC)` port, orchestrated by a lightweight domain `Service`. Avoids artificial Rule ABC ceremony for simple data access.

```
Caller ──▶ [ Entrypoint / Router ] ──▶ [ Domain Service ] ──▶ [ Repository ABC ] ──▶ [ Adapter / Datastore ]
```

---

## 2. Domain Models (`src/domain/models.py`)
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Entity:
    """Immutable domain entity."""

    id: str
    target_value: str
    created_at: datetime
    is_active: bool = True
    metadata: Optional[dict[str, str]] = None
```

---

## 3. Repository ABC Port (`src/domain/repository.py`)
```python
import abc
from typing import Optional
from .models import Entity


class EntityRepository(abc.ABC):
    """Abstract port for entity persistence and retrieval."""

    @abc.abstractmethod
    def get_by_id(self, entity_id: str) -> Optional[Entity]:
        """Fetch entity by primary key. Returns None if not found."""
        ...

    @abc.abstractmethod
    def save(self, entity: Entity) -> None:
        """Persist or update entity."""
        ...

    @abc.abstractmethod
    def delete(self, entity_id: str) -> bool:
        """Delete entity by key. Returns True if deleted, False if not found."""
        ...
```

---

## 4. Domain Service (`src/domain/service.py`)
```python
from typing import Optional
from .exceptions import EntityNotFoundError, InactiveEntityError
from .models import Entity
from .repository import EntityRepository


class LookupService:
    """Domain service handling entity retrieval and lifecycle validation."""

    def __init__(self, repository: EntityRepository) -> None:
        self._repository = repository

    def resolve(self, entity_id: str) -> Entity:
        """Resolve active entity by ID or raise explicit domain errors."""
        entity: Optional[Entity] = self._repository.get_by_id(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"Entity '{entity_id}' not found.")
        if not entity.is_active:
            raise InactiveEntityError(f"Entity '{entity_id}' is deactivated.")
        return entity
```

---

## 5. Test Focus
- **Found / active**: `resolve` returns the entity for a present, active record.
- **Not found → `EntityNotFoundError`**: mapped to `404`.
- **Inactive → `InactiveEntityError`**: distinct domain error (e.g. `410 Gone` / `404`), not conflated with "not found".
- **Fake repository**: drive all cases through an in-memory `EntityRepository` fake; the real adapter is covered separately at the boundary.
