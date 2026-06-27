# app/api/v1/__init__.py
from fastapi import APIRouter, Depends
from typing import List, Dict, Any

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.master_codes import router as master_codes_router
from app.api.v1.payments import router as payments_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.reports import router as reports_router
from app.api.v1.settings import router as settings_router

from app.core.config import settings
from app.services.auth_service import AuthService
from app.models.utilisateurs import Utilisateur

# ==================== CRÉATION DU ROUTEUR PRINCIPAL ====================
api_router = APIRouter(
    prefix="/api/v1",
    tags=["API v1"],
    responses={
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé"},
        404: {"description": "Ressource non trouvée"},
        429: {"description": "Trop de requêtes"},
        500: {"description": "Erreur interne du serveur"},
    }
)

# ==================== INCLUSION DES ROUTEURS ====================

# 1. Authentification (public)
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"]
)

# 2. Gestion des utilisateurs (protégé)
api_router.include_router(
    users_router,
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(AuthService.get_current_active_user)]
)

# 3. Gestion des codes master (admin/gerant uniquement)
api_router.include_router(
    master_codes_router,
    prefix="/master-codes",
    tags=["Master Codes"],
    dependencies=[Depends(AuthService.get_current_superuser)]
)

# 4. Gestion des paiements (protégé)
api_router.include_router(
    payments_router,
    prefix="/payments",
    tags=["Payments"],
    dependencies=[Depends(AuthService.get_current_active_user)]
)

# 5. Tableau de bord (protégé)
api_router.include_router(
    dashboard_router,
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(AuthService.get_current_active_user)]
)

# 6. Rapports et statistiques (admin/gerant)
api_router.include_router(
    reports_router,
    prefix="/reports",
    tags=["Reports"],
    dependencies=[Depends(AuthService.get_current_superuser)]
)

# 7. Paramètres et configuration (admin uniquement)
api_router.include_router(
    settings_router,
    prefix="/settings",
    tags=["Settings"],
    dependencies=[Depends(AuthService.get_current_admin)]
)

# ==================== ROUTES GLOBALES ====================
@api_router.get("/ping", tags=["System"], include_in_schema=settings.DEBUG)
async def ping() -> Dict[str, str]:
    """
    Endpoint de ping simple pour vérifier la disponibilité de l'API v1.
    """
    return {"status": "pong", "version": "v1"}

@api_router.get("/version", tags=["System"])
async def get_version() -> Dict[str, Any]:
    """
    Retourne les informations de version de l'API.
    """
    return {
        "api_version": "v1",
        "app_version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "routes_count": len(api_router.routes),
        "timestamp": datetime.utcnow().isoformat()
    }

@api_router.get("/routes", tags=["System"], dependencies=[Depends(AuthService.get_current_superuser)])
async def list_routes() -> List[Dict[str, Any]]:
    """
    Liste toutes les routes disponibles (admin uniquement).
    """
    routes = []
    for route in api_router.routes:
        routes.append({
            "path": route.path,
            "name": route.name,
            "methods": list(route.methods) if hasattr(route, "methods") else [],
            "summary": getattr(route, "summary", None),
            "description": getattr(route, "description", None),
        })
    return sorted(routes, key=lambda x: x["path"])

# ==================== INITIALISATION ====================
def setup_v1_routes(app):
    """
    Fonction utilitaire pour configurer les routes v1 dans l'application principale.
    
    Args:
        app: Instance FastAPI
    """
    app.include_router(api_router)
    
    # Logging des routes
    if settings.DEBUG:
        print(f"✅ Routes API v1 configurées: {len(api_router.routes)} routes")
        for route in api_router.routes:
            if hasattr(route, "methods"):
                print(f"   - {route.path} [{', '.join(route.methods)}]")
    
    return app

# ==================== EXPORTATION DES ROUTEURS ====================
__all__ = [
    "api_router",
    "setup_v1_routes",
    "auth_router",
    "users_router",
    "master_codes_router",
    "payments_router",
    "dashboard_router",
    "reports_router",
    "settings_router",
]