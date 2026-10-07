"""Persistence backend selection and the synchronous call bridge.

Backend selection is decided once, from the environment, and fails closed:

* staging and production always require PostgreSQL, so a JSON file can never
  receive a production write;
* development and test default to JSON, which keeps local work and the automated
  suite free of any database requirement;
* ``FLUENT_PATH_PERSISTENCE`` may request either backend explicitly, except that
  it can never downgrade staging or production to JSON.

The domain helpers in ``server.py`` are synchronous, so store calls are executed
on one long-lived background event loop and waited on from the calling thread.
This keeps every route, response shape and authorization rule exactly as it was
while the storage engine changes underneath. The follow-on is to convert the
endpoints to ``async def`` with a request-scoped session, which removes the
serialization this bridge implies.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Mapping

from db_config import DatabaseConfigurationError, load_database_settings
from persistence.errors import DataStoreError, PersistenceConfigurationError
from persistence.store import STORE_FILENAMES, STORE_NAMES, PathResolver, Store

JSON_BACKEND = "json"
POSTGRES_BACKEND = "postgres"
BACKEND_NAMES = (JSON_BACKEND, POSTGRES_BACKEND)

#: Environments that must never run on file storage.
POSTGRESQL_ONLY_ENVIRONMENTS = frozenset({"staging", "production"})

DEFAULT_OPERATION_TIMEOUT_SECONDS = 30.0


def resolve_backend_name(environ: Mapping[str, str] | None = None) -> str:
    """Decide which backend may serve this process, or refuse to start."""
    env = os.environ if environ is None else environ
    environment = env.get("FLUENT_PATH_ENVIRONMENT", "development").strip().lower()
    requested = env.get("FLUENT_PATH_PERSISTENCE", "").strip().lower()
    if requested and requested not in BACKEND_NAMES:
        raise PersistenceConfigurationError(
            f"FLUENT_PATH_PERSISTENCE must be one of {', '.join(BACKEND_NAMES)}"
        )
    if environment in POSTGRESQL_ONLY_ENVIRONMENTS:
        if requested == JSON_BACKEND:
            raise PersistenceConfigurationError(
                f"{environment} requires the {POSTGRES_BACKEND} persistence backend"
            )
        return POSTGRES_BACKEND
    return requested or JSON_BACKEND


class _LoopBridge:
    """Runs store coroutines on one background event loop."""

    def __init__(self, *, timeout: float = DEFAULT_OPERATION_TIMEOUT_SECONDS):
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            ready = threading.Event()
            thread = threading.Thread(target=self._serve, args=(ready,), name="fluent-path-store", daemon=True)
            self._thread = thread
            thread.start()
            if not ready.wait(timeout=self._timeout):
                raise PersistenceConfigurationError("The persistence event loop did not start")
            if self._loop is None:
                raise PersistenceConfigurationError("The persistence event loop did not start")

    def _serve(self, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    def run(self, coroutine):
        self.start()
        loop = self._loop
        if loop is None:  # pragma: no cover - guarded by start()
            raise DataStoreError("Persistent storage is unavailable.")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=self._timeout)
        except asyncio.TimeoutError:
            future.cancel()
            raise DataStoreError("Persistent storage did not respond in time.") from None
        except DataStoreError:
            raise
        except Exception:
            # Driver errors can carry connection strings and row values. Never let
            # them reach the API layer or the logs.
            raise DataStoreError("Persistent storage failed.") from None

    def stop(self) -> None:
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=self._timeout)


_store: Store | None = None
_bridge: _LoopBridge | None = None
_path_resolver: PathResolver | None = None


def build_store(
    environ: Mapping[str, str] | None = None,
    *,
    path_resolver: PathResolver | None = None,
) -> Store:
    """Construct the backend this process is configured to use.

    Pure by design: it installs nothing. Installing the store and its path
    resolver is ``configure``'s job, so building a throwaway store with a
    throwaway resolver cannot disturb the running process.
    """
    backend = resolve_backend_name(environ)
    if backend == POSTGRES_BACKEND:
        from persistence.postgres_backend import PostgresStoreBackend

        try:
            settings = load_database_settings(environ)
        except DatabaseConfigurationError as error:
            raise PersistenceConfigurationError(str(error)) from None
        return PostgresStoreBackend(settings)
    if path_resolver is None:
        raise PersistenceConfigurationError("The JSON backend requires store path resolution")
    from persistence.json_backend import JsonStoreBackend

    return JsonStoreBackend(path_resolver)


def configure(
    store: Store,
    *,
    timeout: float = DEFAULT_OPERATION_TIMEOUT_SECONDS,
    path_resolver: PathResolver | None = None,
) -> Store:
    """Install the process-wide store and its bridge."""
    global _store, _bridge, _path_resolver
    # Retained whichever backend is installed. A PostgreSQL store has no file of
    # its own, so this mapping is the only thing that can still tell a product
    # store path apart from an unrelated scratch file. It is never cleared,
    # because clearing it would make every product store path unresolvable on a
    # PostgreSQL-only runtime.
    if path_resolver is not None:
        _path_resolver = path_resolver
    if _bridge is not None:
        _bridge.stop()
    _bridge = _LoopBridge(timeout=timeout)
    _store = store
    return store


def configure_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    path_resolver: PathResolver | None = None,
    timeout: float = DEFAULT_OPERATION_TIMEOUT_SECONDS,
) -> Store:
    return configure(build_store(environ, path_resolver=path_resolver),
                     timeout=timeout, path_resolver=path_resolver)


def active_store() -> Store:
    if _store is None:
        raise PersistenceConfigurationError("No persistence backend is configured")
    return _store


def active_backend_name() -> str:
    return active_store().name


def _run(coroutine):
    if _bridge is None:
        raise PersistenceConfigurationError("No persistence backend is configured")
    return _bridge.run(coroutine)


def check_store_health() -> None:
    if _store is None:
        raise PersistenceConfigurationError("No persistence backend is configured")
    _run(_store.check_health())


def read_store(store_name: str, *, path=None) -> list[dict]:
    if store_name not in STORE_NAMES:
        # Fail here rather than inside the store, so a caller mistake cannot be
        # reported to a client as a storage outage.
        raise KeyError(store_name)
    return _run(active_store().read(store_name, path=path))


def write_store(store_name: str, records, *, path=None) -> None:
    if store_name not in STORE_NAMES:
        raise KeyError(store_name)
    return _run(active_store().write(store_name, records, path=path))


def revoke_token(token: str, user_id: str, expires_at) -> None:
    return _run(active_store().revoke_token(token, user_id, expires_at))


def token_is_revoked(token: str) -> bool:
    return bool(_run(active_store().token_is_revoked(token)))


def store_name_for_path(file_path) -> str | None:
    """Return the store a path refers to, or ``None`` for unrelated scratch files.

    A store file keeps its filename whichever directory it lives in, because
    tests repoint the module paths at temporary directories.

    Resolution deliberately prefers the process-wide path resolver over the
    active backend's ``path_for``. A PostgreSQL store has no file, so asking it
    for a path answers ``None`` for every store, which made every product store
    path look like unrelated scratch data and silently sent writes to a local
    JSON file. The resolver is backend-independent, so it answers correctly for
    both backends.
    """
    try:
        store = active_store()
    except PersistenceConfigurationError:
        return None
    candidate = Path(file_path)
    for name in STORE_NAMES:
        path = None
        if _path_resolver is not None:
            try:
                path = _path_resolver(name)
            except Exception:
                path = None
        if path is None:
            try:
                path = store.path_for(name)
            except Exception:
                path = None
        if path is None:
            continue
        path = Path(path)
        if candidate == path or candidate.name == path.name:
            return name
    # Last resort, still backend-independent: every store has one canonical
    # filename. Without this, a runtime whose resolver was never installed would
    # classify product store paths as scratch data and write JSON files.
    for name in STORE_NAMES:
        if candidate.name == STORE_FILENAMES.get(name):
            return name
    return None


def default_store_paths(data_dir: Path) -> dict[str, Path]:
    return {name: Path(data_dir) / filename for name, filename in STORE_FILENAMES.items()}


def shutdown() -> None:
    """Release the store and stop the bridge."""
    global _store, _bridge
    store, bridge = _store, _bridge
    _store, _bridge = None, None
    if bridge is not None:
        try:
            if store is not None:
                bridge.run(store.close())
        except DataStoreError:
            pass
        bridge.stop()