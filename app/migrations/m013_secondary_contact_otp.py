"""
Migration 013 — Replace Gava Connect columns with SMS OTP columns on clients.

Drops:  secondary_contact_id_number, secondary_contact_official_name,
        secondary_contact_kra_pin, secondary_contact_matched_names
Adds:   secondary_contact_otp, secondary_contact_otp_expires_at
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m013_secondary_contact_otp")
async def m013_secondary_contact_otp(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for col in [
            "secondary_contact_id_number",
            "secondary_contact_official_name",
            "secondary_contact_kra_pin",
            "secondary_contact_matched_names",
        ]:
            await conn.execute(text(f"ALTER TABLE clients DROP COLUMN IF EXISTS {col}"))

        await conn.execute(text(
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS secondary_contact_otp VARCHAR(10)"
        ))
        await conn.execute(text(
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS secondary_contact_otp_expires_at TIMESTAMPTZ"
        ))
