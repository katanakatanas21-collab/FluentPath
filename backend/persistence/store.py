"""The persistence contract used by the API layer.

``server.py`` keeps its historic whole-store programming model: every domain
helper reads one logical store into plain dictionaries, mutates them, and writes
the store back. A ``Store`` reproduces that contract on top of a different
medium, so the API responses, authorization checks, and domain rules do not have
to change when the storage engine does.

Records are plain ``dict`` objects keyed exactly like the JSON store files.
Backends must never hand ORM instances to the API layer.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Callable, Iterable, Mapping

from persistence.errors import DataStoreError

# The fourteen logical stores, in the order the importer validates them.
STORE_NAMES: tuple[str, ...] = (
    "students",
    "courses",
    "homework",
    "submissions",
    "classes",
    "community_posts",
    "community_replies",
    "conversations",
    "messages",
    "reports",
    "notifications",
    "ai_sessions",
    "ai_messages",
    "ai_usage",
)

STORE_FILENAMES: Mapping[str, str] = {name: f"{name}.json" for name in STORE_NAMES}

PathResolver = Callable[[str], "Path | None"]


class Store(abc.ABC):
    """Read/write access to the logical stores."""

    #: Backend identifier used in diagnostics and start-up logging.
    name: str = "abstract"

    @abc.abstractmethod
    async def read(self, store_name: str, *, path: Path | None = None) -> list[dict]:
        """Return every record of a logical store, or ``[]`` when it is empty.

        ``path`` is an explicit file location supplied by the caller. Only file
        backends can honour it; other backends ignore it.
        """

    @abc.abstractmethod
    async def write(self, store_name: str, records: list[dict], *, path: Path | None = None) -> None:
        """Make a logical store hold exactly ``records``.

        ``path`` carries the same meaning as in :meth:`read`.
        """

    async def check_health(self) -> None:
        """Verify the backend can serve a read, without changing anything.

        Used by the readiness probe. Returning normally means the backend is
        reachable; any failure is raised as :class:`DataStoreError` so the API
        layer can answer non-2xx without inspecting the cause.
        """
        raise DataStoreError("This backend cannot report readiness.")

    def path_for(self, store_name: str) -> Path | None:
        """Return the file backing a store, when the backend uses files.

        The API layer uses this to tell a store path apart from an unrelated
        scratch path. Backends without files return ``None`` so that no path is
        ever treated as a store.
        """
        return None

    async def revoke_token(self, token: str, user_id: str, expires_at) -> None:
        """Record a durably revoked access token.

        Tokens are never stored verbatim; implementations persist a one-way
        digest. Backends without durable revocation may ignore this.
        """

    async def token_is_revoked(self, token: str) -> bool:
        """Return whether a token was revoked by a previous process."""
        return False

    async def close(self) -> None:
        """Release backend resources."""
        return None

    def validate_store_name(self, store_name: str) -> str:
        if store_name not in STORE_NAMES:
            raise KeyError(store_name)
        return store_name


def normalize_records(store_name: str, records: Iterable[dict]) -> list[dict]:
    """Copy records into fresh dicts so backends cannot mutate caller state."""
    if store_name not in STORE_NAMES:
        raise KeyError(store_name)
    normalized: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError(f"{store_name} records must be objects")
        normalized.append(dict(record))
    return normalized