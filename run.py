# run.py
import uvicorn
import logging
import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.security import setup_security
from app.api.v1 import api_router
from app.core.database import engine, Base, check_database_connection

# ==================== CONFIGURATION DU LOGGING ====================
# Créer le dossier de logs si nécessaire
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

# Configuration des handlers
log_handlers = [
    logging.StreamHandler(sys.stdout),
]

# Ajouter un handler pour les fichiers si configuré
if settings.LOG_FILE:
    log_file_path = os.path.join(log_dir, settings.LOG_FILE)
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    log_handlers.append(file_handler)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format=settings.LOG_FORMAT,
    handlers=log_handlers
)

# Injection de sécurité pour éviter les crashs de format si request_id n'est pas dans le log standard
old_factory = logging.getLogRecordFactory()

def record_factory(*args, **kwargs):
    record = old_factory(*args, **kwargs)
    if not hasattr(record, "request_id"):
        record.request_id = "GLOBAL"
    if not hasattr(record, "user_id"):
        record.user_id = "ANONYMOUS"
    if not hasattr(record, "ip"):
        record.ip = "0.0.0.0"
    return record

logging.setLogRecordFactory(record_factory)

logger = logging.getLogger(__name__)

# ==================== LIFESPAN POUR LE CYCLE DE VIE ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le cycle de vie de l'application :
    - Initialisation des ressources au démarrage
    - Nettoyage à l'arrêt
    """
    logger.info(f"🚀 Démarrage de {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"🌍 Environnement: {settings.APP_ENV}")
    logger.info(f"🔧 Mode debug: {settings.DEBUG}")
    logger.info(f"🗄️ Base de données: {settings.get_database_dsn()}")
    
    # Vérifier la connexion à la base de données
    try:
        db_connected = await check_database_connection()
        if db_connected:
            logger.info("✅ Connexion à la base de données établie")
        else:
            logger.warning("⚠️ Impossible de se connecter à la base de données")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification de la DB: {e}")
        if settings.is_production:
            raise
    
    # Créer les tables si nécessaire (en développement uniquement)
    if settings.is_development:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Tables créées/vérifiées")
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors de la création des tables: {e}")
    
    yield
    
    # Nettoyage à l'arrêt
    logger.info("🔄 Fermeture des connexions...")
    await engine.dispose()
    logger.info(f"🛑 Arrêt de {settings.APP_NAME}")

# ==================== INITIALISATION DE L'API ====================
app = FastAPI(
    title=settings.APP_NAME,
    description="""
    Backend sécurisé et optimisé pour la gestion de l'écosystème Établissement Kash.
    
    ## Fonctionnalités principales
    * 🔐 Authentification JWT avec refresh tokens
    * 👥 Gestion des utilisateurs et des rôles
    * 📋 Gestion des codes d'activation
    * 📊 Dashboard et statistiques
    * 💳 Gestion des paiements
    
    ## Sécurité
    * Rate limiting
    * CORS configurable
    * Headers de sécurité (OWASP)
    * Protection contre les attaques DoS
    * Validation des données
    """,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG or settings.is_development else None,
    redoc_url="/redoc" if settings.DEBUG or settings.is_development else None,
    openapi_url="/openapi.json" if settings.DEBUG or settings.is_development else None,
    lifespan=lifespan,
)

# ==================== MIDDLEWARE GLOBAUX ====================

# 1. Trusted Host (protection contre les attaques par en-tête Host)
if settings.is_production and settings.ALLOWED_HOSTS != ["*"]:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )
    logger.info(f"✅ Trusted Host configuré: {settings.ALLOWED_HOSTS}")

# 2. Compression GZIP
app.add_middleware(GZipMiddleware, minimum_size=1000)
logger.info("✅ Compression GZIP activée")

# 3. Session Middleware (optionnel)
if settings.SESSION_SECRET_KEY:
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET_KEY.get_secret_value(),
        session_cookie="session",
        max_age=86400,  # 24 heures
    )
    logger.info("✅ Session middleware activé")

# 4. Configuration de la couche de sécurité globale
setup_security(app)

# 5. Inclusion de l'API Router centralisé de la v1
app.include_router(api_router)

# ==================== POINTS D'ACCÈS DE SANTÉ ====================
@app.get("/", tags=["Health"], response_class=JSONResponse)
async def root():
    """
    Point d'accès racine - Redirige vers la documentation si disponible
    """
    return {
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "status": "running",
        "docs": "/docs" if settings.is_development else None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", tags=["Health"], response_class=JSONResponse)
async def health_check():
    """
    Point d'accès de monitoring pour vérifier la disponibilité de l'instance.
    Utilisé par les health checks de Kubernetes/Docker.
    """
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "timestamp": datetime.utcnow().isoformat(),
        "database": "check /health/db for details"
    }

@app.get("/health/db", tags=["Health"], response_class=JSONResponse)
async def db_health_check():
    """
    Vérifie la connexion à la base de données.
    """
    try:
        connected = await check_database_connection()
        if connected:
            return {
                "status": "healthy",
                "database": "connected",
                "provider": "PostgreSQL via Neon.tech",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "database": "disconnected",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
    except Exception as e:
        logger.error(f"❌ Erreur de connexion à la DB: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/health/ready", tags=["Health"], response_class=JSONResponse)
async def readiness_check():
    """
    Indique si l'application est prête à recevoir du trafic.
    Utilisé par les readiness probes Kubernetes.
    """
    # Vérifier la base de données
    db_connected = await check_database_connection()
    
    if db_connected:
        return {
            "status": "ready",
            "application": settings.APP_NAME,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": "database connection failed",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/health/live", tags=["Health"], response_class=JSONResponse)
async def liveness_check():
    """
    Indique si l'application est vivante.
    Utilisé par les liveness probes Kubernetes.
    """
    return {
        "status": "alive",
        "application": settings.APP_NAME,
        "timestamp": datetime.utcnow().isoformat()
    }

# ==================== GESTION DES EXCEPTIONS GLOBALES ====================
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Gestionnaire d'exceptions global pour capturer toutes les erreurs non traitées.
    """
    logger.error(f"❌ Exception non gérée: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Une erreur interne est survenue. L'équipe technique a été notifiée.",
            "path": request.url.path,
            "method": request.method,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# ==================== FONCTION DE DÉMARRAGE ====================
def run_server():
    """
    Fonction principale de démarrage du serveur.
    """
    try:
        logger.info("=" * 60)
        logger.info(f"🚀 Démarrage de {settings.APP_NAME} v{settings.APP_VERSION}")
        logger.info(f"🌍 Environnement: {settings.APP_ENV}")
        logger.info(f"🔧 Mode debug: {settings.DEBUG}")
        logger.info(f"🌐 Hôte: {settings.HOST}:{settings.PORT}")
        logger.info(f"📚 Documentation: http://{settings.HOST}:{settings.PORT}/docs" if settings.is_development else "")
        logger.info("=" * 60)
        
        # Configuration des workers
        workers = settings.WORKERS if not settings.DEBUG else 1
        
        # Démarrer le serveur
        uvicorn.run(
            "run:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=settings.DEBUG,
            reload_dirs=["app"] if settings.DEBUG else None,
            workers=workers,
            loop="uvloop" if not settings.DEBUG else "auto",
            log_level="debug" if settings.DEBUG else "info",
            access_log=settings.DEBUG,
            use_colors=True,
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Arrêt demandé par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Erreur fatale: {e}", exc_info=True)
        sys.exit(1)

# ==================== POINT D'ENTRÉE ====================
if __name__ == "__main__":
    run_server()