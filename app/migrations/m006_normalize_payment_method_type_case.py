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
    async with engine.begin() as conn:
        # Compare method_type as raw text (::text) so we don't CAST the uppercase
        # value through the enum — uppercase variants may not all be valid enum values.
        # Only the SET side needs a valid enum cast.
        for upper, lower in [("CARD", "card"), ("MPESA", "mpesa"), ("VISA", "visa"), ("MASTERCARD", "mastercard")]:
            await conn.execute(text(
                "UPDATE payment_methods "
                "SET method_type = CAST(:lower AS paymentmethodtype) "
                "WHERE method_type::text = :upper"
            ), {"lower": lower, "upper": upper})
