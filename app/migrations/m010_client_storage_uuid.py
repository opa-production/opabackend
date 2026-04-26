"""
Migration 010 — Add storage_uuid to clients table.

Adds a stable UUID column used as the Supabase Storage folder name for each client.
Integer IDs can be recycled after deletion; UUIDs never are, preventing new users
from inheriting orphaned storage files of deleted accounts.

Backfills existing rows with gen_random_uuid() so all current clients get a UUID.
New clients get one automatically via the ORM default (uuid.uuid4()).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m010_client_storage_uuid")
async def m010_client_storage_uuid(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS storage_uuid VARCHAR(36) UNIQUE"
        ))
        # Backfill existing rows that have no UUID yet
        await conn.execute(text(
            "UPDATE clients SET storage_uuid = gen_random_uuid()::text "
            "WHERE storage_uuid IS NULL"
        ))
