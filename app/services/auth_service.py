# app/services/auth_service.py
import datetime
import logging
from typing import Optional, Tuple, Dict, Any
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.database import get_db
from app.models.utilisateurs import Utilisateur
from app.schemas.user import UserRole, UserStatus

# Configuration du contexte de hachage (Bcrypt)
pwd_context = CryptContext(
    schemes=["bcrypt"], 
    deprecated="auto",
    bcrypt__rounds=12  # Nombre de rounds pour le hachage
)

# Configuration OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

logger = logging.getLogger(__name__)

class AuthService:
    """Service d'authentification avec gestion JWT, mots de passe et sécurité"""
    
    # ==================== GESTION DES MOTS DE PASSE ====================
    @staticmethod
    def hash_password(password: str) -> str:
        """Hache un mot de passe en utilisant Bcrypt"""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Vérifie si un mot de passe en clair correspond au hash stocké"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def verify_password_strength(password: str) -> Tuple[bool, Optional[str]]:
        """Vérifie la complexité du mot de passe"""
        if len(password) < settings.PASSWORD_MIN_LENGTH:
            return False, f"Le mot de passe doit contenir au moins {settings.PASSWORD_MIN_LENGTH} caractères"
        
        if settings.PASSWORD_REQUIRE_DIGIT and not any(c.isdigit() for c in password):
            return False, "Le mot de passe doit contenir au moins un chiffre"
        
        if settings.PASSWORD_REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
            return False, "Le mot de passe doit contenir au moins une majuscule"
        
        if settings.PASSWORD_REQUIRE_SPECIAL and not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            return False, "Le mot de passe doit contenir au moins un caractère spécial"
        
        return True, None

    # ==================== GESTION DES TOKENS JWT ====================
    @staticmethod
    def create_token(
        data: Dict[str, Any], 
        expires_delta: datetime.timedelta, 
        token_type: str = "access"
    ) -> str:
        """Génère un token JWT sécurisé"""
        to_encode = data.copy()
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "type": token_type,
            "iss": settings.TOKEN_ISSUER,
            "aud": settings.TOKEN_AUDIENCE,
        })
        
        return jwt.encode(
            to_encode, 
            settings.SECRET_KEY.get_secret_value(), 
            algorithm=settings.ALGORITHM
        )

    @classmethod
    def generate_auth_tokens(cls, utilisateur: Utilisateur) -> Dict[str, Any]:
        """Génère le couple complet (Access Token, Refresh Token)"""
        # Access Token
        access_payload = {
            "sub": str(utilisateur.id),
            "matricule": utilisateur.matricule,
            "nom": utilisateur.nom,
            "prenom": utilisateur.prenom,
            "role": utilisateur.role,
            "statut": utilisateur.statut,
        }
        access_expires = datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = cls.create_token(access_payload, access_expires, token_type="access")

        # Refresh Token
        refresh_payload = {
            "sub": str(utilisateur.id),
            "matricule": utilisateur.matricule,
        }
        refresh_expires = datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        refresh_token = cls.create_token(refresh_payload, refresh_expires, token_type="refresh")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # en secondes
        }

    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """Décode et vérifie un token JWT"""
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY.get_secret_value(),
                algorithms=[settings.ALGORITHM],
                audience=settings.TOKEN_AUDIENCE,
                issuer=settings.TOKEN_ISSUER,
            )
            return payload
        except JWTError as e:
            logger.error(f"Erreur de décodage JWT: {e}")
            raise

    @staticmethod
    def verify_token(token: str, token_type: str = "access") -> Dict[str, Any]:
        """Vérifie la validité d'un token JWT"""
        try:
            payload = AuthService.decode_token(token)
            
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token type invalide. Attendu: {token_type}",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            exp = payload.get("exp")
            if exp and datetime.datetime.fromtimestamp(exp, datetime.timezone.utc) < datetime.datetime.now(datetime.timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expiré",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return payload
            
        except JWTError as e:
            logger.error(f"Erreur de vérification JWT: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @staticmethod
    def refresh_access_token(refresh_token: str) -> Dict[str, str]:
        """Génère un nouvel access token à partir d'un refresh token"""
        try:
            payload = AuthService.verify_token(refresh_token, token_type="refresh")
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token invalide: ID utilisateur manquant",
                )
            
            # Générer un nouvel access token
            access_expires = datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            access_payload = {
                "sub": user_id,
                "type": "access",
                "refresh": True,
            }
            new_access_token = AuthService.create_token(access_payload, access_expires, token_type="access")
            
            return {
                "access_token": new_access_token,
                "token_type": "bearer",
                "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            }
            
        except Exception as e:
            logger.error(f"Erreur de refresh token: {e}")
            raise

    # ==================== SÉCURITÉ ANTI-FORCE BRUTE ====================
    @staticmethod
    async def handle_failed_login(db: AsyncSession, utilisateur: Utilisateur) -> None:
        """Incrémente les tentatives infructueuses et verrouille le compte si nécessaire"""
        utilisateur.tentative_connexion += 1
        
        if utilisateur.tentative_connexion >= settings.MAX_LOGIN_ATTEMPTS:
            lock_duration = datetime.timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            utilisateur.verrouille_jusqua = datetime.datetime.now(datetime.timezone.utc) + lock_duration
            utilisateur.statut = UserStatus.SUSPENDU.value
            utilisateur.tentative_connexion = 0
            logger.warning(f"🔒 Compte verrouillé: {utilisateur.matricule} jusqu'à {utilisateur.verrouille_jusqua}")
        
        db.add(utilisateur)
        await db.commit()

    @staticmethod
    async def reset_login_attempts(db: AsyncSession, utilisateur: Utilisateur) -> None:
        """Réinitialise le compteur d'échecs après une connexion réussie"""
        if utilisateur.tentative_connexion > 0 or utilisateur.verrouille_jusqua is not None:
            utilisateur.tentative_connexion = 0
            utilisateur.verrouille_jusqua = None
            if utilisateur.statut == UserStatus.SUSPENDU.value:
                utilisateur.statut = UserStatus.ACTIF.value
            db.add(utilisateur)
            await db.commit()
            logger.info(f"✅ Tentatives de connexion réinitialisées pour: {utilisateur.matricule}")

    @staticmethod
    def is_account_locked(utilisateur: Utilisateur) -> Tuple[bool, Optional[datetime.datetime]]:
        """Vérifie si le compte est verrouillé"""
        if utilisateur.verrouille_jusqua:
            if datetime.datetime.now(datetime.timezone.utc) < utilisateur.verrouille_jusqua:
                return True, utilisateur.verrouille_jusqua
            else:
                utilisateur.verrouille_jusqua = None
                if utilisateur.statut == UserStatus.SUSPENDU.value:
                    utilisateur.statut = UserStatus.ACTIF.value
        return False, None

    # ==================== AUTHENTIFICATION UTILISATEUR ====================
    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        matricule: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[bool, Optional[Utilisateur], Optional[str]]:
        """Authentifie un utilisateur avec son matricule et mot de passe"""
        try:
            result = await db.execute(
                select(Utilisateur).where(Utilisateur.matricule == matricule.upper())
            )
            utilisateur = result.scalar_one_or_none()
            
            if not utilisateur:
                logger.warning(f"❌ Tentative de connexion avec matricule inconnu: {matricule}")
                return False, None, "Matricule ou mot de passe incorrect"
            
            if utilisateur.statut == UserStatus.INACTIF.value:
                logger.warning(f"❌ Tentative de connexion sur compte inactif: {matricule}")
                return False, None, "Ce compte est désactivé"
            
            is_locked, unlock_time = AuthService.is_account_locked(utilisateur)
            if is_locked:
                logger.warning(f"🔒 Tentative de connexion sur compte verrouillé: {matricule}")
                return False, None, f"Compte verrouillé jusqu'à {unlock_time.strftime('%H:%M:%S')}"
            
            if not AuthService.verify_password(password, utilisateur.mot_de_passe):
                await AuthService.handle_failed_login(db, utilisateur)
                logger.warning(f"❌ Échec de connexion pour: {matricule} (tentative {utilisateur.tentative_connexion})")
                return False, None, "Matricule ou mot de passe incorrect"
            
            await AuthService.reset_login_attempts(db, utilisateur)
            
            utilisateur.derniere_connexion = datetime.datetime.now(datetime.timezone.utc)
            if ip_address:
                utilisateur.derniere_ip = ip_address
            if user_agent:
                utilisateur.user_agent = user_agent
            db.add(utilisateur)
            await db.commit()
            
            logger.info(f"✅ Connexion réussie pour: {matricule}")
            return True, utilisateur, None
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'authentification: {e}")
            await db.rollback()
            return False, None, "Erreur lors de l'authentification"

    # ==================== DÉPENDANCES POUR FASTAPI (CORRIGÉES) ====================
    @staticmethod
    async def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db)  # ✅ CORRIGÉ : Depends() obligatoire
    ) -> Utilisateur:
        """
        Dépendance FastAPI pour obtenir l'utilisateur actuellement authentifié
        
        Args:
            token: Token JWT (injecté automatiquement)
            db: Session de base de données (injectée automatiquement)
            
        Returns:
            Utilisateur: Utilisateur authentifié
            
        Raises:
            HTTPException: Si l'authentification échoue
        """
        try:
            payload = AuthService.verify_token(token, token_type="access")
            
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token invalide: ID utilisateur manquant",
                )
            
            result = await db.execute(
                select(Utilisateur).where(Utilisateur.id == int(user_id))
            )
            utilisateur = result.scalar_one_or_none()
            
            if not utilisateur:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Utilisateur non trouvé",
                )
            
            if utilisateur.statut != UserStatus.ACTIF.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Compte {utilisateur.statut}",
                )
            
            return utilisateur
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération de l'utilisateur: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Impossible d'authentifier l'utilisateur",
            )
    
    @staticmethod
    async def get_current_active_user(
        current_user: Utilisateur = Depends(get_current_user)  # ✅ Dépendance chaînée
    ) -> Utilisateur:
        """
        Dépendance FastAPI pour obtenir l'utilisateur actif actuellement authentifié
        """
        if current_user.statut != UserStatus.ACTIF.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur inactif",
            )
        return current_user
    
    @staticmethod
    async def get_current_superuser(
        current_user: Utilisateur = Depends(get_current_active_user)  # ✅ Dépendance chaînée
    ) -> Utilisateur:
        """
        Dépendance FastAPI pour obtenir un superutilisateur (admin/gerant)
        """
        if current_user.role not in [UserRole.ADMIN.value, UserRole.GERANT.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes. Admin ou Gérant requis.",
            )
        return current_user
    
    @staticmethod
    async def get_current_admin(
        current_user: Utilisateur = Depends(get_current_active_user)
    ) -> Utilisateur:
        """
        Dépendance FastAPI pour obtenir un administrateur uniquement
        """
        if current_user.role != UserRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes. Admin requis.",
            )
        return current_user

    # ==================== MÉTHODE UTILITAIRE ====================
    @staticmethod
    def get_password_hash(password: str) -> str:
        """Alias pour hash_password (compatibilité)"""
        return AuthService.hash_password(password)