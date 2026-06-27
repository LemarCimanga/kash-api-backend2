from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
import re

# ==================== ENUMS ====================
class UserRole(str, Enum):
    """Rôles utilisateur disponibles"""
    ADMIN = "admin"
    GERANT = "gerant"
    AGENT_BOUTIQUE = "agent boutique"
    SERVEUR = "serveur"
    CAISSIER_RESTO = "caissier_resto"
    AGENT_CUISINE = "agent cuisine"

class UserStatus(str, Enum):
    """Statuts utilisateur disponibles"""
    ACTIF = "actif"
    INACTIF = "inactif"
    SUSPENDU = "suspendu"

class UserLockReason(str, Enum):
    """Raisons de verrouillage du compte"""
    LOGIN_ATTEMPTS = "tentatives_connexion_excessives"
    ADMIN = "verrouillage_admin"
    SECURITY = "raison_securite"
    INACTIVITY = "inactivite_prolongee"

# ==================== SCHÉMAS DE BASE ====================
class UtilisateurBase(BaseModel):
    nom: str = Field(
        ..., 
        max_length=50, 
        min_length=1,
        description="Nom de famille"
    )
    postnom: str = Field(
        ..., 
        max_length=50, 
        min_length=1,
        description="Postnom (nom du père)"
    )
    prenom: str = Field(
        ..., 
        max_length=50, 
        min_length=1,
        description="Prénom"
    )
    numero_telephone: Optional[str] = Field(
        None, 
        max_length=20,
        description="Numéro de téléphone (format international)"
    )
    email: Optional[str] = Field(
        None,
        max_length=100,
        description="Adresse email (optionnelle)"
    )
    role: UserRole = Field(
        ...,
        description="Rôle de l'utilisateur"
    )
    photo: Optional[str] = Field(
        None,
        description="URL ou chemin de la photo"
    )
    
    @field_validator("nom", "postnom", "prenom")
    @classmethod
    def validate_name_fields(cls, value: str) -> str:
        """Valide les champs de nom"""
        if not value:
            raise ValueError("Ce champ ne peut pas être vide")
        
        value = value.strip()
        
        # Supprimer les espaces multiples
        value = re.sub(r'\s+', ' ', value)
        
        # Vérifier les caractères autorisés
        if not re.match(r"^[a-zA-ZÀ-ÿ\s\-']+$", value):
            raise ValueError("Caractères invalides dans le nom")
        
        # Mettre en forme (première lettre majuscule)
        return value.title()
    
    @field_validator("numero_telephone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        """Valide le format du numéro de téléphone"""
        if value:
            value = value.strip()
            # Nettoyer les espaces et caractères spéciaux
            value = re.sub(r'[\s\-\(\)]', '', value)
            
            # Vérifier le format (international ou local)
            if not re.match(r"^\+?[0-9]{8,15}$", value):
                raise ValueError(
                    "Format de téléphone invalide. Utilisez le format international "
                    "(ex: +243812345678) ou local (ex: 0812345678)"
                )
            
            # Ajouter le préfixe + si absent
            if not value.startswith('+'):
                # Supposons que c'est un numéro congolais
                if value.startswith('0'):
                    value = '+243' + value[1:]
                else:
                    value = '+243' + value
            
        return value
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        """Valide le format de l'email"""
        if value:
            value = value.strip().lower()
            
            # Validation plus stricte
            pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(pattern, value):
                raise ValueError("Format d'email invalide")
            
            # Vérifier les domaines courants
            domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
            domain = value.split('@')[1]
            # Optionnel: ajouter des règles spécifiques
            
        return value

# ==================== SCHÉMAS DE CRÉATION ====================
class UtilisateurCreate(UtilisateurBase):
    password: str = Field(
        ...,
        min_length=4,
        max_length=255,
        description="Mot de passe (min 4 caractères)"
    )
    master_code: str = Field(
        ...,
        description="Code d'activation obligatoire"
    )
    created_by: Optional[int] = Field(
        None,
        description="ID de l'utilisateur qui crée"
    )
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Valide la complexité du mot de passe"""
        if len(value) < 4:
            raise ValueError("Le mot de passe doit contenir au moins 4 caractères")
        
        # Recommandations de complexité (non bloquant)
        warnings = []
        if len(value) < 8:
            warnings.append("Pour plus de sécurité, utilisez au moins 8 caractères")
        if not any(c.isdigit() for c in value):
            warnings.append("Pour plus de sécurité, incluez au moins un chiffre")
        if not any(c.isupper() for c in value):
            warnings.append("Pour plus de sécurité, incluez au moins une majuscule")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in value):
            warnings.append("Pour plus de sécurité, incluez au moins un caractère spécial")
        
        # Vous pouvez logger les warnings mais pas bloquer
        # logger.info(f"Password warnings: {warnings}")
        
        return value
    
    @field_validator("master_code")
    @classmethod
    def validate_master_code(cls, value: str) -> str:
        """Valide le code d'activation"""
        if not value:
            raise ValueError("Le code d'activation est requis")
        
        value = value.strip().upper()
        
        # Le code doit être alphanumérique
        if not value.isalnum():
            raise ValueError("Le code doit être alphanumérique")
        
        # Longueur minimale
        if len(value) < 4:
            raise ValueError("Le code doit contenir au moins 4 caractères")
        
        return value
    
    @model_validator(mode='after')
    def validate_contact_method(self) -> 'UtilisateurCreate':
        """S'assure qu'au moins un moyen de contact est fourni"""
        if not self.numero_telephone and not self.email:
            raise ValueError(
                "Au moins un moyen de contact (téléphone ou email) est requis"
            )
        return self

# ==================== SCHÉMAS DE MISE À JOUR ====================
class UtilisateurUpdate(BaseModel):
    nom: Optional[str] = Field(None, max_length=50, min_length=1)
    postnom: Optional[str] = Field(None, max_length=50, min_length=1)
    prenom: Optional[str] = Field(None, max_length=50, min_length=1)
    numero_telephone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    statut: Optional[UserStatus] = None
    photo: Optional[str] = None
    
    # Réutilisation des validateurs de UtilisateurBase
    @field_validator("nom", "postnom", "prenom")
    @classmethod
    def validate_name_fields(cls, value: Optional[str]) -> Optional[str]:
        if value:
            return UtilisateurBase.validate_name_fields(value)
        return value
    
    @field_validator("numero_telephone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value:
            return UtilisateurBase.validate_phone(value)
        return value
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value:
            return UtilisateurBase.validate_email(value)
        return value
    
    @model_validator(mode='after')
    def validate_update(self) -> 'UtilisateurUpdate':
        """Vérifie qu'au moins un champ est fourni pour la mise à jour"""
        changes = self.model_dump(exclude_unset=True)
        if not changes:
            raise ValueError("Au moins un champ doit être fourni pour la mise à jour")
        return self

# ==================== SCHÉMAS DE CHANGEMENT DE MOT DE PASSE ====================
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(
        ...,
        min_length=4,
        description="Mot de passe actuel"
    )
    new_password: str = Field(
        ...,
        min_length=4,
        description="Nouveau mot de passe"
    )
    confirm_password: str = Field(
        ...,
        min_length=4,
        description="Confirmation du nouveau mot de passe"
    )
    
    @model_validator(mode='after')
    def validate_passwords(self) -> 'ChangePasswordRequest':
        """Valide les mots de passe"""
        # Vérifier que les mots de passe correspondent
        if self.new_password != self.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas")
        
        # Vérifier que le nouveau mot de passe est différent de l'ancien
        if self.old_password == self.new_password:
            raise ValueError(
                "Le nouveau mot de passe doit être différent de l'ancien"
            )
        
        # Vérifier la longueur
        if len(self.new_password) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        
        return self

# ==================== SCHÉMAS DE RÉINITIALISATION ====================
class ResetPasswordRequest(BaseModel):
    email_or_phone: str = Field(
        ...,
        description="Email ou numéro de téléphone"
    )
    
    @field_validator("email_or_phone")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        """Valide l'identifiant (email ou téléphone)"""
        value = value.strip()
        
        # Tester si c'est un email
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if re.match(email_pattern, value):
            return value
        
        # Tester si c'est un téléphone
        phone = re.sub(r'[\s\-\(\)]', '', value)
        if re.match(r"^\+?[0-9]{8,15}$", phone):
            return phone
        
        raise ValueError(
            "L'identifiant doit être un email valide ou un numéro de téléphone"
        )

class ResetPasswordConfirmRequest(BaseModel):
    token: str = Field(..., description="Token de réinitialisation")
    new_password: str = Field(..., min_length=8, description="Nouveau mot de passe")
    confirm_password: str = Field(..., min_length=8, description="Confirmation")
    
    @model_validator(mode='after')
    def validate_passwords(self) -> 'ResetPasswordConfirmRequest':
        if self.new_password != self.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas")
        return self

# ==================== SCHÉMAS DE RÉPONSE ====================
class UtilisateurResponse(UtilisateurBase):
    id: int
    matricule: str
    statut: UserStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    derniere_connexion: Optional[datetime] = None
    created_by: Optional[int] = None
    is_locked: bool = False
    is_active: bool = True
    
    class Config:
        from_attributes = True
        use_enum_values = True  # Retourne les valeurs des enums
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

class UtilisateurDetailResponse(UtilisateurResponse):
    """Réponse avec des détails supplémentaires"""
    tentative_connexion: int
    verrouille_jusqua: Optional[datetime] = None
    derniere_ip: Optional[str] = None
    creator_name: Optional[str] = None
    password_changed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

class UtilisateurListResponse(BaseModel):
    """Réponse pour la liste paginée des utilisateurs"""
    total: int
    page: int
    per_page: int
    items: List[UtilisateurResponse]
    
    class Config:
        from_attributes = True

# ==================== SCHÉMAS D'AUTHENTIFICATION ====================
class LoginRequest(BaseModel):
    matricule: str = Field(..., description="Matricule de l'utilisateur")
    password: str = Field(..., description="Mot de passe")
    
    @field_validator("matricule")
    @classmethod
    def validate_matricule(cls, value: str) -> str:
        """Valide le format du matricule"""
        value = value.strip().upper()
        
        # Format attendu: KASH + 5 chiffres
        if not re.match(r"^KASH\d{5}$", value):
            raise ValueError("Format de matricule invalide (ex: KASH26001)")
        
        return value

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 480  # minutes
    refresh_token: Optional[str] = None
    
    class Config:
        from_attributes = True

class LoginResponse(BaseModel):
    """Réponse complète de connexion"""
    user: UtilisateurResponse
    token: TokenResponse
    
    class Config:
        from_attributes = True

# ==================== SCHÉMAS D'ERREUR ====================
class ErrorResponse(BaseModel):
    detail: str
    code: str
    field: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ValidationErrorResponse(BaseModel):
    """Réponse pour les erreurs de validation"""
    detail: str
    errors: List[dict]  # Liste des erreurs de validation
    
    class Config:
        from_attributes = True

# ==================== SCHÉMAS DE FILTRES ====================
class UtilisateurFilter(BaseModel):
    """Filtres pour la recherche d'utilisateurs"""
    matricule: Optional[str] = None
    nom: Optional[str] = None
    prenom: Optional[str] = None
    role: Optional[UserRole] = None
    statut: Optional[UserStatus] = None
    recherche: Optional[str] = Field(
        None,
        description="Recherche dans nom, postnom, prenom, matricule"
    )
    date_debut: Optional[datetime] = None
    date_fin: Optional[datetime] = None
    
    class Config:
        use_enum_values = True