#!/usr/bin/env python3
"""
Run all database migrations manually.

Usage (from project root on the server):
    source .venv/bin/activate
    python migrate.py

Run this BEFORE restarting the service after each deploy that includes new migrations.
The server startup no longer runs migrations automatically.
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

from dotenv import load_dotenv
load_dotenv()

from app.database import engine

# Register all migrations in order
import app.migrations.m001_paystack                             # noqa: F401
import app.migrations.m002_clear_stale_push_tokens             # noqa: F401
import app.migrations.m003_fix_card_enum_case                  # noqa: F401
import app.migrations.m004_dojah_kyc                           # noqa: F401
import app.migrations.m005_perf_indexes                        # noqa: F401
import app.migrations.m006_normalize_payment_method_type_case  # noqa: F401
import app.migrations.m007_schema_patches                      # noqa: F401
import app.migrations.m008_free_trial                          # noqa: F401

from app.migrations.runner import run_pending


async def main() -> None:
    logging.info("=== Starting migration run ===")
    try:
        await run_pending(engine)
    finally:
        await engine.dispose()
    logging.info("=== Migration run complete ===")


if __name__ == "__main__":
    asyncio.run(main())
