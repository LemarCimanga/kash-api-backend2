# app/api/v1/auth.py
import datetime
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_client_ip, get_request_id
from app.services.auth_service import AuthService
from app.models.utilisateurs import Utilisateur
from app.models.master_code import MasterCode
from app.schemas.user import (
    UtilisateurCreate, 
    UtilisateurResponse, 
    UtilisateurDetailResponse,
    UserStatus,
    UserRole,
    ChangePasswordRequest,
    ResetPasswordRequest,
    ResetPasswordConfirmRequest
)
from app.schemas.token import TokenResponse, TokenRefreshRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ==================== INSCRIPTION ====================
@router.post("/register", response_model=UtilisateurResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UtilisateurCreate, 
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Inscription d'un nouvel utilisateur.
    
    - Vérifie la complexité du mot de passe
    - Valide le Master Code si fourni
    - Crée l'utilisateur avec le rôle approprié
    """
    client_ip = get_client_ip(request)
    request_id = get_request_id(request)
    
    logger.info(f"📝 Tentative d'inscription depuis {client_ip} (ID: {request_id})")
    
    # 1. Vérifier si le matricule existe déjà
    result = await db.execute(
        select(Utilisateur).where(Utilisateur.matricule == user_in.matricule.upper())
    )
    if result.scalar_one_or_none():
        logger.warning(f"⚠️ Tentative d'inscription avec matricule existant: {user_in.matricule}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un utilisateur avec ce matricule existe déjà.",
        )
    
    # 2. Vérifier si le téléphone existe déjà
    if user_in.numero_telephone:
        result = await db.execute(
            select(Utilisateur).where(Utilisateur.numero_telephone == user_in.numero_telephone)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce numéro de téléphone est déjà utilisé.",
            )
    
    # 3. Vérifier si l'email existe déjà
    if user_in.email:
        result = await db.execute(
            select(Utilisateur).where(Utilisateur.email == user_in.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet email est déjà utilisé.",
            )

    # 4. Validation de la force du mot de passe
    is_strong, password_error = AuthService.verify_password_strength(user_in.password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error,
        )

    # 5. Gestion et validation du Master Code
    db_master_code = None
    if user_in.master_code:
        # Rechercher le code
        code_result = await db.execute(
            select(MasterCode).where(MasterCode.code_hash == MasterCode.hash_code(user_in.master_code))
        )
        db_master_code = code_result.scalar_one_or_none()
        
        if not db_master_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Master Code invalide.",
            )
        
        # Vérifier si le code est disponible
        if not db_master_code.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Master Code expiré ou déjà utilisé.",
            )
        
        # Vérifier si le rôle est autorisé pour ce code
        if db_master_code.used_by_roles:
            authorized_roles = [r.strip() for r in db_master_code.used_by_roles.split(',')]
            if user_in.role.value not in authorized_roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ce code n'est pas autorisé pour le rôle {user_in.role.value}.",
                )
        
        logger.info(f"✅ Master Code valide: {user_in.master_code}")

    # 6. Création de l'utilisateur
    hashed_password = AuthService.hash_password(user_in.password)
    
    nouvel_utilisateur = Utilisateur(
        matricule=user_in.matricule.upper(),
        nom=user_in.nom,
        postnom=user_in.postnom,
        prenom=user_in.prenom,
        numero_telephone=user_in.numero_telephone,
        email=user_in.email,
        mot_de_passe=hashed_password,
        role=user_in.role.value,
        statut=UserStatus.ACTIF.value,
        photo=user_in.photo or "",
        tentative_connexion=0,
        created_by=user_in.created_by,
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    
    db.add(nouvel_utilisateur)
    await db.flush()  # Récupère l'ID généré

    # 7. Marquer le Master Code comme consommé
    if db_master_code:
        db_master_code.is_active = False
        db_master_code.used_count += 1
        db_master_code.last_used_at = datetime.datetime.now(datetime.timezone.utc)
        
        # Enregistrer l'utilisation
        from app.models.master_code import MasterCodeUsage
        usage = MasterCodeUsage(
            master_code_id=db_master_code.id,
            utilisateur_id=nouvel_utilisateur.id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent")
        )
        db.add(usage)
        
        logger.info(f"✅ Master Code {user_in.master_code} consommé par {nouvel_utilisateur.matricule}")

    await db.commit()
    await db.refresh(nouvel_utilisateur)
    
    logger.info(f"✅ Utilisateur créé avec succès: {nouvel_utilisateur.matricule} (ID: {nouvel_utilisateur.id})")
    return nouvel_utilisateur

# ==================== CONNEXION ====================
@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Connexion standard OAuth2.
    
    - Utilise le matricule comme username
    - Renvoie un Access Token et un Refresh Token
    - Protégé par la logique anti-brute force
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    request_id = get_request_id(request)
    
    logger.info(f"🔐 Tentative de connexion depuis {client_ip} (ID: {request_id})")

    success, utilisateur, error_message = await AuthService.authenticate_user(
        db=db,
        matricule=form_data.username,  # Le champ username reçoit le matricule
        password=form_data.password,
        ip_address=client_ip,
        user_agent=user_agent
    )

    if not success or not utilisateur:
        logger.warning(f"❌ Échec de connexion depuis {client_ip}: {error_message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Génération du couple de tokens
    tokens = AuthService.generate_auth_tokens(utilisateur)
    
    logger.info(f"✅ Connexion réussie: {utilisateur.matricule} (ID: {utilisateur.id})")
    
    return {
        **tokens,
        "user": {
            "id": utilisateur.id,
            "matricule": utilisateur.matricule,
            "nom": utilisateur.nom,
            "prenom": utilisateur.prenom,
            "role": utilisateur.role,
            "statut": utilisateur.statut,
            "photo": utilisateur.photo
        }
    }

# ==================== RAFRAÎCHISSEMENT DU TOKEN ====================
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    payload: TokenRefreshRequest,
    request: Request
) -> Any:
    """
    Renouvelle l'Access Token à partir d'un Refresh Token valide.
    """
    client_ip = get_client_ip(request)
    request_id = get_request_id(request)
    
    logger.info(f"🔄 Rafraîchissement de token depuis {client_ip} (ID: {request_id})")
    
    try:
        tokens = AuthService.refresh_access_token(payload.refresh_token)
        logger.info(f"✅ Token rafraîchi avec succès")
        return tokens
    except HTTPException as e:
        logger.warning(f"❌ Échec du rafraîchissement: {e.detail}")
        raise

# ==================== PROFIL UTILISATEUR ====================
@router.get("/me", response_model=UtilisateurDetailResponse)
async def get_current_user_profile(
    current_user: Utilisateur = Depends(AuthService.get_current_active_user)
) -> Any:
    """
    Récupère les informations du profil de l'utilisateur connecté.
    """
    return current_user

@router.put("/me", response_model=UtilisateurResponse)
async def update_current_user_profile(
    user_update: UtilisateurUpdate,
    current_user: Utilisateur = Depends(AuthService.get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Met à jour le profil de l'utilisateur connecté.
    """
    # Mettre à jour les champs
    update_data = user_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        if field == "password":
            continue  # Ne pas mettre à jour le mot de passe ici
        setattr(current_user, field, value)
    
    current_user.updated_at = datetime.datetime.now(datetime.timezone.utc)
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    
    logger.info(f"✅ Profil mis à jour pour {current_user.matricule}")
    return current_user

# ==================== CHANGEMENT DE MOT DE PASSE ====================
@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: Utilisateur = Depends(AuthService.get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Change le mot de passe de l'utilisateur connecté.
    """
    # Vérifier l'ancien mot de passe
    if not AuthService.verify_password(password_data.old_password, current_user.mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect."
        )
    
    # Vérifier la force du nouveau mot de passe
    is_strong, error = AuthService.verify_password_strength(password_data.new_password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    # Hasher et sauvegarder le nouveau mot de passe
    current_user.mot_de_passe = AuthService.hash_password(password_data.new_password)
    current_user.password_changed_at = datetime.datetime.now(datetime.timezone.utc)
    
    db.add(current_user)
    await db.commit()
    
    logger.info(f"✅ Mot de passe changé pour {current_user.matricule}")
    
    return {
        "message": "Mot de passe changé avec succès.",
        "status": "success"
    }

# ==================== DÉCONNEXION ====================
@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    current_user: Utilisateur = Depends(AuthService.get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Déconnecte l'utilisateur (invalide le token côté client).
    """
    # Note: Avec JWT, la déconnexion est généralement gérée côté client.
    # On peut ajouter un blacklist si nécessaire.
    logger.info(f"👋 Déconnexion de {current_user.matricule}")
    
    return {
        "message": "Déconnexion réussie.",
        "status": "success"
    }

# ==================== RÉINITIALISATION DU MOT DE PASSE ====================
@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password_request(
    reset_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Demande de réinitialisation du mot de passe.
    Envoie un token de réinitialisation par email ou SMS.
    """
    # Rechercher l'utilisateur par email ou téléphone
    user = None
    
    if reset_data.email_or_phone:
        # Chercher par email
        result = await db.execute(
            select(Utilisateur).where(Utilisateur.email == reset_data.email_or_phone)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Chercher par téléphone
            result = await db.execute(
                select(Utilisateur).where(Utilisateur.numero_telephone == reset_data.email_or_phone)
            )
            user = result.scalar_one_or_none()
    
    if not user:
        # Pour des raisons de sécurité, ne pas révéler si l'utilisateur existe
        logger.warning(f"⚠️ Demande de réinitialisation pour un compte inexistant: {reset_data.email_or_phone}")
        return {
            "message": "Si un compte existe avec ces informations, vous recevrez un lien de réinitialisation.",
            "status": "sent"
        }
    
    # Générer un token de réinitialisation
    import secrets
    reset_token = secrets.token_urlsafe(32)
    reset_expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
    
    user.password_reset_token = reset_token
    user.password_reset_expires = reset_expires
    
    db.add(user)
    await db.commit()
    
    logger.info(f"📧 Token de réinitialisation généré pour {user.matricule}")
    
    # Ici, envoyer l'email ou SMS avec le token
    # await send_reset_email(user.email, reset_token)
    
    return {
        "message": "Si un compte existe avec ces informations, vous recevrez un lien de réinitialisation.",
        "status": "sent"
    }

@router.post("/reset-password/confirm", status_code=status.HTTP_200_OK)
async def reset_password_confirm(
    reset_data: ResetPasswordConfirmRequest,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Confirme la réinitialisation du mot de passe avec un token valide.
    """
    # Rechercher l'utilisateur avec le token
    result = await db.execute(
        select(Utilisateur).where(Utilisateur.password_reset_token == reset_data.token)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de réinitialisation invalide."
        )
    
    # Vérifier si le token a expiré
    if user.password_reset_expires and user.password_reset_expires < datetime.datetime.now(datetime.timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le token de réinitialisation a expiré."
        )
    
    # Vérifier la force du nouveau mot de passe
    is_strong, error = AuthService.verify_password_strength(reset_data.new_password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    # Mettre à jour le mot de passe
    user.mot_de_passe = AuthService.hash_password(reset_data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    user.password_changed_at = datetime.datetime.now(datetime.timezone.utc)
    
    db.add(user)
    await db.commit()
    
    logger.info(f"✅ Mot de passe réinitialisé pour {user.matricule}")
    
    return {
        "message": "Mot de passe réinitialisé avec succès.",
        "status": "success"
    }

# ==================== VÉRIFICATION DU TOKEN ====================
@router.get("/verify-token", status_code=status.HTTP_200_OK)
async def verify_token(
    current_user: Utilisateur = Depends(AuthService.get_current_active_user)
) -> Dict[str, Any]:
    """
    Vérifie si le token actuel est valide.
    """
    return {
        "valid": True,
        "user_id": current_user.id,
        "matricule": current_user.matricule,
        "role": current_user.role,
        "statut": current_user.statut,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }