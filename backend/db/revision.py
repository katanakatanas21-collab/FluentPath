"""The Alembic revision the application requires.

This is the one place that names the revision the running code is built
against. Both the JSON importer and the PostgreSQL persistence runtime read it,
so a new migration cannot be adopted by one and silently missed by the other.
Keeping it here rather than in either caller is what makes that guarantee.
"""

from __future__ import annotations

#: Revision the running code expects. Bump only together with the migration.
EXPECTED_SCHEMA_REVISION = "0003_unknown_history_times"

#: Revision history table maintained by Alembic itself.
VERSION_TABLE = "alembic_version"