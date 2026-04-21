"""
Migration 004 — Replace Veriff with Dojah on client_kycs and host_kycs.

- Drops veriff_session_id (Veriff is fully removed).
- Adds dojah_reference_id, verified_name, verified_dob, verified_gender, face_match_score.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m004_dojah_kyc")
async def m004_dojah_kyc(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table in ("client_kycs", "host_kycs"):
            await conn.execute(text(
                f"ALTER TABLE {table} DROP COLUMN IF EXISTS veriff_session_id"
            ))
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS dojah_reference_id VARCHAR(255)"
            ))
            await conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_dojah_reference_id ON {table}(dojah_reference_id)"
            ))
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verified_name VARCHAR(255)"
            ))
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verified_dob DATE"
            ))
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verified_gender VARCHAR(20)"
            ))
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS face_match_score FLOAT"
            ))
