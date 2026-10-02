"""Async database layer using SQLAlchemy 2.0 + asyncpg.

Provides:
- engine: async engine with connection pool
- async_session_maker: session factory
- get_db: FastAPI dependency yielding a session
- Base: declarative base for ORM models
- check_db: health check (SELECT 1)
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from api.config import get_settings
from api.logging import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (lazy singleton)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_max_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
        )
        log.info(
            "db_engine_created",
            pool_size=settings.db_pool_max_size,
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory (lazy singleton)."""
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession.

    Usage:
        @router.get("/documents")
        async def list_documents(db: AsyncSession = Depends(get_db)):
            ...
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_db() -> bool:
    """Health check: run SELECT 1. Returns True if DB is reachable."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.error("db_health_check_failed", error=str(exc))
        return False


async def dispose_engine() -> None:
    """Close the engine pool. Called on application shutdown."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
        log.info("db_engine_disposed")
        _engine = None
        _session_maker = None