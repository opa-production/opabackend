from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings
import os

# PostgreSQL database URL configuration
# Priority: TEST_DATABASE_URL (if TEST_MODE) > DATABASE_URL
if settings.TEST_MODE and settings.TEST_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = settings.TEST_DATABASE_URL
    print(f"Using TEST_DATABASE_URL (PostgreSQL)")
elif settings.DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
    print(f"Using DATABASE_URL (PostgreSQL)")
else:
    raise ValueError(
        "No database configuration found. Please set DATABASE_URL for PostgreSQL database."
    )

# Ensure PostgreSQL URL uses asyncpg driver
if SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=False,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10
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
