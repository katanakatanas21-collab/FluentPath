"""Storage-layer errors shared by every persistence backend."""

from __future__ import annotations


class DataStoreError(RuntimeError):
    """Raised when persistent data cannot safely be read or written.

    The API layer maps this to a generic 503 so that storage problems never leak
    connection strings, row values, or driver messages to clients.
    """


class PersistenceConfigurationError(RuntimeError):
    """Raised at start-up when the persistence backend selection is unsafe."""


class SchemaVersionMismatch(DataStoreError):
    """Raised when the database is not at the Alembic revision the code expects.

    Deliberately a ``DataStoreError`` subclass, so the existing handler still
    answers 503 ``DATA_STORE_UNAVAILABLE`` and the API contract is unchanged,
    while the specific cause stays available to logs and tests. The message names
    only revisions, never a host, database, role or credential.
    """