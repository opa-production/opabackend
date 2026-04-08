import ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

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

# Ensure PostgreSQL URL uses asyncpg driver and handle sslmode parameter
if SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
elif SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgres://", "postgresql+asyncpg://", 1
    )

# Parse the URL to remove sslmode and channel_binding (asyncpg doesn't use them)
parsed = urlparse(SQLALCHEMY_DATABASE_URL)
query_params = parse_qs(parsed.query)

# Remove parameters that asyncpg doesn't recognize
params_to_remove = ["sslmode", "channel_binding"]
for param in params_to_remove:
    if param in query_params:
        del query_params[param]

# Reconstruct URL without incompatible parameters
new_query = urlencode(query_params, doseq=True)
SQLALCHEMY_DATABASE_URL = urlunparse(
    (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    )
)

# Create engine with SSL context for asyncpg if needed
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
    "pool_size": 20,
    "max_overflow": 10,
}

# Add SSL context for production database connections
if "postgresql+asyncpg://" in SQLALCHEMY_DATABASE_URL:
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = True
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    engine_kwargs["connect_args"] = {"ssl": ssl_context}

engine = create_async_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)

# Create a configured "Session" class
SessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    """Dependency to get database session"""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
