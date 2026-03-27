from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings
import os

# Default to SQLite if DATABASE_URL is not provided
# But ensure we use the async driver for PostgreSQL if provided
if settings.DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
elif settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
    # Construct DATABASE_URL from Supabase
    from urllib.parse import urlparse
    parsed = urlparse(settings.SUPABASE_URL)
    project_id = parsed.netloc.split('.')[0]  # e.g., project-id from https://project-id.supabase.co
    SQLALCHEMY_DATABASE_URL = f"postgresql+asyncpg://postgres:{settings.SUPABASE_SERVICE_ROLE_KEY}@db.{project_id}.supabase.co:5432/postgres"
else:
    SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./car_rental.db"

# asyncpg requires postgresql+asyncpg:// instead of postgresql://
if SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
# Sync sqlite:// uses pysqlite; create_async_engine needs sqlite+aiosqlite://
elif SQLALCHEMY_DATABASE_URL.split("://", 1)[0] == "sqlite":
    rest = SQLALCHEMY_DATABASE_URL.split("://", 1)[1]
    SQLALCHEMY_DATABASE_URL = f"sqlite+aiosqlite://{rest}"

# For SQLite, we need to ensure check_same_thread is handled if it was a sync connection,
# but aiosqlite handles it differently. 
connect_args = {}
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True
)

# Create a configured "Session" class
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    """Dependency to get database session"""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
