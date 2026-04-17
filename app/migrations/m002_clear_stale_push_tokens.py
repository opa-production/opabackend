"""
Migration 002 — Clear all existing push tokens.

All tokens currently in the DB were registered when users tested in Expo Go.
Expo Go tokens show "Expo Go" branding on notifications instead of the app's name/icon.
Wiping them forces every user to re-register a fresh token when they next open the
standalone app, which will be tied to the app's own push credentials.

This migration runs exactly once. Push notifications simply won't fire for users who
haven't reopened the app yet after this migration — that is acceptable and temporary.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m002_clear_stale_push_tokens")
async def m002_clear_stale_push_tokens(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM client_push_tokens"))
        await conn.execute(text("DELETE FROM host_push_tokens"))
