"""Unit test template: genuine arrange-act-assert against an isolated subject.

The Specialist Implementer replaces ``_ExampleService`` with the real domain
subject under test. Every test must assert on an *observed* value or an
*actually-raised* exception. Never write ``assert True`` (or any literal-against-
itself tautology): it can never fail, proves nothing, and is rejected by Gate 8
(``audit_test_coverage.py``). Aim for 100% branch coverage of the subject.
"""

from __future__ import annotations

import pytest


class _ExampleService:
    """Illustrative pure-domain subject. Replace with the real subsystem class."""

    def apply_discount(self, price: int, percent: int) -> int:
        """Return ``price`` reduced by ``percent``; reject out-of-range input."""
        if not 0 <= percent <= 100:
            raise ValueError("percent must be within [0, 100].")
        return price - (price * percent // 100)


def test_unit_happy_path() -> None:
    """The primary success path returns the correctly computed value."""
    result = _ExampleService().apply_discount(price=200, percent=25)
    assert result == 150


def test_unit_exception_branch() -> None:
    """Out-of-range input raises the domain's explicit ValueError."""
    with pytest.raises(ValueError, match=r"percent must be within"):
        _ExampleService().apply_discount(price=200, percent=150)
