"""
Migration 011 — Add client support conversations.

The support_conversations table was designed for hosts only (host_id NOT NULL UNIQUE).
This migration extends it to support clients as well by:
  1. Making host_id nullable (so a row can belong to a client instead).
  2. Dropping the simple UNIQUE constraint on host_id and replacing it with a
     partial unique index (UNIQUE WHERE host_id IS NOT NULL), preserving the
     one-thread-per-host invariant without blocking client rows.
  3. Adding a nullable client_id FK column with its own partial unique index
     (one thread per client).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m011_client_support")
async def m011_client_support(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # 1. Make host_id nullable
        await conn.execute(text(
            "ALTER TABLE support_conversations "
            "ALTER COLUMN host_id DROP NOT NULL"
        ))

        # 2. Drop the original simple UNIQUE constraint on host_id.
        #    PostgreSQL auto-names it <table>_<col>_key.
        await conn.execute(text(
            "ALTER TABLE support_conversations "
            "DROP CONSTRAINT IF EXISTS support_conversations_host_id_key"
        ))

        # 3. Replace with a partial unique index so the uniqueness invariant
        #    still holds for host rows but doesn't conflict with client rows.
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_support_conv_host_id "
            "ON support_conversations (host_id) "
            "WHERE host_id IS NOT NULL"
        ))

        # 4. Add client_id column
        await conn.execute(text(
            "ALTER TABLE support_conversations "
            "ADD COLUMN IF NOT EXISTS client_id INTEGER "
            "REFERENCES clients(id) ON DELETE SET NULL"
        ))

        # 5. Partial unique index for clients
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_support_conv_client_id "
            "ON support_conversations (client_id) "
            "WHERE client_id IS NOT NULL"
        ))

        # 6. Index for efficient lookups by client_id
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_support_conversations_client_id "
            "ON support_conversations (client_id)"
        ))
