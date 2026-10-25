"""Bounded metadata pagination shared by credential management services."""

from collections.abc import Callable, Iterable
from typing import Protocol


class PageQuerySet[Item](Protocol):
    """Small queryset surface required by the bounded paginator."""

    def count(self) -> int: ...

    def __getitem__(self, key: slice) -> Iterable[Item]: ...


def credential_page[Item](
    queryset: PageQuerySet[Item],
    *,
    offset: int = 0,
    limit: int = 50,
    project: Callable[[Item], object] | None = None,
) -> dict[str, object]:
    """Fetch at most one page; no verifier or raw credential belongs in a page."""
    if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 100000 or not 1 <= limit <= 200:
        raise ValueError("Invalid credential pagination")
    count = queryset.count()
    projector = project if project is not None else lambda value: value
    return {
        "count": count,
        "next_offset": offset + limit if offset + limit < count else None,
        "results": [projector(item) for item in queryset[offset : offset + limit]],
    }
