"""
Migration 007 — Consolidate all inline ALTER TABLE patches from main.py startup.

Previously these ran on every startup via migrate_database(). Moving them here means
they run exactly once (tracked in schema_migrations) and never again block startup.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m007_schema_patches")
async def m007_schema_patches(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # ── hosts ─────────────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS cover_image_url VARCHAR(500)",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS id_document_url VARCHAR(500)",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS license_document_url VARCHAR(500)",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS google_id VARCHAR(255)",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS id_number VARCHAR(100)",
        ]:
            await conn.execute(text(ddl))

        # ── clients ───────────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS id_document_url VARCHAR(500)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS license_document_url VARCHAR(500)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS date_of_birth DATE",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS gender VARCHAR(20)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS google_id VARCHAR(255)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS email_notifications_enabled INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS sms_notifications_enabled INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS in_app_notifications_enabled INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS id_number VARCHAR(100)",
        ]:
            await conn.execute(text(ddl))

        # ── cars ──────────────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN DEFAULT FALSE NOT NULL",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS image_urls TEXT",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS cover_image VARCHAR(500)",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS car_images TEXT",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS car_video VARCHAR(500)",
            "ALTER TABLE cars ADD COLUMN IF NOT EXISTS drive_setting VARCHAR(30) DEFAULT 'self_only'",
            # Draft listing columns must be nullable
            "ALTER TABLE cars ALTER COLUMN seats DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN fuel_type DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN transmission DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN color DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN mileage DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN features DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN daily_rate DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN weekly_rate DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN monthly_rate DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN min_rental_days DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN max_rental_days DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN min_age_requirement DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN rules DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN location_name DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN latitude DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN longitude DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN image_urls DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN video_url DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN cover_image DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN car_images DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN car_video DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN rejection_reason DROP NOT NULL",
            "ALTER TABLE cars ALTER COLUMN updated_at DROP NOT NULL",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                await conn.rollback()

        # ── feedbacks ─────────────────────────────────────────────────────────
        await conn.execute(text(
            "ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS is_flagged INTEGER DEFAULT 0 NOT NULL"
        ))

        # ── payments ──────────────────────────────────────────────────────────
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS extension_request_id INTEGER"
        ))

        # ── payment_methods ───────────────────────────────────────────────────
        await conn.execute(text(
            "ALTER TABLE payment_methods ADD COLUMN IF NOT EXISTS client_id INTEGER"
        ))
        try:
            await conn.execute(text(
                "ALTER TABLE payment_methods ALTER COLUMN host_id DROP NOT NULL"
            ))
        except Exception:
            await conn.rollback()

        # ── bookings ──────────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS dropoff_same_as_pickup INTEGER DEFAULT 1 NOT NULL",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS pickup_confirmed_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS dropoff_confirmed_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS push_reminder_10h_sent_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS push_reminder_5h_sent_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS push_reminder_1h_sent_at TIMESTAMP WITH TIME ZONE",
        ]:
            await conn.execute(text(ddl))

        # ── withdrawals ───────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS checkout_request_id VARCHAR(255)",
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS result_code INTEGER",
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS result_desc VARCHAR(500)",
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS mpesa_receipt_number VARCHAR(100)",
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS mpesa_phone VARCHAR(20)",
            "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS mpesa_transaction_date VARCHAR(50)",
        ]:
            await conn.execute(text(ddl))

        # ── car_blocked_dates ─────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE car_blocked_dates ADD COLUMN IF NOT EXISTS blocked_date DATE",
            "ALTER TABLE car_blocked_dates ADD COLUMN IF NOT EXISTS reason TEXT",
            "ALTER TABLE car_blocked_dates ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE",
        ]:
            await conn.execute(text(ddl))
        await conn.execute(text(
            "UPDATE car_blocked_dates SET blocked_date = DATE(start_date) WHERE blocked_date IS NULL"
        ))

        # ── client_wallets ────────────────────────────────────────────────────
        for ddl in [
            "ALTER TABLE client_wallets ADD COLUMN IF NOT EXISTS balance_xlm VARCHAR(50) DEFAULT '0'",
            "ALTER TABLE client_wallets ADD COLUMN IF NOT EXISTS balance_usdc VARCHAR(50) DEFAULT '0'",
            "ALTER TABLE client_wallets ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMP WITH TIME ZONE",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                await conn.rollback()

        # ── car media data migration ───────────────────────────────────────────
        # Copy image_urls → car_images and set cover_image for legacy rows
        await conn.execute(text("""
            UPDATE cars
            SET
                car_images = image_urls,
                cover_image = COALESCE(
                    cover_image,
                    CASE
                        WHEN image_urls IS NOT NULL AND image_urls LIKE '[%'
                        THEN TRIM(BOTH '"' FROM SPLIT_PART(TRIM(LEADING '[' FROM image_urls), ',', 1))
                        ELSE image_urls
                    END
                )
            WHERE image_urls IS NOT NULL
              AND car_images IS NULL
        """))
        # Copy video_url → car_video for legacy rows
        await conn.execute(text("""
            UPDATE cars
            SET car_video = video_url
            WHERE video_url IS NOT NULL AND car_video IS NULL
        """))
