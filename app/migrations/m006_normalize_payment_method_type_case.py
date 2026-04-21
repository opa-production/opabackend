"""
Migration 006 — Normalize payment_methods.method_type to lowercase.

m003 added 'CARD' (uppercase) to the enum and some rows were written with
uppercase values before the ORM was fixed to use enum values instead of names.
SQLAlchemy now maps only lowercase values, so uppercase rows cause LookupError
on read. This migration downcases any existing uppercase rows in-place.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m006_normalize_payment_method_type_case")
async def m006_normalize_payment_method_type_case(engine: AsyncEngine) -> None:
    # Step 1: ADD VALUE cannot run inside a transaction block
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for value in ("mpesa", "visa", "mastercard"):
            await conn.execute(text(
                f"ALTER TYPE paymentmethodtype ADD VALUE IF NOT EXISTS '{value}'"
            ))

    # Step 2: Normalize existing uppercase rows to lowercase
    async with engine.begin() as conn:
        for upper, lower in [("MPESA", "mpesa"), ("CARD", "card"), ("VISA", "visa"), ("MASTERCARD", "mastercard")]:
            await conn.execute(text(
                "UPDATE payment_methods "
                "SET method_type = CAST(:lower AS paymentmethodtype) "
                "WHERE method_type::text = :upper"
            ), {"lower": lower, "upper": upper})
