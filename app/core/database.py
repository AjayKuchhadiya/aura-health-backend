import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

logger = logging.getLogger(__name__)

# 1. Define the shared Base class
Base = declarative_base()

# 2. Create async engine with Supabase-specific args
logger.info("Creating async database engine")
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    # THIS IS THE CRITICAL FIX FOR SUPABASE:
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)
logger.info("Async database engine created")

# Create async session factory
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Dependency for getting database session"""
    logger.debug("Opening database session")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            logger.exception("Database session error — rolling back")
            await session.rollback()
            raise
        finally:
            logger.debug("Closing database session")
