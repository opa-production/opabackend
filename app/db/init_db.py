import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, select, text

from app.db.base import Base
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal inspection helpers
# ---------------------------------------------------------------------------


async def _async_insp_table_names(conn) -> set:
    """Table names via sync inspector inside greenlet (required for async SQLAlchemy)."""

    def _f(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


async def _async_insp_column_names(conn, table: str) -> list:
    def _f(sync_conn):
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return []
        return [c["name"] for c in insp.get_columns(table)]

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


async def _async_insp_column_info(conn, table: str) -> dict:
    def _f(sync_conn):
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return {}
        return {c["name"]: c for c in insp.get_columns(table)}

    for attempt in range(3):
        try:
            return await conn.run_sync(_f)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed: {e}, retrying...")
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

migration_lock_file = os.path.join(os.getcwd(), "migration.lock")


async def run_migrations():
    try:
        import fcntl

        lock_file = "/tmp/fastapi_migration.lock"
        with open(lock_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                if not os.path.exists(migration_lock_file):
                    with open(migration_lock_file, "w") as f2:
                        f2.write("1")
                    await migrate_database()
                    async with engine.connect() as conn:
                        await migrate_car_media_data(conn)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        # On systems without fcntl (like Windows), just run without lock
        if not os.path.exists(migration_lock_file):
            with open(migration_lock_file, "w") as f2:
                f2.write("1")
            await migrate_database()
            async with engine.connect() as conn:
                await migrate_car_media_data(conn)


async def migrate_database():
    """Add missing columns to existing tables"""
    async with engine.connect() as conn:
        table_names = await _async_insp_table_names(conn)

        # Check and add missing columns to hosts table
        if "hosts" in table_names:
            columns = await _async_insp_column_names(conn, "hosts")
            if "is_active" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE hosts ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added is_active column to hosts table")
            if "avatar_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE hosts ADD COLUMN avatar_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added avatar_url column to hosts table")
            if "cover_image_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE hosts ADD COLUMN cover_image_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added cover_image_url column to hosts table")
            if "id_document_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE hosts ADD COLUMN id_document_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added id_document_url column to hosts table")
            if "license_document_url" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE hosts ADD COLUMN license_document_url VARCHAR(500)"
                    )
                )
                await conn.commit()
                print("✓ Added license_document_url column to hosts table")
            if "google_id" not in columns:
                await conn.execute(
                    text("ALTER TABLE hosts ADD COLUMN google_id VARCHAR(255)")
                )
                await conn.commit()
                print("✓ Added google_id column to hosts table")
            if "terms_accepted_at" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE hosts ADD COLUMN terms_accepted_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added terms_accepted_at column to hosts table")

        # Check and add missing columns to clients table
        if "clients" in table_names:
            columns = await _async_insp_column_names(conn, "clients")
            if "is_active" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added is_active column to clients table")
            if "avatar_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE clients ADD COLUMN avatar_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added avatar_url column to clients table")
            if "id_document_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE clients ADD COLUMN id_document_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added id_document_url column to clients table")
            if "license_document_url" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN license_document_url VARCHAR(500)"
                    )
                )
                await conn.commit()
                print("✓ Added license_document_url column to clients table")
            if "date_of_birth" not in columns:
                await conn.execute(
                    text("ALTER TABLE clients ADD COLUMN date_of_birth DATE")
                )
                await conn.commit()
                print("✓ Added date_of_birth column to clients table")
            if "gender" not in columns:
                await conn.execute(
                    text("ALTER TABLE clients ADD COLUMN gender VARCHAR(20)")
                )
                await conn.commit()
                print("✓ Added gender column to clients table")
            if "google_id" not in columns:
                await conn.execute(
                    text("ALTER TABLE clients ADD COLUMN google_id VARCHAR(255)")
                )
                await conn.commit()
                print("✓ Added google_id column to clients table")
            if "terms_accepted_at" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN terms_accepted_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added terms_accepted_at column to clients table")
            if "email_notifications_enabled" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN email_notifications_enabled INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added email_notifications_enabled column to clients table")
            if "sms_notifications_enabled" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN sms_notifications_enabled INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added sms_notifications_enabled column to clients table")
            if "in_app_notifications_enabled" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE clients ADD COLUMN in_app_notifications_enabled INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added in_app_notifications_enabled column to clients table")

        # Check and add missing columns to cars table
        if "cars" in table_names:
            columns = await _async_insp_column_names(conn, "cars")
            if "rejection_reason" not in columns:
                await conn.execute(
                    text("ALTER TABLE cars ADD COLUMN rejection_reason TEXT")
                )
                await conn.commit()
                print("✓ Added rejection_reason column to cars table")
            if "is_hidden" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE cars ADD COLUMN is_hidden INTEGER DEFAULT 0 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added is_hidden column to cars table")
            if "image_urls" not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN image_urls TEXT"))
                await conn.commit()
                print("✓ Added image_urls column to cars table")
            if "video_url" not in columns:
                await conn.execute(
                    text("ALTER TABLE cars ADD COLUMN video_url VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added video_url column to cars table")
            if "cover_image" not in columns:
                await conn.execute(
                    text("ALTER TABLE cars ADD COLUMN cover_image VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added cover_image column to cars table")
            if "car_images" not in columns:
                await conn.execute(text("ALTER TABLE cars ADD COLUMN car_images TEXT"))
                await conn.commit()
                print("✓ Added car_images column to cars table")
            if "car_video" not in columns:
                await conn.execute(
                    text("ALTER TABLE cars ADD COLUMN car_video VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added car_video column to cars table")
            if "drive_setting" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE cars ADD COLUMN drive_setting VARCHAR(30) DEFAULT 'self_only' NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added drive_setting column to cars table")

        # Check and add is_flagged to feedbacks table
        if "feedbacks" in table_names:
            columns = await _async_insp_column_names(conn, "feedbacks")
            if "is_flagged" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE feedbacks ADD COLUMN is_flagged INTEGER DEFAULT 0 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added is_flagged column to feedbacks table")

        # Check and add extension_request_id to payments table (for booking extensions)
        if "payments" in table_names:
            columns = await _async_insp_column_names(conn, "payments")
            if "extension_request_id" not in columns:
                await conn.execute(
                    text("ALTER TABLE payments ADD COLUMN extension_request_id INTEGER")
                )
                await conn.commit()
                print("✓ Added extension_request_id column to payments table")

        # Check and add client_id to payment_methods table, and make host_id nullable
        if "payment_methods" in table_names:
            columns = await _async_insp_column_names(conn, "payment_methods")
            column_info = await _async_insp_column_info(conn, "payment_methods")

            # Add client_id if missing
            if "client_id" not in columns:
                try:
                    await conn.execute(
                        text("ALTER TABLE payment_methods ADD COLUMN client_id INTEGER")
                    )
                    await conn.commit()
                    print("✓ Added client_id column to payment_methods table")
                except Exception as e:
                    print(f"⚠️  Error adding client_id to payment_methods: {e}")

            # PostgreSQL can handle ALTER COLUMN directly
            if "host_id" in column_info:
                host_id_nullable = column_info["host_id"].get("nullable", False)
                if not host_id_nullable:
                    print(
                        "⚠️  payment_methods.host_id is NOT NULL, altering to nullable..."
                    )
                    try:
                        await conn.execute(
                            text(
                                "ALTER TABLE payment_methods ALTER COLUMN host_id DROP NOT NULL"
                            )
                        )
                        await conn.commit()
                        print("✓ Made payment_methods.host_id nullable")
                    except Exception as e:
                        print(f"⚠️  Error altering payment_methods table: {e}")

        # Create notifications table if it doesn't exist
        if "notifications" not in table_names:
            print("✓ Notifications table will be created")

        # Migrate support_messages table to new conversation-based schema
        if "support_messages" in table_names:
            columns = await _async_insp_column_names(conn, "support_messages")
            if "conversation_id" not in columns and "host_id" in columns:
                print(
                    "⚠️  Migrating support_messages table to new conversation-based schema..."
                )
                await conn.execute(text("DROP TABLE support_messages"))
                await conn.commit()
                print(
                    "✓ Dropped old support_messages table (will be recreated with new schema)"
                )

        # Ensure support_conversations table exists
        if "support_conversations" not in table_names:
            print("✓ Support conversations table will be created")


async def migrate_car_media_data(conn):
    """Migrate existing car media data from legacy fields to new fields"""
    import json

    # Check if cars table exists
    table_names = await _async_insp_table_names(conn)
    if "cars" not in table_names:
        return

    # Get all cars with legacy media data
    result = await conn.execute(
        text(
            "SELECT id, image_urls, video_url, car_images, cover_image, car_video FROM cars"
        )
    )
    cars = result.fetchall()

    migrated_count = 0
    for car in cars:
        car_id, image_urls, video_url, car_images, cover_image, car_video = car

        updates = {}

        # Migrate image_urls to car_images if car_images is empty
        if image_urls and not car_images:
            try:
                # image_urls should already be JSON, but let's ensure it's valid
                parsed_urls = (
                    json.loads(image_urls)
                    if isinstance(image_urls, str)
                    else image_urls
                )
                if isinstance(parsed_urls, list) and parsed_urls:
                    updates["car_images"] = json.dumps(parsed_urls)
                    # Set cover_image to first image if not set
                    if not cover_image and parsed_urls:
                        updates["cover_image"] = parsed_urls[0]
            except (json.JSONDecodeError, TypeError):
                # If image_urls is not valid JSON, try to treat it as a single URL
                if image_urls and isinstance(image_urls, str):
                    updates["car_images"] = json.dumps([image_urls])
                    if not cover_image:
                        updates["cover_image"] = image_urls

        # Migrate video_url to car_video if car_video is empty
        if video_url and not car_video:
            updates["car_video"] = video_url

        # Apply updates if any
        if updates:
            set_parts = []
            params = {"car_id": car_id}

            for field, value in updates.items():
                set_parts.append(f"{field} = :{field}")
                params[field] = value

            if set_parts:
                query = f"UPDATE cars SET {', '.join(set_parts)} WHERE id = :car_id"
                await conn.execute(text(query), params)
                migrated_count += 1

    if migrated_count > 0:
        await conn.commit()
        print(
            f"✓ Migrated media data for {migrated_count} cars from legacy to new fields"
        )


# ---------------------------------------------------------------------------
# Startup entrypoint
# ---------------------------------------------------------------------------


async def startup_database():
    """Create database tables on startup and create default super admin"""
    print("🚀 Starting up...")

    # Run migrations first
    await run_migrations()

    # Then create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        table_names = await _async_insp_table_names(conn)

        # Double-check that support_messages table exists, create if missing
        if "support_messages" not in table_names:
            print("⚠️  support_messages table missing, creating...")
            from app.models import SupportMessage

            def create_table(sync_conn):
                SupportMessage.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created support_messages table")

        # Double-check that client_host_conversations and client_host_messages tables exist
        if "client_host_conversations" not in table_names:
            print("⚠️  client_host_conversations table missing, creating...")
            from app.models import ClientHostConversation

            def create_table(sync_conn):
                ClientHostConversation.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created client_host_conversations table")

        if "client_host_messages" not in table_names:
            print("⚠️  client_host_messages table missing, creating...")
            from app.models import ClientHostMessage

            def create_table(sync_conn):
                ClientHostMessage.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created client_host_messages table")

        # Double-check that car_blocked_dates table exists
        if "car_blocked_dates" not in table_names:
            print("⚠️  car_blocked_dates table missing, creating...")
            from app.models import CarBlockedDate

            def create_table(sync_conn):
                CarBlockedDate.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created car_blocked_dates table")
        else:
            columns = await _async_insp_column_names(conn, "car_blocked_dates")
            if "start_date" in columns and "blocked_date" not in columns:
                await conn.execute(
                    text("ALTER TABLE car_blocked_dates ADD COLUMN blocked_date DATE")
                )
                await conn.execute(
                    text(
                        "UPDATE car_blocked_dates SET blocked_date = DATE(start_date) WHERE blocked_date IS NULL"
                    )
                )
                await conn.commit()
                print(
                    "✓ Migrated start_date to blocked_date in car_blocked_dates table"
                )
            elif "blocked_date" not in columns:
                await conn.execute(
                    text("ALTER TABLE car_blocked_dates ADD COLUMN blocked_date DATE")
                )
                await conn.commit()
                print("✓ Added blocked_date column to car_blocked_dates table")

            if "reason" not in columns:
                await conn.execute(
                    text("ALTER TABLE car_blocked_dates ADD COLUMN reason TEXT")
                )
                await conn.commit()
                print("✓ Added reason column to car_blocked_dates table")
            if "created_at" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE car_blocked_dates ADD COLUMN created_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added created_at column to car_blocked_dates table")

        # Ensure client_kycs table exists
        if "client_kycs" not in table_names:
            print("⚠️  client_kycs table missing, creating...")
            from app.models import ClientKyc

            def create_table(sync_conn):
                ClientKyc.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created client_kycs table")

        # Ensure client_wallets table exists (Ardena Pay / Stellar)
        if "client_wallets" not in table_names:
            print("⚠️  client_wallets table missing, creating...")
            from app.models import ClientWallet

            await conn.run_sync(
                lambda sync_conn: ClientWallet.__table__.create(
                    sync_conn, checkfirst=True
                )
            )
            print("✓ Created client_wallets table")
        else:
            # Add balance cache columns if missing (stored in DB for easier retrieval)
            cw_columns = await conn.run_sync(
                lambda sync_conn: [
                    col["name"]
                    for col in inspect(sync_conn).get_columns("client_wallets")
                ]
            )
            if "balance_xlm" not in cw_columns:
                await conn.execute(
                    text(
                        "ALTER TABLE client_wallets ADD COLUMN balance_xlm VARCHAR(50) DEFAULT '0'"
                    )
                )
                await conn.commit()
                print("✓ Added balance_xlm column to client_wallets table")
            if "balance_usdc" not in cw_columns:
                await conn.execute(
                    text(
                        "ALTER TABLE client_wallets ADD COLUMN balance_usdc VARCHAR(50) DEFAULT '0'"
                    )
                )
                await conn.commit()
                print("✓ Added balance_usdc column to client_wallets table")
            if "balance_updated_at" not in cw_columns:
                await conn.execute(
                    text(
                        "ALTER TABLE client_wallets ADD COLUMN balance_updated_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added balance_updated_at column to client_wallets table")

        # Ensure host_booking_issues table exists
        if "host_booking_issues" not in table_names:
            print("⚠️  host_booking_issues table missing, creating...")
            from app.models import BookingIssue

            def create_table(sync_conn):
                BookingIssue.__table__.create(sync_conn, checkfirst=True)

            await conn.run_sync(create_table)
            print("✓ Created host_booking_issues table")

        # Check and add missing columns to bookings table
        if "bookings" in table_names:
            columns = await _async_insp_column_names(conn, "bookings")
            if "dropoff_same_as_pickup" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE bookings ADD COLUMN dropoff_same_as_pickup INTEGER DEFAULT 1 NOT NULL"
                    )
                )
                await conn.commit()
                print("✓ Added dropoff_same_as_pickup column to bookings table")
            if "pickup_confirmed_at" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE bookings ADD COLUMN pickup_confirmed_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added pickup_confirmed_at column to bookings table")
            if "dropoff_confirmed_at" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE bookings ADD COLUMN dropoff_confirmed_at TIMESTAMP WITH TIME ZONE"
                    )
                )
                await conn.commit()
                print("✓ Added dropoff_confirmed_at column to bookings table")

        # Check and add missing columns to withdrawals table
        if "withdrawals" in table_names:
            columns = await _async_insp_column_names(conn, "withdrawals")
            if "checkout_request_id" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE withdrawals ADD COLUMN checkout_request_id VARCHAR(255)"
                    )
                )
                await conn.commit()
                print("✓ Added checkout_request_id column to withdrawals table")
            if "result_code" not in columns:
                await conn.execute(
                    text("ALTER TABLE withdrawals ADD COLUMN result_code INTEGER")
                )
                await conn.commit()
                print("✓ Added result_code column to withdrawals table")
            if "result_desc" not in columns:
                await conn.execute(
                    text("ALTER TABLE withdrawals ADD COLUMN result_desc VARCHAR(500)")
                )
                await conn.commit()
                print("✓ Added result_desc column to withdrawals table")
            if "mpesa_receipt_number" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE withdrawals ADD COLUMN mpesa_receipt_number VARCHAR(100)"
                    )
                )
                await conn.commit()
                print("✓ Added mpesa_receipt_number column to withdrawals table")
            if "mpesa_phone" not in columns:
                await conn.execute(
                    text("ALTER TABLE withdrawals ADD COLUMN mpesa_phone VARCHAR(20)")
                )
                await conn.commit()
                print("✓ Added mpesa_phone column to withdrawals table")
            if "mpesa_transaction_date" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE withdrawals ADD COLUMN mpesa_transaction_date VARCHAR(50)"
                    )
                )
                await conn.commit()
                print("✓ Added mpesa_transaction_date column to withdrawals table")

        # Migrate existing car media data from legacy to new fields
        await migrate_car_media_data(conn)

    # Create default super admin if it doesn't exist
    await _ensure_default_super_admin()

    print("✅ Startup complete!")

    # Launch background worker loops
    from app.workers.scheduler import (
        _run_expire_pending_bookings_loop,
        _run_pickup_reminder_loop,
    )

    asyncio.create_task(_run_expire_pending_bookings_loop())
    asyncio.create_task(_run_pickup_reminder_loop())


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


async def _ensure_default_super_admin():
    """Ensure the default super admin exists, handling race conditions from multiple workers."""
    from sqlalchemy.exc import IntegrityError

    from app.core.security import get_admin_by_email, get_password_hash
    from app.models import Admin

    async with SessionLocal() as db:
        try:
            default_admin_email = "admin@carrental.com"
            existing_admin = await get_admin_by_email(db, default_admin_email)

            if not existing_admin:
                # Default super admin password: Admin123!
                # ⚠️ SECURITY WARNING: This default password is for development only.
                # In production, use a strong password or environment variable.
                default_password = "Admin123!"
                hashed_password = get_password_hash(default_password)

                super_admin = Admin(
                    full_name="Super Admin",
                    email=default_admin_email,
                    hashed_password=hashed_password,
                    role="super_admin",
                    is_active=True,
                )

                db.add(super_admin)
                try:
                    await db.commit()
                    await db.refresh(super_admin)

                    print("=" * 60)
                    print("DEFAULT SUPER ADMIN CREATED")
                    print("=" * 60)
                    print(f"Email: {default_admin_email}")
                    print(f"Password: {default_password}")
                    print("=" * 60)
                    print("⚠️  IMPORTANT: Change this password after first login!")
                    print("=" * 60)
                except IntegrityError:
                    await db.rollback()
                    # Someone else created it in the meantime
                    print(
                        f"Super admin already exists (created by another worker): {default_admin_email}"
                    )
            else:
                print(f"Super admin already exists: {default_admin_email}")
        except Exception as e:
            print(f"Error creating default super admin: {e}")
            await db.rollback()
