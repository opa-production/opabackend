"""
Migration 012 — Secondary contact verification fields on clients.

Adds columns to support the secondary-contact verification flow:
  1. Client enters secondary contact phone + official names (stored immediately).
  2. Client enters secondary contact ID number → backend calls Gava Connect,
     compares returned name with entered names, marks verified/failed.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m012_secondary_contact")
async def m012_secondary_contact(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_phone VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_names VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_id_number VARCHAR(100)"
        ))
        # not_started | pending | verified | failed
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_status VARCHAR(20) DEFAULT 'not_started'"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_official_name VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_kra_pin VARCHAR(20)"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_matched_names INT DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE clients "
            "ADD COLUMN IF NOT EXISTS secondary_contact_verified_at TIMESTAMPTZ"
        ))
