from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
from sqlalchemy.pool import AsyncAdaptedQueuePool
from app.core.config import settings
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager
import time
import asyncio

logger = logging.getLogger(__name__)

# Configuration du pool de connexions (Compatible Pydantic v2)
class DatabaseConfig:
    """Configuration avancée de la base de données"""
    
    POOL_SIZE = getattr(settings, "DB_POOL_SIZE", 20)
    MAX_OVERFLOW = getattr(settings, "DB_MAX_OVERFLOW", 10)
    POOL_TIMEOUT = getattr(settings, "DB_POOL_TIMEOUT", 30)
    POOL_RECYCLE = getattr(settings, "DB_POOL_RECYCLE", 3600)
    POOL_PRE_PING = getattr(settings, "DB_POOL_PRE_PING", True)
    
    CONNECT_TIMEOUT = getattr(settings, "DB_CONNECT_TIMEOUT", 10)
    STATEMENT_TIMEOUT = getattr(settings, "DB_STATEMENT_TIMEOUT", 30)
    
    LOG_SLOW_QUERIES = getattr(settings, "LOG_SLOW_QUERIES", True)
    SLOW_QUERY_THRESHOLD = getattr(settings, "SLOW_QUERY_THRESHOLD", 1.0)

# Création du moteur de base de données
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=getattr(settings, "DB_ECHO", False),
    future=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=DatabaseConfig.POOL_SIZE,
    max_overflow=DatabaseConfig.MAX_OVERFLOW,
    pool_timeout=DatabaseConfig.POOL_TIMEOUT,
    pool_recycle=DatabaseConfig.POOL_RECYCLE,
    pool_pre_ping=DatabaseConfig.POOL_PRE_PING,
    connect_args={
        "timeout": DatabaseConfig.CONNECT_TIMEOUT,
        "server_settings": {
            "statement_timeout": f"{DatabaseConfig.STATEMENT_TIMEOUT}s",
            "application_name": "my_app",
        }
    }
)

# Événements pour le monitoring
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.time()

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if hasattr(context, '_query_start_time'):
        elapsed = time.time() - context._query_start_time
        if DatabaseConfig.LOG_SLOW_QUERIES and elapsed > DatabaseConfig.SLOW_QUERY_THRESHOLD:
            logger.warning(f"Slow query ({elapsed:.2f}s): {statement[:200]}...")

# Configuration de la fabrique de sessions
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Classe de base pour les modèles
class Base(DeclarativeBase):
    pass

# Fonction de dépendance
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            await session.begin()
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {str(e)}", exc_info=True)
            raise
        finally:
            await session.close()