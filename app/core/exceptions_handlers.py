# app/core/exceptions_handlers.py
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError, DataError, OperationalError
from app.core.exceptions import (
    AppException,
    NotFoundException,
    ValidationException,
    DuplicateException,
    SecurityException,
    AuthenticationException,
    RateLimitException
)

logger = logging.getLogger(__name__)

# ==================== UTILITAIRES ====================

def build_error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
    exception: Optional[Exception] = None
) -> JSONResponse:
    """
    Construit une réponse d'erreur standardisée.
    
    Args:
        request: Requête FastAPI
        code: Code d'erreur
        message: Message d'erreur
        status_code: Code HTTP
        details: Détails supplémentaires
        exception: Exception originale (pour logging)
    
    Returns:
        JSONResponse: Réponse d'erreur formatée
    """
    # Logger l'erreur
    if exception:
        log_level = logging.ERROR if status_code >= 500 else logging.WARNING
        logger.log(
            log_level,
            f"❌ {code}: {message} - Path: {request.url.path}",
            exc_info=exception if status_code >= 500 else None
        )
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "path": request.url.path,
                "method": request.method,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        },
        headers={
            "X-Error-Code": code,
            "X-Error-Time": datetime.now(timezone.utc).isoformat()
        }
    )

# ==================== HANDLERS PERSONNALISÉS ====================

async def app_exception_handler(request: Request, exc: AppException):
    """Handler pour les exceptions métier personnalisées"""
    return build_error_response(
        request=request,
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        exception=exc
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handler pour les exceptions HTTP de Starlette"""
    # Personnaliser le message selon le code
    messages = {
        status.HTTP_404_NOT_FOUND: "Ressource non trouvée",
        status.HTTP_403_FORBIDDEN: "Accès refusé",
        status.HTTP_401_UNAUTHORIZED: "Non authentifié",
        status.HTTP_429_TOO_MANY_REQUESTS: "Trop de requêtes",
        status.HTTP_400_BAD_REQUEST: "Requête invalide",
    }
    
    message = messages.get(exc.status_code, str(exc.detail))
    
    return build_error_response(
        request=request,
        code=f"HTTP_{exc.status_code}",
        message=message,
        status_code=exc.status_code,
        details={"detail": str(exc.detail)} if exc.detail else None,
        exception=exc
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handler pour les erreurs de validation Pydantic"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"],
            "input": error.get("input", None)
        })
    
    # Logger les erreurs de validation en debug
    logger.debug(f"🔍 Validation errors: {errors}")
    
    return build_error_response(
        request=request,
        code="VALIDATION_ERROR",
        message="Erreur de validation des données",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details={"errors": errors},
        exception=exc
    )

async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Handler pour les erreurs d'intégrité SQL"""
    # Extraire le message d'erreur original
    error_msg = str(exc.orig) if exc.orig else str(exc)
    
    # Détection du type d'erreur d'intégrité
    if "duplicate key" in error_msg.lower():
        # Extraire le nom de la contrainte
        import re
        match = re.search(r'Key \((.*?)\)=', error_msg)
        if match:
            field = match.group(1)
            return build_error_response(
                request=request,
                code="DUPLICATE_ENTRY",
                message=f"Un enregistrement avec ce {field} existe déjà",
                status_code=status.HTTP_409_CONFLICT,
                details={"field": field, "error": error_msg},
                exception=exc
            )
    
    if "foreign key" in error_msg.lower():
        return build_error_response(
            request=request,
            code="FOREIGN_KEY_VIOLATION",
            message="Violation de contrainte de clé étrangère",
            status_code=status.HTTP_409_CONFLICT,
            details={"error": error_msg},
            exception=exc
        )
    
    return build_error_response(
        request=request,
        code="INTEGRITY_ERROR",
        message="Violation de contrainte de base de données",
        status_code=status.HTTP_409_CONFLICT,
        details={"error": error_msg},
        exception=exc
    )

async def data_error_handler(request: Request, exc: DataError):
    """Handler pour les erreurs de données SQL"""
    return build_error_response(
        request=request,
        code="DATA_ERROR",
        message="Erreur de format de données",
        status_code=status.HTTP_400_BAD_REQUEST,
        details={"error": str(exc)},
        exception=exc
    )

async def operational_error_handler(request: Request, exc: OperationalError):
    """Handler pour les erreurs opérationnelles SQL"""
    error_msg = str(exc)
    
    # Détection des erreurs de connexion
    if "connection" in error_msg.lower() or "timeout" in error_msg.lower():
        return build_error_response(
            request=request,
            code="DATABASE_CONNECTION_ERROR",
            message="Erreur de connexion à la base de données",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"error": error_msg},
            exception=exc
        )
    
    return build_error_response(
        request=request,
        code="DATABASE_OPERATIONAL_ERROR",
        message="Erreur opérationnelle de la base de données",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"error": error_msg},
        exception=exc
    )

async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    """Handler pour les erreurs SQLAlchemy globales"""
    return build_error_response(
        request=request,
        code="DATABASE_ERROR",
        message="Erreur de base de données",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"error": str(exc)},
        exception=exc
    )

async def rate_limit_exception_handler(request: Request, exc: RateLimitException):
    """Handler pour les exceptions de rate limiting"""
    retry_after = exc.details.get("retry_after", 60)
    
    return build_error_response(
        request=request,
        code="RATE_LIMIT_EXCEEDED",
        message=exc.message,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        details=exc.details,
        exception=exc
    ).headers.update({
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": "100",
        "X-RateLimit-Remaining": "0"
    })

async def general_exception_handler(request: Request, exc: Exception):
    """Handler pour toutes les autres exceptions système non interceptées"""
    # Logger avec stacktrace complet
    logger.error(
        f"❌ Exception non gérée: {exc.__class__.__name__} - {str(exc)}",
        exc_info=True,
        extra={
            "path": request.url.path,
            "method": request.method,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")
        }
    )
    
    # En développement, inclure plus de détails
    if hasattr(request.app, "debug") and request.app.debug:
        details = {
            "error": str(exc),
            "type": exc.__class__.__name__,
            "module": exc.__class__.__module__
        }
    else:
        details = {}
    
    return build_error_response(
        request=request,
        code="INTERNAL_ERROR",
        message="Une erreur interne est survenue. L'équipe technique a été notifiée.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details=details,
        exception=exc
    )

# ==================== CONFIGURATION ====================

def setup_exception_handlers(app):
    """
    Configure tous les handlers d'exceptions pour l'application FastAPI.
    
    Args:
        app: Instance FastAPI
    """
    # Handlers personnalisés
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(DataError, data_error_handler)
    app.add_exception_handler(OperationalError, operational_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(RateLimitException, rate_limit_exception_handler)
    
    # Handler générique (doit être le dernier)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info("✅ Exception handlers configurés")
    
    return app

# ==================== MIDDLEWARE D'ERREUR ====================

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware pour capturer les exceptions au niveau de la requête.
    Utile pour les erreurs qui se produisent avant les handlers.
    """
    
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Utiliser le handler général
            return await general_exception_handler(request, exc)