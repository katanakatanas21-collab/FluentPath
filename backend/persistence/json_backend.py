"""JSON file backend: the development and automated-test store."""

from __future__ import annotations

import asyncio
from pathlib import Path

from persistence.errors import DataStoreError
from persistence.json_files import read_json_list, write_json_list
from persistence.store import STORE_FILENAMES, PathResolver, Store, normalize_records


class JsonStoreBackend(Store):
    """Serves the logical stores from JSON files.

    ``path_resolver`` is consulted on every call so that tests which repoint the
    store module paths at a temporary directory are honoured without re-wiring
    the backend.
    """

    name = "json"

    def __init__(self, path_resolver: PathResolver):
        self._path_resolver = path_resolver

    def _path(self, store_name: str, explicit: Path | None = None) -> Path:
        if explicit is not None:
            return Path(explicit)
        path = self._path_resolver(store_name)
        if path is None:
            raise DataStoreError(f"No JSON path is configured for {store_name}")
        return Path(path)

    def path_for(self, store_name: str) -> Path | None:
        path = self._path_resolver(store_name)
        return None if path is None else Path(path)

    async def read(self, store_name: str, *, path: Path | None = None) -> list[dict]:
        self.validate_store_name(store_name)
        return await asyncio.to_thread(read_json_list, self._path(store_name, path))

    async def write(self, store_name: str, records, *, path: Path | None = None) -> None:
        self.validate_store_name(store_name)
        payload = normalize_records(store_name, records)
        await asyncio.to_thread(write_json_list, self._path(store_name, path), payload)

    async def check_health(self) -> None:
        """Confirm every store path resolves and the directory is readable.

        Reads nothing and writes nothing: it verifies the paths the process was
        configured with, which is what actually goes wrong when the JSON runtime
        is misconfigured.
        """
        for name in STORE_FILENAMES:
            path = self.path_for(name)
            if path is None:
                raise DataStoreError(f"No JSON path is configured for {name}")
            if not path.parent.is_dir():
                raise DataStoreError("The JSON store directory is not available.")

    def describe(self) -> str:
        """Non-secret summary for start-up logging."""
        return "json: " + ", ".join(
            f"{name}->{self._path(name)}" if self.path_for(name) is not None else f"{name}->unset"
            for name in sorted(STORE_FILENAMES)
        )