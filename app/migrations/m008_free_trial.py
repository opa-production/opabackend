"""
Migration 008 — Add free_trial_activated_at column to hosts table.

Tracks whether a host has used their one-time free trial.
NULL  = trial not yet used.
NOT NULL = trial was activated on that timestamp (used up, cannot be reused).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m008_free_trial")
async def m008_free_trial(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE hosts "
            "ADD COLUMN IF NOT EXISTS free_trial_activated_at TIMESTAMP WITH TIME ZONE"
        ))
