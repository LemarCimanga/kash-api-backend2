# app/schemas/token.py
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum

# ==================== ENUMS ====================
class TokenType(str, Enum):
    """Types de tokens JWT"""
    ACCESS = "access"
    REFRESH = "refresh"
    RESET = "reset"
    VERIFICATION = "verification"

class TokenStatus(str, Enum):
    """Statuts possibles d'un token"""
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"

# ==================== SCHÉMAS DE BASE ====================
class TokenData(BaseModel):
    """
    Structure des données embarquées (payload) dans le jeton JWT
    """
    sub: Optional[str] = Field(None, description="ID ou matricule de l'utilisateur")
    role: Optional[str] = Field(None, description="Rôle de l'utilisateur")
    statut: Optional[str] = Field(None, description="Statut du compte utilisateur")
    type: Optional[TokenType] = Field(TokenType.ACCESS, description="Type de token")
    exp: Optional[int] = Field(None, description="Timestamp d'expiration")
    iat: Optional[int] = Field(None, description="Timestamp de création")
    iss: Optional[str] = Field(None, description="Émetteur du token")
    aud: Optional[str] = Field(None, description="Audience du token")
    
    class Config:
        use_enum_values = True

# ==================== SCHÉMAS DE REQUÊTE ====================
class TokenRefreshRequest(BaseModel):
    """
    Schéma requis pour demander le renouvellement d'un Access Token
    """
    refresh_token: str = Field(
        ..., 
        description="Le jeton de rafraîchissement (Refresh Token) valide fourni lors de la connexion",
        min_length=10
    )
    
    @field_validator("refresh_token")
    @classmethod
    def validate_refresh_token(cls, v: str) -> str:
        """Valide le format du refresh token"""
        if not v or len(v) < 10:
            raise ValueError("Le refresh token doit être valide")
        return v.strip()

class TokenVerifyRequest(BaseModel):
    """
    Schéma pour vérifier la validité d'un token
    """
    token: str = Field(..., description="Token à vérifier")
    token_type: Optional[TokenType] = Field(TokenType.ACCESS, description="Type de token attendu")

class TokenRevokeRequest(BaseModel):
    """
    Schéma pour révoquer un token
    """
    token: str = Field(..., description="Token à révoquer")
    reason: Optional[str] = Field(None, description="Raison de la révocation")

# ==================== SCHÉMAS DE RÉPONSE ====================
class UserTokenPayload(BaseModel):
    """
    Sous-schéma pour injecter les données utilisateur dans la réponse de connexion
    Optimisé pour l'application Flutter
    """
    id: int = Field(..., description="ID unique de l'utilisateur")
    matricule: str = Field(..., description="Matricule unique")
    nom: str = Field(..., description="Nom de famille")
    prenom: str = Field(..., description="Prénom")
    role: str = Field(..., description="Rôle de l'utilisateur")
    statut: str = Field(..., description="Statut du compte")
    photo: Optional[str] = Field("", description="URL de la photo de profil")
    email: Optional[str] = Field(None, description="Email de l'utilisateur")
    numero_telephone: Optional[str] = Field(None, description="Numéro de téléphone")
    
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    """
    Schéma de réponse standard renvoyé à l'application Flutter après authentification
    """
    access_token: str = Field(..., description="Jeton JWT pour authentifier les requêtes HTTP suivantes")
    refresh_token: str = Field(..., description="Jeton longue durée permettant d'obtenir un nouvel access_token")
    token_type: str = Field(default="bearer", description="Type de jeton (toujours 'bearer')")
    expires_in: int = Field(..., description="Durée de validité en secondes")
    refresh_expires_in: Optional[int] = Field(None, description="Durée de validité du refresh token en secondes")
    user: Optional[UserTokenPayload] = Field(None, description="Informations minimales sur l'utilisateur connecté")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIs...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
                "token_type": "bearer",
                "expires_in": 28800,
                "refresh_expires_in": 2592000,
                "user": {
                    "id": 1,
                    "matricule": "KASH26001",
                    "nom": "Kabasele",
                    "prenom": "Jean",
                    "role": "admin",
                    "statut": "actif",
                    "photo": "https://example.com/photo.jpg"
                }
            }
        }

class TokenVerifyResponse(BaseModel):
    """
    Réponse pour la vérification d'un token
    """
    valid: bool = Field(..., description="Indique si le token est valide")
    status: TokenStatus = Field(..., description="Statut du token")
    user_id: Optional[int] = Field(None, description="ID de l'utilisateur associé")
    matricule: Optional[str] = Field(None, description="Matricule de l'utilisateur")
    role: Optional[str] = Field(None, description="Rôle de l'utilisateur")
    expires_at: Optional[datetime] = Field(None, description="Date d'expiration du token")
    issued_at: Optional[datetime] = Field(None, description="Date de création du token")
    remaining_seconds: Optional[int] = Field(None, description="Temps restant en secondes")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

class TokenRevokeResponse(BaseModel):
    """
    Réponse pour la révocation d'un token
    """
    success: bool = Field(..., description="Indique si la révocation a réussi")
    message: str = Field(..., description="Message d'information")
    revoked_at: datetime = Field(default_factory=datetime.utcnow, description="Date de révocation")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# ==================== SCHÉMAS DE LOGS DE TOKENS ====================
class TokenLogEntry(BaseModel):
    """
    Schéma pour les logs d'utilisation des tokens
    """
    token_id: Optional[str] = None
    user_id: int
    action: str  # "created", "used", "refreshed", "revoked", "expired"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Optional[Dict[str, Any]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# ==================== SCHÉMAS DE STATISTIQUES ====================
class TokenStats(BaseModel):
    """
    Statistiques d'utilisation des tokens
    """
    total_issued: int = Field(0, description="Nombre total de tokens émis")
    active_tokens: int = Field(0, description="Nombre de tokens actifs")
    expired_tokens: int = Field(0, description="Nombre de tokens expirés")
    revoked_tokens: int = Field(0, description="Nombre de tokens révoqués")
    last_issued_at: Optional[datetime] = None
    last_refreshed_at: Optional[datetime] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }