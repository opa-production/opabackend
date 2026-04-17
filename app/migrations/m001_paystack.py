"""
Migration 001 — Replace Pesapal with Paystack.

Changes:
- Adds 'card' value to the paymentmethodtype PostgreSQL enum.
- Drops all pesapal_* columns from the payments table.
- Adds paystack_reference, paystack_authorization_code, paystack_channel,
  paystack_card_last4, and paystack_card_brand columns to the payments table.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m001_paystack_replace_pesapal")
async def m001_paystack_replace_pesapal(engine: AsyncEngine) -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside an explicit transaction on older
    # PostgreSQL versions, so we use autocommit mode for that single statement.
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(
            "ALTER TYPE paymentmethodtype ADD VALUE IF NOT EXISTS 'card'"
        ))

    # Everything else runs in a single transaction.
    async with engine.begin() as conn:
        # Add Paystack tracking columns
        await conn.execute(text("""
            ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS paystack_reference        VARCHAR(100),
                ADD COLUMN IF NOT EXISTS paystack_authorization_code VARCHAR(100),
                ADD COLUMN IF NOT EXISTS paystack_channel          VARCHAR(50),
                ADD COLUMN IF NOT EXISTS paystack_card_last4       VARCHAR(4),
                ADD COLUMN IF NOT EXISTS paystack_card_brand       VARCHAR(50)
        """))

        # Unique constraint on paystack_reference (NULL values are not considered duplicates)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_payments_paystack_reference'
                ) THEN
                    ALTER TABLE payments
                        ADD CONSTRAINT uq_payments_paystack_reference
                        UNIQUE (paystack_reference);
                END IF;
            END $$
        """))

        # Index for fast webhook/status lookups
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_payments_paystack_reference
            ON payments (paystack_reference)
        """))

        # Drop old Pesapal columns
        await conn.execute(text("""
            ALTER TABLE payments
                DROP COLUMN IF EXISTS pesapal_order_tracking_id,
                DROP COLUMN IF EXISTS pesapal_merchant_reference,
                DROP COLUMN IF EXISTS pesapal_confirmation_code,
                DROP COLUMN IF EXISTS pesapal_payment_method,
                DROP COLUMN IF EXISTS pesapal_payment_account
        """))
