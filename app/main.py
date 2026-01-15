from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.database import engine, Base, SessionLocal
from app import models  # Import models to ensure they're registered
from app.routers import host_auth, client_auth, cars, payment_methods, feedback, support, media, bookings
from app.admin import (
    auth as admin_auth,
    users as admin_users,
    cars as admin_cars,
    dashboard as admin_dashboard,
    feedback as admin_feedback,
    notifications as admin_notifications,
    admins as admin_admins,
    payment_methods as admin_payment_methods,
    support as admin_support
)
from app.models import Admin
from app.auth import get_password_hash, get_admin_by_email
from sqlalchemy import text, inspect

app = FastAPI(
    title="Car Rental API",
    description="Backend API for car rental platform",
    version="1.0.0"
)


def migrate_database():
    """Add missing columns to existing tables"""
    inspector = inspect(engine)
    
    # Check and add missing columns to hosts table
    if 'hosts' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('hosts')]
        if 'is_active' not in columns:
            # SQLite uses INTEGER for booleans (0 = False, 1 = True)
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE hosts ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"))
            print("✓ Added is_active column to hosts table")
        if 'avatar_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE hosts ADD COLUMN avatar_url VARCHAR(500)"))
            print("✓ Added avatar_url column to hosts table")
        if 'cover_image_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE hosts ADD COLUMN cover_image_url VARCHAR(500)"))
            print("✓ Added cover_image_url column to hosts table")
        if 'id_document_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE hosts ADD COLUMN id_document_url VARCHAR(500)"))
            print("✓ Added id_document_url column to hosts table")
        if 'license_document_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE hosts ADD COLUMN license_document_url VARCHAR(500)"))
            print("✓ Added license_document_url column to hosts table")
    
    # Check and add missing columns to clients table
    if 'clients' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('clients')]
        if 'is_active' not in columns:
            # SQLite uses INTEGER for booleans (0 = False, 1 = True)
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN is_active INTEGER DEFAULT 1 NOT NULL"))
            print("✓ Added is_active column to clients table")
        if 'avatar_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN avatar_url VARCHAR(500)"))
            print("✓ Added avatar_url column to clients table")
        if 'id_document_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN id_document_url VARCHAR(500)"))
            print("✓ Added id_document_url column to clients table")
        if 'license_document_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN license_document_url VARCHAR(500)"))
            print("✓ Added license_document_url column to clients table")
    
    # Check and add missing columns to cars table
    if 'cars' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('cars')]
        if 'rejection_reason' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cars ADD COLUMN rejection_reason TEXT"))
            print("✓ Added rejection_reason column to cars table")
        if 'is_hidden' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cars ADD COLUMN is_hidden INTEGER DEFAULT 0 NOT NULL"))
            print("✓ Added is_hidden column to cars table")
        if 'image_urls' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cars ADD COLUMN image_urls TEXT"))
            print("✓ Added image_urls column to cars table")
        if 'video_url' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cars ADD COLUMN video_url VARCHAR(500)"))
            print("✓ Added video_url column to cars table")
    
    # Check and add is_flagged to feedbacks table
    if 'feedbacks' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('feedbacks')]
        if 'is_flagged' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE feedbacks ADD COLUMN is_flagged INTEGER DEFAULT 0 NOT NULL"))
            print("✓ Added is_flagged column to feedbacks table")
    
    # Create notifications table if it doesn't exist
    if 'notifications' not in inspector.get_table_names():
        print("✓ Notifications table will be created")
    
    # Migrate support_messages table to new conversation-based schema
    if 'support_messages' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('support_messages')]
        # Check if it's the old schema (has host_id, subject, admin_response) vs new schema (has conversation_id, sender_type)
        if 'conversation_id' not in columns and 'host_id' in columns:
            print("⚠️  Migrating support_messages table to new conversation-based schema...")
            with engine.begin() as conn:
                # Drop old table (data will be lost, but this is a migration)
                conn.execute(text("DROP TABLE support_messages"))
            print("✓ Dropped old support_messages table (will be recreated with new schema)")
    
    # Ensure support_conversations table exists (created by Base.metadata.create_all)
    if 'support_conversations' not in inspector.get_table_names():
        print("✓ Support conversations table will be created")


@app.on_event("startup")
async def startup_event():
    """Create database tables on startup and create default super admin"""
    # Run migrations first (may drop old tables)
    migrate_database()
    
    # Then create all tables (will recreate any dropped tables with new schema)
    Base.metadata.create_all(bind=engine)
    
    # Double-check that support_messages table exists, create if missing
    inspector = inspect(engine)
    if 'support_messages' not in inspector.get_table_names():
        print("⚠️  support_messages table missing, creating...")
        from app.models import SupportMessage, SupportConversation
        SupportMessage.__table__.create(bind=engine, checkfirst=True)
        print("✓ Created support_messages table")
    
    # Create default super admin if it doesn't exist
    db = SessionLocal()
    try:
        default_admin_email = "admin@carrental.com"
        existing_admin = get_admin_by_email(db, default_admin_email)
        
        if not existing_admin:
            # Default super admin password: Admin123!
            default_password = "Admin123!"
            hashed_password = get_password_hash(default_password)
            
            super_admin = Admin(
                full_name="Super Admin",
                email=default_admin_email,
                hashed_password=hashed_password,
                role="super_admin",
                is_active=True
            )
            
            db.add(super_admin)
            db.commit()
            db.refresh(super_admin)
            
            print("=" * 60)
            print("DEFAULT SUPER ADMIN CREATED")
            print("=" * 60)
            print(f"Email: {default_admin_email}")
            print(f"Password: {default_password}")
            print("=" * 60)
            print("⚠️  IMPORTANT: Change this password after first login!")
            print("=" * 60)
        else:
            print(f"Super admin already exists: {default_admin_email}")
    except Exception as e:
        print(f"Error creating default super admin: {e}")
        db.rollback()
    finally:
        db.close()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",  # Expo default
        "http://localhost:19000",  # Expo web
        "http://localhost:19006",  # Expo web alternative
        "exp://localhost:8081",   # Expo client
        "*"  # Allow all for development - RESTRICT IN PRODUCTION
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(host_auth.router, prefix="/api/v1", tags=["Host Auth"])
app.include_router(client_auth.router, prefix="/api/v1", tags=["Client Auth"])
app.include_router(cars.router, prefix="/api/v1", tags=["Car Management"])
app.include_router(payment_methods.router, prefix="/api/v1", tags=["Payment Methods"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
app.include_router(support.router, prefix="/api/v1", tags=["Support Messages"])
app.include_router(bookings.router, prefix="/api/v1", tags=["Bookings"])
app.include_router(media.router, prefix="/api/v1", tags=["Media Upload"])
app.include_router(admin_auth.router, prefix="/api/v1", tags=["Admin Auth"])
app.include_router(admin_users.router, prefix="/api/v1", tags=["Admin User Management"])
app.include_router(admin_cars.router, prefix="/api/v1", tags=["Admin Car Management"])
app.include_router(admin_dashboard.router, prefix="/api/v1", tags=["Admin Dashboard"])
app.include_router(admin_feedback.router, prefix="/api/v1", tags=["Admin Feedback Management"])
app.include_router(admin_notifications.router, prefix="/api/v1", tags=["Admin Notifications"])
app.include_router(admin_admins.router, prefix="/api/v1", tags=["Admin Management"])
app.include_router(admin_payment_methods.router, prefix="/api/v1", tags=["Admin Payment Methods"])
app.include_router(admin_support.router, prefix="/api/v1", tags=["Admin Support"])


@app.get("/")
async def root():
    return {"message": "Car Rental API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


