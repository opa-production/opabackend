"""
Migration 003 — Fix CARD enum value case.

Migration m001 added 'card' (lowercase) to the paymentmethodtype PostgreSQL enum,
but SQLAlchemy uses the Python enum member's .name (uppercase) when writing to
native PostgreSQL enum columns. The existing values MPESA, VISA, MASTERCARD are
stored as uppercase names in PostgreSQL, so CARD must also be uppercase.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m003_fix_card_enum_case")
async def m003_fix_card_enum_case(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(
            "ALTER TYPE paymentmethodtype ADD VALUE IF NOT EXISTS 'CARD'"
        ))
