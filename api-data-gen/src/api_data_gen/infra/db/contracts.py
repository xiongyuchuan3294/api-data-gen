from __future__ import annotations

from typing import Any, Protocol


class QueryClient(Protocol):
    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        ...

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        ...

    def resolve_table_location(self, table_name: str) -> tuple[str, str]:
        ...
