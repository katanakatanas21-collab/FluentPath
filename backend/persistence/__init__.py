"""Persistence boundary for the Fluent Path API.

``server.py`` reads and writes logical stores through this package instead of
touching files directly, so the storage engine can change without changing any
API behaviour.

* ``persistence.runtime`` selects and configures the backend.
* ``persistence.json_backend`` keeps the historic JSON file behaviour for
  development and the automated suite.
* ``persistence.postgres_backend`` serves the normalized PostgreSQL schema used
  by staging and production.
* ``persistence.records`` translates between store records and database rows.
* ``persistence.errors.DataStoreError`` is what the API layer maps to a 503.
"""

from persistence.errors import DataStoreError, PersistenceConfigurationError
from persistence.runtime import (
    BACKEND_NAMES,
    JSON_BACKEND,
    POSTGRES_BACKEND,
    active_backend_name,
    active_store,
    build_store,
    check_store_health,
    configure,
    configure_from_environment,
    default_store_paths,
    read_store,
    resolve_backend_name,
    revoke_token,
    shutdown,
    store_name_for_path,
    token_is_revoked,
    write_store,
)
from persistence.store import (
    STORE_FILENAMES,
    STORE_NAMES,
    PathResolver,
    Store,
    normalize_records,
)

__all__ = [
    "BACKEND_NAMES",
    "DataStoreError",
    "JSON_BACKEND",
    "POSTGRES_BACKEND",
    "PersistenceConfigurationError",
    "STORE_FILENAMES",
    "STORE_NAMES",
    "PathResolver",
    "Store",
    "active_backend_name",
    "active_store",
    "build_store",
    "check_store_health",
    "configure",
    "configure_from_environment",
    "default_store_paths",
    "normalize_records",
    "read_store",
    "resolve_backend_name",
    "revoke_token",
    "shutdown",
    "store_name_for_path",
    "token_is_revoked",
    "write_store",
]