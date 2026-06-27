from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import event, text
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from app.core.config import settings
import logging
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
import time
import asyncio

logger = logging.getLogger(__name__)

# Configuration du pool de connexions
class DatabaseConfig:
    """Configuration avancée de la base de données"""
    
    # Pool de connexions
    POOL_SIZE = settings.get("DB_POOL_SIZE", 20)  # Taille maximale du pool
    MAX_OVERFLOW = settings.get("DB_MAX_OVERFLOW", 10)  # Connexions supplémentaires
    POOL_TIMEOUT = settings.get("DB_POOL_TIMEOUT", 30)  # Timeout en secondes
    POOL_RECYCLE = settings.get("DB_POOL_RECYCLE", 3600)  # Recycler les connexions après 1 heure
    POOL_PRE_PING = settings.get("DB_POOL_PRE_PING", True)  # Vérifier la connexion avant utilisation
    
    # Timeouts
    CONNECT_TIMEOUT = settings.get("DB_CONNECT_TIMEOUT", 10)
    STATEMENT_TIMEOUT = settings.get("DB_STATEMENT_TIMEOUT", 30)  # Timeout des requêtes SQL
    
    # Monitoring
    LOG_SLOW_QUERIES = settings.get("LOG_SLOW_QUERIES", True)
    SLOW_QUERY_THRESHOLD = settings.get("SLOW_QUERY_THRESHOLD", 1.0)  # Secondes

# 1. Création du moteur de base de données asynchrone amélioré
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.get("DB_ECHO", False),
    future=True,
    
    # Configuration du pool de connexions
    poolclass=AsyncAdaptedQueuePool,
    pool_size=DatabaseConfig.POOL_SIZE,
    max_overflow=DatabaseConfig.MAX_OVERFLOW,
    pool_timeout=DatabaseConfig.POOL_TIMEOUT,
    pool_recycle=DatabaseConfig.POOL_RECYCLE,
    pool_pre_ping=DatabaseConfig.POOL_PRE_PING,
    
    # Paramètres de connexion
    connect_args={
        "timeout": DatabaseConfig.CONNECT_TIMEOUT,
        "server_settings": {
            "statement_timeout": f"{DatabaseConfig.STATEMENT_TIMEOUT}s",
            "application_name": "my_app",
        }
    }
)

# 2. Événements pour le monitoring
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Enregistre le début de l'exécution d'une requête"""
    context._query_start_time = time.time()
    logger.debug(f"Query: {statement}")

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Enregistre la fin de l'exécution d'une requête et log les requêtes lentes"""
    if hasattr(context, '_query_start_time'):
        elapsed = time.time() - context._query_start_time
        if DatabaseConfig.LOG_SLOW_QUERIES and elapsed > DatabaseConfig.SLOW_QUERY_THRESHOLD:
            logger.warning(
                f"Slow query ({elapsed:.2f}s): {statement[:200]}..."
            )
        logger.debug(f"Query executed in {elapsed:.2f}s")

# 3. Configuration de la fabrique de sessions asynchrones
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

# 4. Classe de base pour les modèles
class Base(DeclarativeBase):
    """Classe de base avec méthodes utilitaires"""
    
    @classmethod
    @asynccontextmanager
    async def get_session(cls, db: AsyncSession = None):
        """Gestionnaire de contexte pour les sessions"""
        if db:
            yield db
        else:
            async with SessionLocal() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()
    
    @classmethod
    async def get_all(cls, db: AsyncSession, **filters):
        """Récupère tous les enregistrements avec filtres optionnels"""
        query = cls.query
        for key, value in filters.items():
            query = query.filter(getattr(cls, key) == value)
        result = await db.execute(query)
        return result.scalars().all()
    
    @classmethod
    async def get_by_id(cls, db: AsyncSession, record_id: int):
        """Récupère un enregistrement par ID"""
        result = await db.execute(cls.query.filter(cls.id == record_id))
        return result.scalar_one_or_none()

# 5. Fonction de dépendance avec gestion d'erreurs améliorée
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency pour obtenir une session de base de données.
    Gère automatiquement les transactions et les erreurs.
    """
    session = None
    try:
        session = SessionLocal()
        # Démarrer une transaction
        await session.begin()
        yield session
        # Commit si aucune erreur
        await session.commit()
    except Exception as e:
        if session:
            await session.rollback()
        logger.error(f"Database error: {str(e)}", exc_info=True)
        raise
    finally:
        if session:
            await session.close()

# 6. Gestionnaire de contexte pour les transactions
@asynccontextmanager
async def transaction(db: AsyncSession):
    """
    Gestionnaire de contexte pour les transactions.
    Usage: async with transaction(db) as session:
    """
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise

# 7. Middleware pour les requêtes de base de données
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time

class DatabaseMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware pour mesurer les performances des requêtes DB"""
    
    async def dispatch(self, request: Request, call_next):
        request.state.db_start_time = time.time()
        response = await call_next(request)
        if hasattr(request.state, 'db_queries_count'):
            elapsed = time.time() - request.state.db_start_time
            logger.info(
                f"DB Queries: {request.state.db_queries_count}, "
                f"Time: {elapsed:.2f}s, "
                f"Path: {request.url.path}"
            )
        return response

# 8. Fonction utilitaire pour vérifier la connexion
async def check_database_connection() -> bool:
    """
    Vérifie la connexion à la base de données.
    À utiliser pour les health checks.
    """
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return False

# 9. Fonction pour exécuter des requêtes en batch
async def execute_in_batches(db: AsyncSession, items: list, batch_size: int = 1000, func=None):
    """
    Exécute une fonction en batches pour éviter les problèmes de mémoire.
    """
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        if func:
            await func(db, batch)
        # Commit après chaque batch
        await db.commit()

# 10. Fonction pour gérer les retries sur les erreurs de base de données
async def execute_with_retry(func, retries: int = 3, delay: float = 1.0):
    """
    Exécute une fonction avec retry en cas d'erreur de base de données.
    """
    last_exception = None
    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_exception = e
            if attempt < retries - 1:
                wait_time = delay * (2 ** attempt)  # Backoff exponentiel
                logger.warning(f"DB error, retrying in {wait_time}s: {str(e)}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"DB error after {retries} attempts: {str(e)}")
                raise
    raise last_exception