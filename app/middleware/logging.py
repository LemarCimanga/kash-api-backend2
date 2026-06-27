# app/middleware/logging.py
import time
import logging
import json
from typing import Dict, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.security import get_client_ip, get_request_id

# Configuration du logger JSON
json_logger = logging.getLogger("api_access")

# Configuration du formateur JSON
class JSONFormatter(logging.Formatter):
    """Formatter JSON pour les logs structurés"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "timestamp_ms": int(record.created * 1000),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Ajouter les extra fields s'ils existent
        if hasattr(record, 'extra'):
            log_data.update(record.extra)
        
        # Ajouter les exceptions si présentes
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)

# Appliquer le formateur JSON
if not json_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    json_logger.addHandler(handler)
    json_logger.setLevel(logging.INFO)

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware pour le logging structuré JSON de chaque requête entrante/sortante"""
    
    # Configuration des chemins à ignorer
    IGNORE_PATHS = ["/health", "/health/db", "/health/live", "/health/ready", "/metrics"]
    IGNORE_STATIC = [".css", ".js", ".png", ".jpg", ".ico", ".svg"]
    
    def __init__(self, app, log_body: bool = False, log_headers: bool = False):
        """
        Args:
            app: Application FastAPI
            log_body: Logger le corps des requêtes/réponses (désactivé par défaut pour sécurité)
            log_headers: Logger les headers (désactivé par défaut pour sécurité)
        """
        super().__init__(app)
        self.log_body = log_body
        self.log_headers = log_headers
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Vérifier si la requête doit être ignorée
        if self._should_ignore(request):
            return await call_next(request)
        
        # Capture des métadonnées de la requête
        request_data = self._get_request_data(request)
        
        # Si log_body est activé et que c'est une requête POST/PUT/PATCH
        if self.log_body and request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    request_data["body"] = body.decode("utf-8")[:1000]  # Limiter à 1000 caractères
            except Exception:
                pass
        
        # Traitement de la requête
        try:
            response = await call_next(request)
        except Exception as e:
            # En cas d'erreur fatale non gérée
            duration = (time.time() - start_time) * 1000
            json_logger.error(
                "request_failed", 
                extra={
                    **request_data, 
                    "error": str(e), 
                    "error_type": type(e).__name__,
                    "duration_ms": round(duration, 2)
                }
            )
            raise e
        
        # Log de la réponse
        duration_ms = (time.time() - start_time) * 1000
        response_data = self._get_response_data(request_data, response, duration_ms)
        
        # Choisir le niveau de log selon le code de réponse
        log_level = self._get_log_level(response.status_code)
        
        if log_level == "error":
            json_logger.error("request_completed", extra=response_data)
        elif log_level == "warning":
            json_logger.warning("request_completed", extra=response_data)
        else:
            json_logger.info("request_completed", extra=response_data)
        
        return response
    
    def _should_ignore(self, request: Request) -> bool:
        """Vérifie si la requête doit être ignorée des logs"""
        # Ignorer les chemins spécifiques
        if request.url.path in self.IGNORE_PATHS:
            return True
        
        # Ignorer les fichiers statiques
        for ext in self.IGNORE_STATIC:
            if request.url.path.endswith(ext):
                return True
        
        return False
    
    def _get_request_data(self, request: Request) -> Dict[str, Any]:
        """Extrait les métadonnées de la requête"""
        data = {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params),
            "client_ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent", "unknown"),
            "request_id": get_request_id(request),
            "host": request.headers.get("host", "unknown"),
            "referer": request.headers.get("referer", ""),
        }
        
        if self.log_headers:
            # Logger les headers sélectifs (éviter les tokens)
            safe_headers = {
                "content-type": request.headers.get("content-type"),
                "accept": request.headers.get("accept"),
                "accept-language": request.headers.get("accept-language"),
                "origin": request.headers.get("origin"),
                "x-forwarded-for": request.headers.get("x-forwarded-for"),
            }
            data["headers"] = safe_headers
        
        return data
    
    def _get_response_data(self, request_data: Dict, response: Response, duration_ms: float) -> Dict[str, Any]:
        """Construit les données de réponse"""
        data = {
            **request_data,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "size": int(response.headers.get("content-length", 0)),
        }
        
        if self.log_headers:
            data["response_headers"] = {
                "content-type": response.headers.get("content-type"),
                "content-length": response.headers.get("content-length"),
            }
        
        return data
    
    def _get_log_level(self, status_code: int) -> str:
        """Détermine le niveau de log selon le code HTTP"""
        if status_code >= 500:
            return "error"
        elif status_code >= 400:
            return "warning"
        else:
            return "info"

# ==================== FONCTION UTILITAIRE ====================
def setup_logging_middleware(app, log_body: bool = False, log_headers: bool = False):
    """
    Configure le middleware de logging pour l'application
    
    Args:
        app: Application FastAPI
        log_body: Logger le corps des requêtes (désactivé par défaut)
        log_headers: Logger les headers (désactivé par défaut)
    """
    app.add_middleware(
        StructuredLoggingMiddleware,
        log_body=log_body,
        log_headers=log_headers
    )
    json_logger.info("✅ Structured logging middleware configuré")
    
    return app

# ==================== EXEMPLE DE LOGS ====================
# {
#   "timestamp": "2024-01-15 10:30:45",
#   "timestamp_ms": 1705319445123,
#   "level": "info",
#   "name": "api_access",
#   "message": "request_completed",
#   "method": "GET",
#   "path": "/api/v1/users",
#   "client_ip": "192.168.1.100",
#   "user_agent": "Mozilla/5.0...",
#   "request_id": "abc-123-def",
#   "status_code": 200,
#   "duration_ms": 45.32,
#   "size": 1024
# }