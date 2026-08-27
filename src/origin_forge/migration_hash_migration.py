from __future__ import annotations

from .migrations import Migration

MIGRATION_HASH_MIGRATION = Migration(
    28,
    r"""
ALTER TABLE schema_migrations ADD COLUMN migration_hash TEXT;
""",
)
