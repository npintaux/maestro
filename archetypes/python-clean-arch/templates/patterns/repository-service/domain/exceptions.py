"""Domain exceptions for Repository-Service pattern."""

from __future__ import annotations


class DomainError(Exception):
    """Base exception for all domain-specific errors."""


class EntityNotFoundError(DomainError):
    """Raised when an entity requested by ID does not exist in the repository."""


class InactiveEntityError(DomainError):
    """Raised when an operation is attempted on an entity that is deactivated/expired."""


class DuplicateEntityError(DomainError):
    """Raised when attempting to create an entity that already exists."""
