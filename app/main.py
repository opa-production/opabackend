from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.database import engine, Base, SessionLocal
from app import models  # Import models to ensure they're registered
from app.models import DrivingLicense  # Import DrivingLicense to ensure it's registered
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
        if 'date_of_birth' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN date_of_birth DATE"))
            print("✓ Added date_of_birth column to clients table")
        if 'gender' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN gender VARCHAR(20)"))
            print("✓ Added gender column to clients table")
    
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
    
    # Check and add client_id to payment_methods table, and make host_id nullable
    if 'payment_methods' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('payment_methods')]
        column_info = {col['name']: col for col in inspector.get_columns('payment_methods')}
        
        # Add client_id if missing
        if 'client_id' not in columns:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE payment_methods ADD COLUMN client_id INTEGER"))
                    print("✓ Added client_id column to payment_methods table")
                except Exception as e:
                    print(f"⚠️  Error adding client_id to payment_methods: {e}")
        
        # SQLite doesn't support ALTER COLUMN to change nullability directly
        # We need to recreate the table. Check if host_id is NOT NULL
        if 'host_id' in column_info:
            host_id_nullable = column_info['host_id'].get('nullable', False)
            if not host_id_nullable:
                print("⚠️  payment_methods.host_id is NOT NULL, recreating table to make it nullable...")
                try:
                    with engine.begin() as conn:
                        # Drop temp table if it exists from previous failed migration
                        try:
                            conn.execute(text("DROP TABLE IF EXISTS payment_methods_new"))
                        except Exception:
                            pass
                        
                        # Create new table with correct schema
                        conn.execute(text("""
                            CREATE TABLE payment_methods_new (
                                id INTEGER PRIMARY KEY,
                                host_id INTEGER,
                                client_id INTEGER,
                                name VARCHAR(255) NOT NULL,
                                method_type VARCHAR(20) NOT NULL,
                                mpesa_number VARCHAR(20),
                                card_number_hash VARCHAR(255),
                                card_last_four VARCHAR(4),
                                card_type VARCHAR(20),
                                expiry_month INTEGER,
                                expiry_year INTEGER,
                                cvc_hash VARCHAR(255),
                                is_default INTEGER DEFAULT 0,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                FOREIGN KEY(host_id) REFERENCES hosts(id),
                                FOREIGN KEY(client_id) REFERENCES clients(id)
                            )
                        """))
                        
                        # Copy existing data - preserve ALL existing payment methods (both host and client)
                        # Get all columns from old table BEFORE we modify anything
                        old_columns = [col['name'] for col in inspector.get_columns('payment_methods')]
                        
                        # Build SELECT statement: copy all existing columns, add NULL for new client_id column
                        select_parts = []
                        
                        # Always include these core columns (they should exist)
                        select_parts.append('id')
                        select_parts.append('host_id')  # Preserve existing host_id values
                        select_parts.append('NULL as client_id')  # New column, will be NULL for existing host methods
                        
                        # Copy all other existing columns
                        for col in ['name', 'method_type', 'mpesa_number', 'card_number_hash', 
                                   'card_last_four', 'card_type', 'expiry_month', 'expiry_year', 
                                   'cvc_hash', 'is_default', 'created_at', 'updated_at']:
                            if col in old_columns:
                                select_parts.append(col)
                            else:
                                select_parts.append(f'NULL as {col}')
                        
                        # Copy all existing data - this preserves ALL host payment methods
                        select_sql = f"SELECT {', '.join(select_parts)} FROM payment_methods"
                        insert_sql = f"""
                            INSERT INTO payment_methods_new 
                            (id, host_id, client_id, name, method_type, mpesa_number, 
                             card_number_hash, card_last_four, card_type, expiry_month, 
                             expiry_year, cvc_hash, is_default, created_at, updated_at)
                            {select_sql}
                        """
                        conn.execute(text(insert_sql))
                        print(f"✓ Copied {conn.execute(text('SELECT COUNT(*) FROM payment_methods_new')).scalar()} payment methods to new table")
                        
                        # Drop old table
                        conn.execute(text("DROP TABLE payment_methods"))
                        
                        # Rename new table
                        conn.execute(text("ALTER TABLE payment_methods_new RENAME TO payment_methods"))
                        
                        print("✓ Recreated payment_methods table with nullable host_id and client_id")
                except Exception as e:
                    print(f"⚠️  Error recreating payment_methods table: {e}")
                    # Try to drop temp table if it exists
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("DROP TABLE IF EXISTS payment_methods_new"))
                    except Exception:
                        pass
                    print("   The table will be recreated on next startup with Base.metadata.create_all()")
    
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


