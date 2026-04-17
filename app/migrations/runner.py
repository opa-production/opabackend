"""
Lightweight migration runner. Migrations are plain async functions identified by a unique name.
Each migration runs exactly once; completion is recorded in the `schema_migrations` table.
Called from app startup in main.py.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_MIGRATIONS: list = []


def migration(name: str):
    """Decorator to register a migration function."""
    def decorator(fn):
        _MIGRATIONS.append((name, fn))
        return fn
    return decorator


async def run_pending(engine: AsyncEngine) -> None:
    """Create tracking table if missing, then run any unexecuted migrations in order."""
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

    for name, fn in _MIGRATIONS:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE name = :n"), {"n": name}
            )
            already_applied = row.fetchone() is not None

        if already_applied:
            logger.info("[MIGRATION] Skipping (already applied): %s", name)
            continue

        logger.info("[MIGRATION] Running: %s", name)
        try:
            await fn(engine)
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": name}
                )
            logger.info("[MIGRATION] Done: %s", name)
        except Exception:
            logger.exception("[MIGRATION] FAILED: %s", name)
            raise
