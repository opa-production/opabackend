"""
Migration 009 — Add Paystack card-payment columns to host_subscription_payments.

Adds:
  - payment_method  VARCHAR(10)   NOT NULL DEFAULT 'mpesa'   (mpesa | card)
  - paystack_reference             VARCHAR(200) UNIQUE
  - paystack_authorization_code    VARCHAR(200)
  - paystack_channel               VARCHAR(50)
  - paystack_card_last4            VARCHAR(10)
  - paystack_card_brand            VARCHAR(50)

Also widens external_reference from VARCHAR(80) → VARCHAR(120) to fit H-SUB-CARD-* refs.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m009_host_sub_paystack")
async def m009_host_sub_paystack(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS payment_method VARCHAR(10) NOT NULL DEFAULT 'mpesa'"
        ))
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS paystack_reference VARCHAR(200)"
        ))
        # Unique index (IF NOT EXISTS avoids error on re-run)
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_host_sub_payments_paystack_ref "
            "ON host_subscription_payments (paystack_reference) "
            "WHERE paystack_reference IS NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS paystack_authorization_code VARCHAR(200)"
        ))
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS paystack_channel VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS paystack_card_last4 VARCHAR(10)"
        ))
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ADD COLUMN IF NOT EXISTS paystack_card_brand VARCHAR(50)"
        ))
        # Widen external_reference to fit H-SUB-CARD-<id>-<hex> references
        await conn.execute(text(
            "ALTER TABLE host_subscription_payments "
            "ALTER COLUMN external_reference TYPE VARCHAR(120)"
        ))
