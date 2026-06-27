# app/main.py
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db, check_database_connection
from app.core.cache import init_cache, close_cache, cache_service
from app.core.security import setup_security, get_client_ip, get_request_id
from app.core.exceptions_handlers import setup_exception_handlers
from app.middleware.logging import StructuredLoggingMiddleware, setup_logging_middleware
from app.api.v1 import api_router

# ==================== CONFIGURATION DES LOGS ====================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE) if settings.LOG_FILE else logging.NullHandler()
    ]
)

# Injection de sécurité pour les logs
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

logger = logging.getLogger("kash_api")

# ==================== LIFESPAN (CYCLE DE VIE) ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le démarrage et l'arrêt de l'application.
    Initialise les connexions aux services externes.
    """
    # ==================== DÉMARRAGE ====================
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage de {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"🌍 Environnement: {settings.APP_ENV}")
    logger.info(f"🔧 Debug: {settings.DEBUG}")
    logger.info(f"🗄️ Base de données: {settings.get_database_dsn()}")
    logger.info("=" * 60)
    
    # 1. Initialisation du cache Redis
    try:
        await init_cache()
        if cache_service.is_connected:
            logger.info("✅ Cache Redis initialisé avec succès")
        else:
            logger.warning("⚠️ Cache Redis désactivé (connexion non disponible)")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation du cache: {e}")
    
    # 2. Vérification de la connexion à la base de données
    try:
        db_connected = await check_database_connection()
        if db_connected:
            logger.info("✅ Connexion à la base de données établie")
        else:
            logger.warning("⚠️ Impossible de se connecter à la base de données")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification de la DB: {e}")
    
    logger.info("✅ Application prête à recevoir du trafic")
    logger.info("=" * 60)
    
    yield
    
    # ==================== ARRÊT ====================
    logger.info("=" * 60)
    logger.info("🛑 Arrêt de l'application en cours...")
    
    # 1. Fermeture de Redis
    try:
        await close_cache()
        logger.info("✅ Cache Redis fermé proprement")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la fermeture du cache: {e}")
    
    logger.info("=" * 60)

# ==================== INITIALISATION DE FASTAPI ====================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=f"""
    API de gestion pour {settings.APP_NAME}
    
    ## Fonctionnalités
    * 🔐 Authentification JWT avec refresh tokens
    * 👥 Gestion des utilisateurs et des rôles
    * 📋 Gestion des codes d'activation
    * 📊 Dashboard et statistiques
    * 💳 Gestion des paiements
    * 🚀 Performance optimisée avec cache Redis
    
    ## Sécurité
    * Rate limiting anti-DoS
    * Protection OWASP (headers, CORS, etc.)
    * Validation rigoureuse des données
    * Anti-brute force avec verrouillage
    
    ## Environnement
    * 🌍 {settings.APP_ENV}
    * 📦 Version {settings.APP_VERSION}
    """,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG or settings.is_development else None,
    redoc_url="/redoc" if settings.DEBUG or settings.is_development else None,
    openapi_url="/openapi.json" if settings.DEBUG or settings.is_development else None,
    servers=[
        {"url": f"http://{settings.HOST}:{settings.PORT}", "description": "Local"},
        {"url": "https://api.kash.com", "description": "Production"}
    ] if settings.is_production else [],
    contact={
        "name": "Équipe Kash",
        "email": "support@kash.com",
        "url": "https://kash.com/contact",
    },
    license_info={
        "name": "Propriétaire - Établissement Kash",
        "url": "https://kash.com/license",
    },
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "Endpoints d'authentification (inscription, connexion, rafraîchissement)",
        },
        {
            "name": "Users",
            "description": "Gestion des utilisateurs (CRUD, rôles, permissions)",
        },
        {
            "name": "Master Codes",
            "description": "Gestion des codes d'activation",
        },
        {
            "name": "Payments",
            "description": "Gestion des paiements et transactions",
        },
        {
            "name": "Dashboard",
            "description": "Tableaux de bord et statistiques",
        },
        {
            "name": "Reports",
            "description": "Rapports et analyses",
        },
        {
            "name": "System",
            "description": "Endpoints système (health, monitoring, etc.)",
        },
        {
            "name": "Health",
            "description": "Vérification de la santé du service",
        },
    ],
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

# 3. Configuration du CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With", "X-Request-ID"],
    expose_headers=["Content-Length", "X-Total-Count", "X-Request-ID", "X-Process-Time"],
    max_age=86400,  # 24 heures
)
logger.info(f"✅ CORS configuré: {settings.BACKEND_CORS_ORIGINS}")

# 4. Middleware de logging structuré
setup_logging_middleware(
    app,
    log_body=settings.DEBUG,
    log_headers=settings.DEBUG
)
logger.info("✅ Logging structuré activé")

# 5. Configuration de la sécurité globale
setup_security(app)
logger.info("✅ Sécurité globale configurée")

# 6. Configuration des handlers d'exceptions
setup_exception_handlers(app)
logger.info("✅ Handlers d'exceptions configurés")

# 7. Routeur API v1
app.include_router(api_router)
logger.info(f"✅ Routes API v1 chargées: {len(api_router.routes)} routes")

# ==================== ROUTES DE VÉRIFICATION (HEALTH CHECK) ====================
@app.get("/", tags=["System"])
async def root():
    """Route racine - Redirection vers la documentation si disponible"""
    return {
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs" if settings.DEBUG or settings.is_development else None,
        "environment": settings.APP_ENV,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", tags=["Health"], status_code=status.HTTP_200_OK)
async def health_check():
    """Vérifie que le serveur FastAPI tourne correctement"""
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "timestamp": datetime.utcnow().isoformat(),
        "cache": "connected" if cache_service.is_connected else "disabled"
    }

@app.get("/health/db", tags=["Health"])
async def db_health_check(db: AsyncSession = Depends(get_db)):
    """
    Vérifie la connexion active avec la base de données.
    Exécute une requête ultra-légère (SELECT 1).
    """
    try:
        start_time = time.time()
        result = await db.execute(text("SELECT 1"))
        await db.commit()
        latency = (time.time() - start_time) * 1000
        
        return {
            "database": "connected",
            "provider": "Neon.tech (PostgreSQL)",
            "latency_ms": f"{latency:.2f}ms",
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Échec de la vérification de la base de données: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "database": "disconnected",
                "error": str(e),
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """
    Vérifie si l'application est prête à recevoir du trafic.
    Utilisé par Kubernetes pour les readiness probes.
    """
    # Vérifier la base de données
    db_connected = await check_database_connection()
    
    if db_connected:
        return {
            "status": "ready",
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "reason": "database connection failed",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/health/live", tags=["Health"])
async def liveness_check():
    """
    Vérifie si l'application est vivante.
    Utilisé par Kubernetes pour les liveness probes.
    """
    return {
        "status": "alive",
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health/cache", tags=["Health"])
async def cache_health_check():
    """
    Vérifie la connexion au cache Redis.
    """
    if cache_service.is_connected:
        return {
            "status": "healthy",
            "cache": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "cache": "disconnected",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# ==================== INFO API ====================
@app.get("/api/info", tags=["System"])
async def api_info():
    """Informations sur l'API"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "docs_available": settings.DEBUG or settings.is_development,
        "cache_enabled": cache_service.is_connected,
        "timestamp": datetime.utcnow().isoformat(),
        "routes": [
            {"path": "/", "method": "GET", "description": "Root endpoint"},
            {"path": "/health", "method": "GET", "description": "Health check"},
            {"path": "/health/db", "method": "GET", "description": "Database health check"},
            {"path": "/health/cache", "method": "GET", "description": "Cache health check"},
            {"path": "/api/info", "method": "GET", "description": "API information"},
            {"path": "/api/v1/auth/*", "method": "ALL", "description": "Authentication endpoints"},
            {"path": "/api/v1/users/*", "method": "ALL", "description": "User management"},
        ]
    }

# ==================== POINT D'ENTRÉE EXÉCUTABLE ====================
if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info(f"🚀 Lancement du serveur sur http://{settings.HOST}:{settings.PORT}")
    if settings.is_development:
        logger.info(f"📚 Documentation: http://{settings.HOST}:{settings.PORT}/docs")
        logger.info(f"📚 ReDoc: http://{settings.HOST}:{settings.PORT}/redoc")
    logger.info(f"🌍 Environnement: {settings.APP_ENV}")
    logger.info("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.is_development,
        workers=settings.WORKERS if not settings.is_development else 1,
        loop="uvloop" if not settings.is_development else "auto",
        log_level=settings.LOG_LEVEL.lower(),
        access_log=settings.DEBUG,
        use_colors=True,
        reload_dirs=["app"] if settings.is_development else None,
    )