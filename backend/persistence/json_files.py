"""JSON store file input/output.

This is the historic Fluent Path store format: one UTF-8 JSON array per logical
store, replaced atomically so a reader never observes a partial write. It is the
development and automated-test backend, and the reference definition of what a
"record" is.
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
import time
from pathlib import Path

from persistence.errors import DataStoreError

STORE_REPLACE_ATTEMPTS = 5
STORE_REPLACE_BACKOFF_SECONDS = 0.02
# ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION and ERROR_LOCK_VIOLATION are raised when a
# scanner, indexer or other process momentarily holds the store file open. They are
# transient: the target is untouched and the temporary file is still intact, so the same
# atomic replace can simply be retried.
TRANSIENT_STORE_REPLACE_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.EAGAIN, errno.EBUSY})
TRANSIENT_STORE_REPLACE_WINERRORS = frozenset({5, 32, 33})


def read_json_list(file_path) -> list[dict]:
    """Read one store file, treating a missing file as an empty store."""
    path = Path(file_path)
    try:
        with open(path, "r", encoding="utf-8") as file:
            records = json.load(file)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        raise DataStoreError("Persistent data could not be read.") from None

    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise DataStoreError("Persistent data has an invalid structure.")
    return records


def _replace_store_file(temporary_path: Path, path: Path) -> None:
    """Atomically publish a store file, retrying transient sharing failures.

    os.replace is atomic, so a reader never observes a partial write. A single call can
    still fail while another process holds the target open. Retry briefly, then fail
    closed rather than fall back to a non-atomic write.
    """
    for attempt in range(STORE_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary_path, path)
            return
        except OSError as error:
            winerror = getattr(error, "winerror", None)
            transient = (
                getattr(error, "errno", None) in TRANSIENT_STORE_REPLACE_ERRNOS
                or winerror in TRANSIENT_STORE_REPLACE_WINERRORS
            )
            if not transient or attempt + 1 == STORE_REPLACE_ATTEMPTS:
                raise
            time.sleep(STORE_REPLACE_BACKOFF_SECONDS * (attempt + 1))


def write_json_list(file_path, records) -> None:
    """Publish a store file atomically, failing closed without partial damage."""
    path = Path(file_path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        _replace_store_file(temporary_path, path)
    except (OSError, TypeError, ValueError):
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise DataStoreError("Persistent data could not be saved.") from None