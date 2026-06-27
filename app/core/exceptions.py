# app/core/exceptions.py
from typing import Any, Dict, Optional, List
from fastapi import HTTPException, status
from datetime import datetime

# ==================== EXCEPTION DE BASE ====================

class AppException(Exception):
    """
    Exception de base pour l'application.
    Toutes les exceptions personnalisées doivent hériter de celle-ci.
    """
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'exception en dictionnaire pour la réponse API"""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "timestamp": self.timestamp
            }
        }

# ==================== EXCEPTIONS HTTP 4XX ====================

class NotFoundException(AppException):
    """Exception pour les ressources non trouvées (404)"""
    def __init__(self, resource: str, identifier: Any, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"{resource} avec l'identifiant '{identifier}' non trouvé",
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details={
                "resource": resource,
                "identifier": str(identifier),
                **(details or {})
            }
        )

class ValidationException(AppException):
    """Exception pour les erreurs de validation (422)"""
    def __init__(self, message: str, errors: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"errors": errors or {}}
        )

class DuplicateException(AppException):
    """Exception pour les doublons (409)"""
    def __init__(self, field: str, value: Any, message: Optional[str] = None):
        super().__init__(
            message=message or f"La valeur '{value}' pour le champ '{field}' existe déjà",
            code="DUPLICATE_ENTRY",
            status_code=status.HTTP_409_CONFLICT,
            details={"field": field, "value": str(value)}
        )

class SecurityException(AppException):
    """Exception pour les problèmes de sécurité (403)"""
    def __init__(self, message: str = "Accès non autorisé", code: str = "SECURITY_ERROR"):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_403_FORBIDDEN
        )

class AuthenticationException(AppException):
    """Exception pour les problèmes d'authentification (401)"""
    def __init__(self, message: str = "Non authentifié", code: str = "AUTHENTICATION_ERROR"):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"}
        )

class RateLimitException(AppException):
    """Exception pour le rate limiting (429)"""
    def __init__(self, retry_after: int = 60, message: Optional[str] = None):
        super().__init__(
            message=message or f"Trop de requêtes. Réessayez dans {retry_after} secondes",
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)}
        )

class BadRequestException(AppException):
    """Exception pour les requêtes invalides (400)"""
    def __init__(self, message: str = "Requête invalide", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="BAD_REQUEST",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details or {}
        )

class ConflictException(AppException):
    """Exception pour les conflits (409)"""
    def __init__(self, message: str = "Conflit détecté", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            details=details or {}
        )

class GoneException(AppException):
    """Exception pour les ressources supprimées (410)"""
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            message=f"{resource} avec l'identifiant '{identifier}' a été supprimé",
            code="GONE",
            status_code=status.HTTP_410_GONE,
            details={"resource": resource, "identifier": str(identifier)}
        )

class UnprocessableEntityException(AppException):
    """Exception pour les entités non traitables (422)"""
    def __init__(self, message: str = "Entité non traitable", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="UNPROCESSABLE_ENTITY",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details or {}
        )

# ==================== EXCEPTIONS MÉTIER ====================

class BusinessException(AppException):
    """Exception pour les règles métier (400)"""
    def __init__(self, message: str, code: str = "BUSINESS_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details or {}
        )

class InsufficientPermissionException(SecurityException):
    """Exception pour les permissions insuffisantes"""
    def __init__(self, required_role: str, current_role: str):
        super().__init__(
            message=f"Permissions insuffisantes. Rôle requis: {required_role}",
            code="INSUFFICIENT_PERMISSION"
        )
        self.details = {
            "required_role": required_role,
            "current_role": current_role
        }

class AccountLockedException(AppException):
    """Exception pour les comptes verrouillés (403)"""
    def __init__(self, locked_until: datetime):
        super().__init__(
            message=f"Compte verrouillé jusqu'à {locked_until.strftime('%H:%M:%S')}",
            code="ACCOUNT_LOCKED",
            status_code=status.HTTP_403_FORBIDDEN,
            details={"locked_until": locked_until.isoformat()}
        )

class InactiveAccountException(AppException):
    """Exception pour les comptes inactifs (403)"""
    def __init__(self):
        super().__init__(
            message="Ce compte est désactivé",
            code="ACCOUNT_INACTIVE",
            status_code=status.HTTP_403_FORBIDDEN
        )

class ExpiredTokenException(AppException):
    """Exception pour les tokens expirés (401)"""
    def __init__(self):
        super().__init__(
            message="Token expiré",
            code="TOKEN_EXPIRED",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"}
        )

class InvalidTokenException(AppException):
    """Exception pour les tokens invalides (401)"""
    def __init__(self):
        super().__init__(
            message="Token invalide",
            code="TOKEN_INVALID",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"}
        )

class MasterCodeInvalidException(AppException):
    """Exception pour les codes master invalides (400)"""
    def __init__(self, reason: str = "Code invalide"):
        super().__init__(
            message=reason,
            code="MASTER_CODE_INVALID",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class MasterCodeExpiredException(AppException):
    """Exception pour les codes master expirés (400)"""
    def __init__(self):
        super().__init__(
            message="Ce code master a expiré",
            code="MASTER_CODE_EXPIRED",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class MasterCodeUsedException(AppException):
    """Exception pour les codes master déjà utilisés (400)"""
    def __init__(self):
        super().__init__(
            message="Ce code master a déjà été utilisé",
            code="MASTER_CODE_USED",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class PaymentException(AppException):
    """Exception pour les erreurs de paiement (400)"""
    def __init__(self, message: str = "Erreur de paiement", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="PAYMENT_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details or {}
        )

class PaymentFailedException(PaymentException):
    """Exception pour les paiements échoués"""
    def __init__(self, transaction_id: str, reason: str):
        super().__init__(
            message=f"Paiement échoué: {reason}",
            details={"transaction_id": transaction_id, "reason": reason}
        )

class InsufficientFundsException(PaymentException):
    """Exception pour les fonds insuffisants"""
    def __init__(self, required: float, available: float):
        super().__init__(
            message=f"Fonds insuffisants. Besoin de {required} disponible {available}",
            details={"required": required, "available": available}
        )

class FileUploadException(AppException):
    """Exception pour les erreurs d'upload (400)"""
    def __init__(self, message: str = "Erreur d'upload de fichier"):
        super().__init__(
            message=message,
            code="FILE_UPLOAD_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class FileTooLargeException(FileUploadException):
    """Exception pour les fichiers trop volumineux"""
    def __init__(self, max_size: int, file_size: int):
        super().__init__(
            message=f"Fichier trop volumineux. Max: {max_size} bytes, Reçu: {file_size} bytes",
            details={"max_size": max_size, "file_size": file_size}
        )

class InvalidFileTypeException(FileUploadException):
    """Exception pour les types de fichiers non autorisés"""
    def __init__(self, allowed_types: List[str], file_type: str):
        super().__init__(
            message=f"Type de fichier non autorisé. Types autorisés: {', '.join(allowed_types)}",
            details={"allowed_types": allowed_types, "file_type": file_type}
        )

# ==================== EXCEPTIONS SYSTÈME ====================

class DatabaseException(AppException):
    """Exception pour les erreurs de base de données (500)"""
    def __init__(self, message: str = "Erreur de base de données", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details or {}
        )

class ExternalServiceException(AppException):
    """Exception pour les erreurs de services externes (502)"""
    def __init__(self, service: str, message: str = "Service externe indisponible"):
        super().__init__(
            message=f"{message}: {service}",
            code="EXTERNAL_SERVICE_ERROR",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"service": service}
        )

class TimeoutException(AppException):
    """Exception pour les timeouts (504)"""
    def __init__(self, operation: str):
        super().__init__(
            message=f"Timeout lors de l'opération: {operation}",
            code="TIMEOUT_ERROR",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            details={"operation": operation}
        )

class ConfigurationException(AppException):
    """Exception pour les erreurs de configuration (500)"""
    def __init__(self, message: str = "Erreur de configuration"):
        super().__init__(
            message=message,
            code="CONFIG_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# ==================== FONCTIONS UTILITAIRES ====================

def is_app_exception(exc: Exception) -> bool:
    """Vérifie si une exception est une AppException"""
    return isinstance(exc, AppException)

def get_exception_status_code(exc: Exception) -> int:
    """Récupère le code HTTP d'une exception"""
    if isinstance(exc, AppException):
        return exc.status_code
    if isinstance(exc, HTTPException):
        return exc.status_code
    return status.HTTP_500_INTERNAL_SERVER_ERROR

def get_exception_details(exc: Exception) -> Dict[str, Any]:
    """Récupère les détails d'une exception"""
    if isinstance(exc, AppException):
        return exc.details
    return {"error": str(exc)}

# ==================== EXPORTATIONS ====================

__all__ = [
    # Base
    "AppException",
    
    # HTTP 4XX
    "NotFoundException",
    "ValidationException",
    "DuplicateException",
    "SecurityException",
    "AuthenticationException",
    "RateLimitException",
    "BadRequestException",
    "ConflictException",
    "GoneException",
    "UnprocessableEntityException",
    
    # Métier
    "BusinessException",
    "InsufficientPermissionException",
    "AccountLockedException",
    "InactiveAccountException",
    "ExpiredTokenException",
    "InvalidTokenException",
    "MasterCodeInvalidException",
    "MasterCodeExpiredException",
    "MasterCodeUsedException",
    "PaymentException",
    "PaymentFailedException",
    "InsufficientFundsException",
    "FileUploadException",
    "FileTooLargeException",
    "InvalidFileTypeException",
    
    # Système
    "DatabaseException",
    "ExternalServiceException",
    "TimeoutException",
    "ConfigurationException",
    
    # Utilitaires
    "is_app_exception",
    "get_exception_status_code",
    "get_exception_details",
]