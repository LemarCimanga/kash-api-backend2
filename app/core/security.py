# app/core/security.py
import time
import logging
from typing import Dict, Tuple, Optional, List
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import ipaddress

from app.core.config import settings

logger = logging.getLogger(__name__)

class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Middleware de Rate Limiting en mémoire avec support de plusieurs stratégies.
    Limite le nombre de requêtes par IP ou par utilisateur pour éviter les attaques.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        requests_limit: int = 100,
        window_seconds: int = 60,
        strategy: str = "ip",  # "ip" ou "user"
        bypass_paths: Optional[List[str]] = None,
        whitelist_ips: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.strategy = strategy
        self.bypass_paths = bypass_paths or ["/health", "/health/db", "/health/live", "/health/ready"]
        self.whitelist_ips = [ipaddress.ip_network(ip) for ip in (whitelist_ips or [])]
        
        # Structure de stockage : { clé: [timestamps] }
        self.clients: Dict[str, list] = defaultdict(list)
        
        logger.info(f"🔒 Rate Limiter configuré: {requests_limit} req/{window_seconds}s, stratégie={strategy}")
    
    def _get_client_key(self, request: Request) -> str:
        """
        Détermine la clé de limitation selon la stratégie
        
        Args:
            request: Requête HTTP
            
        Returns:
            str: Clé unique pour l'identification
        """
        if self.strategy == "user":
            # Si l'utilisateur est authentifié, utiliser son ID
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                return f"user_{user_id}"
        
        # Par défaut, utiliser l'IP
        return self._get_client_ip(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Récupère l'IP réelle du client en tenant compte des proxies
        
        Args:
            request: Requête HTTP
            
        Returns:
            str: Adresse IP du client
        """
        # Vérifier les en-têtes de proxy
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Prendre la première IP (la plus proche du client)
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback sur l'IP directe
        return request.client.host if request.client else "unknown"
    
    def _is_ip_whitelisted(self, ip: str) -> bool:
        """
        Vérifie si l'IP est dans la liste blanche
        
        Args:
            ip: Adresse IP à vérifier
            
        Returns:
            bool: True si l'IP est autorisée sans limitation
        """
        try:
            ip_addr = ipaddress.ip_address(ip)
            for network in self.whitelist_ips:
                if ip_addr in network:
                    return True
        except ValueError:
            pass
        return False
    
    def _should_bypass(self, request: Request) -> bool:
        """
        Détermine si la requête doit contourner la limitation
        
        Args:
            request: Requête HTTP
            
        Returns:
            bool: True si la requête doit être exemptée
        """
        # Bypass pour les chemins spécifiques
        if request.url.path in self.bypass_paths:
            return True
        
        # Bypass pour les IP en liste blanche
        client_ip = self._get_client_ip(request)
        if self._is_ip_whitelisted(client_ip):
            return True
        
        # Bypass en mode debug
        if settings.DEBUG and request.url.path.startswith("/docs"):
            return True
        
        return False
    
    async def dispatch(self, request: Request, call_next):
        # Vérifier si la requête doit être exemptée
        if self._should_bypass(request):
            return await call_next(request)
        
        client_key = self._get_client_key(request)
        current_time = time.time()
        
        # Nettoyer l'historique des requêtes
        self.clients[client_key] = [
            t for t in self.clients[client_key] 
            if current_time - t < self.window_seconds
        ]
        
        # Vérifier la limite
        if len(self.clients[client_key]) >= self.requests_limit:
            logger.warning(f"⚠️ Rate limit dépassé pour {client_key}")
            
            # Ajouter un en-tête pour informer le client
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Trop de requêtes",
                    "message": f"Limite de {self.requests_limit} requêtes par {self.window_seconds} secondes",
                    "retry_after": self.window_seconds
                },
                headers={
                    "Retry-After": str(self.window_seconds),
                    "X-RateLimit-Limit": str(self.requests_limit),
                    "X-RateLimit-Remaining": "0",
                }
            )
        
        # Enregistrer la requête
        self.clients[client_key].append(current_time)
        
        # Ajouter des en-têtes de rate limit
        response = await call_next(request)
        remaining = self.requests_limit - len(self.clients[client_key])
        response.headers["X-RateLimit-Limit"] = str(self.requests_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(current_time + self.window_seconds))
        
        return response
    
    def get_stats(self) -> Dict:
        """
        Récupère les statistiques du rate limiter
        
        Returns:
            Dict: Statistiques
        """
        total_keys = len(self.clients)
        total_requests = sum(len(requests) for requests in self.clients.values())
        
        return {
            "total_keys": total_keys,
            "total_requests": total_requests,
            "limit": self.requests_limit,
            "window_seconds": self.window_seconds,
            "strategy": self.strategy,
        }


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware injectant les en-têtes HTTP de sécurité standard (OWASP Top 10).
    Protection contre XSS, Clickjacking, MIME-sniffing, etc.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,  # 1 an
        enable_csp: bool = True,
        csp_directives: Optional[Dict[str, str]] = None,
    ):
        super().__init__(app)
        self.enable_hsts = enable_hsts and settings.is_production
        self.hsts_max_age = hsts_max_age
        self.enable_csp = enable_csp
        
        # Politique CSP par défaut
        self.csp_directives = csp_directives or {
            "default-src": "'self'",
            "script-src": "'self' 'unsafe-inline' 'unsafe-eval'",
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data: https:",
            "font-src": "'self'",
            "connect-src": "'self'",
            "frame-ancestors": "'none'",
            "form-action": "'self'",
            "base-uri": "'self'",
            "object-src": "'none'",
        }
        
        logger.info("🛡️ Headers de sécurité configurés")
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # En-têtes de sécurité de base
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), bluetooth=(), "
            "autoplay=(), encrypted-media=()"
        )
        
        # HSTS (uniquement en production)
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )
        
        # Content Security Policy
        if self.enable_csp:
            csp_value = "; ".join([f"{k} {v}" for k, v in self.csp_directives.items()])
            response.headers["Content-Security-Policy"] = csp_value
        
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware ajoutant un ID unique à chaque requête pour le tracing
    """
    
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name
    
    async def dispatch(self, request: Request, call_next):
        import uuid
        
        # Générer ou récupérer un ID de requête
        request_id = request.headers.get(self.header_name)
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Ajouter l'ID à l'état de la requête
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers[self.header_name] = request_id
        
        return response


class IPFilterMiddleware(BaseHTTPMiddleware):
    """
    Middleware pour filtrer les IP autorisées (listes blanche/noire)
    """
    
    def __init__(
        self,
        app: ASGIApp,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.whitelist = [ipaddress.ip_network(ip) for ip in (whitelist or [])]
        self.blacklist = [ipaddress.ip_network(ip) for ip in (blacklist or [])]
        
        logger.info(f"🛡️ Filtrage IP: {len(self.whitelist)} réseaux autorisés, {len(self.blacklist)} réseaux bloqués")
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        
        try:
            ip_addr = ipaddress.ip_address(client_ip)
        except ValueError:
            # IP invalide, refuser l'accès
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Adresse IP invalide"
            )
        
        # Vérifier la liste noire
        for network in self.blacklist:
            if ip_addr in network:
                logger.warning(f"⛔ IP bloquée: {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Accès refusé"
                )
        
        # Vérifier la liste blanche (si définie)
        if self.whitelist:
            allowed = False
            for network in self.whitelist:
                if ip_addr in network:
                    allowed = True
                    break
            
            if not allowed:
                logger.warning(f"⛔ IP non autorisée: {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Accès non autorisé"
                )
        
        return await call_next(request)


# ==================== FONCTION DE CONFIGURATION GLOBALE ====================
def setup_security(app: FastAPI) -> None:
    """
    Fonction globale pour initialiser toute la couche de sécurité de l'API FastAPI.
    À appeler dans main.py.
    
    Args:
        app: Instance FastAPI
    """
    logger.info("🛡️ Initialisation de la couche de sécurité...")
    
    # 1. Configuration du CORS
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
            expose_headers=["X-Request-ID", "X-Process-Time"],
            max_age=86400,  # 24 heures
        )
        logger.info(f"✅ CORS configuré: {settings.BACKEND_CORS_ORIGINS}")
    else:
        logger.warning("⚠️ Aucune origine CORS configurée")
    
    # 2. ID de requête (pour le tracing)
    app.add_middleware(RequestIDMiddleware)
    logger.info("✅ Request ID middleware activé")
    
    # 3. Headers de sécurité
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=settings.is_production,
        hsts_max_age=31536000,
    )
    logger.info("✅ Headers de sécurité activés")
    
    # 4. Rate Limiting (ex: 60 requêtes par minute par IP)
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(
            RateLimiterMiddleware,
            requests_limit=settings.RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_PERIOD,
            strategy="ip",
            bypass_paths=["/health", "/health/db", "/health/live", "/health/ready", "/docs", "/redoc", "/openapi.json"],
        )
        logger.info(f"✅ Rate Limiter activé: {settings.RATE_LIMIT_REQUESTS} req/{settings.RATE_LIMIT_PERIOD}s")
    else:
        logger.info("ℹ️ Rate Limiter désactivé")
    
    # 5. Filtrage IP (optionnel - décommenter si nécessaire)
    # if settings.ALLOWED_IPS:
    #     app.add_middleware(IPFilterMiddleware, whitelist=settings.ALLOWED_IPS)
    #     logger.info(f"✅ Filtrage IP activé: {settings.ALLOWED_IPS}")
    
    logger.info("✅ Sécurité initialisée avec succès")


# ==================== FONCTIONS UTILITAIRES ====================
def get_client_ip(request: Request) -> str:
    """
    Fonction utilitaire pour récupérer l'IP du client depuis une requête
    
    Args:
        request: Requête FastAPI
        
    Returns:
        str: Adresse IP du client
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    return request.client.host if request.client else "unknown"


def get_request_id(request: Request) -> str:
    """
    Récupère l'ID de la requête
    
    Args:
        request: Requête FastAPI
        
    Returns:
        str: ID de la requête
    """
    return getattr(request.state, "request_id", "unknown")