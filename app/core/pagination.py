# app/core/pagination.py
from typing import TypeVar, Generic, List, Optional, Type, Any, Callable, Union
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')

# ==================== SCHÉMAS DE PAGINATION ====================

class PaginationParams(BaseModel):
    """Paramètres de pagination reçus du client Flutter"""
    page: int = Field(default=1, ge=1, description="Numéro de la page")
    per_page: int = Field(default=20, ge=1, le=100, description="Éléments par page")
    sort_by: Optional[str] = Field(default=None, description="Champ de tri")
    sort_order: str = Field(default="asc", description="Ordre de tri ('asc' ou 'desc')")
    search: Optional[str] = Field(default=None, description="Chaîne de recherche textuelle")
    
    # Filtres avancés
    filters: Optional[dict] = Field(default=None, description="Filtres exacts")
    date_from: Optional[str] = Field(default=None, description="Date de début (ISO)")
    date_to: Optional[str] = Field(default=None, description="Date de fin (ISO)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "per_page": 20,
                "sort_by": "created_at",
                "sort_order": "desc",
                "search": "Jean",
                "filters": {"statut": "actif"},
                "date_from": "2024-01-01T00:00:00",
                "date_to": "2024-12-31T23:59:59"
            }
        }

class PaginatedResponse(BaseModel, Generic[T]):
    """Structure de réponse unifiée pour l'application Flutter"""
    items: List[T]
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    has_previous: bool
    
    # Métadonnées additionnelles
    total_items: Optional[int] = Field(default=None, description="Alias pour total")
    current_page: Optional[int] = Field(default=None, description="Alias pour page")
    items_per_page: Optional[int] = Field(default=None, description="Alias pour per_page")
    
    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "total": 100,
                "page": 1,
                "per_page": 20,
                "pages": 5,
                "has_next": True,
                "has_previous": False
            }
        }
    
    def __init__(self, **data):
        super().__init__(**data)
        # Ajouter des alias pour compatibilité Flutter
        self.total_items = self.total
        self.current_page = self.page
        self.items_per_page = self.per_page

class CursorPaginationParams(BaseModel):
    """Paramètres pour la pagination basée sur un curseur (plus performante)"""
    cursor: Optional[int] = Field(default=None, description="ID du dernier élément")
    limit: int = Field(default=20, ge=1, le=100, description="Nombre d'éléments")
    sort_by: str = Field(default="id", description="Champ de tri")
    sort_order: str = Field(default="asc", description="Ordre de tri")
    
class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Réponse pour la pagination basée sur un curseur"""
    items: List[T]
    next_cursor: Optional[int]
    has_more: bool
    limit: int

# ==================== SERVICE DE PAGINATION ====================

class Paginator:
    """Service utilitaire de pagination et de filtrage dynamique avancé"""
    
    @staticmethod
    async def paginate(
        db: AsyncSession,
        model: Type,
        params: PaginationParams,
        filters: Optional[dict] = None,
        search_columns: Optional[List[str]] = None,
        custom_filters: Optional[List[ColumnElement]] = None,
        joins: Optional[List[Any]] = None,
        select_columns: Optional[List[Any]] = None,
        group_by: Optional[List[Any]] = None,
        having: Optional[ColumnElement] = None,
        use_distinct: bool = False,
    ) -> PaginatedResponse:
        """
        Pagine une requête SQLAlchemy avec des options avancées.
        
        Args:
            db: Session de base de données
            model: Modèle SQLAlchemy
            params: Paramètres de pagination
            filters: Filtres exacts (dict)
            search_columns: Colonnes pour la recherche textuelle
            custom_filters: Filtres personnalisés SQLAlchemy
            joins: Relations à joindre
            select_columns: Colonnes à sélectionner (pour les requêtes complexes)
            group_by: Colonnes pour GROUP BY
            having: Clause HAVING
            use_distinct: Utiliser DISTINCT
            
        Returns:
            PaginatedResponse: Résultats paginés
        """
        try:
            # Construire la requête de base
            if select_columns:
                query = select(*select_columns)
            else:
                query = select(model)
            
            # Ajouter les DISTINCT si nécessaire
            if use_distinct:
                query = query.distinct()
            
            # Joindre les relations
            if joins:
                for join in joins:
                    query = query.join(join)
            
            # 1. Soft Delete automatique
            if hasattr(model, "is_deleted"):
                query = query.where(model.is_deleted == False)
            
            # 2. Filtres exacts
            if filters:
                for key, value in filters.items():
                    if value is not None and hasattr(model, key):
                        if isinstance(value, list):
                            query = query.where(getattr(model, key).in_(value))
                        else:
                            query = query.where(getattr(model, key) == value)
            
            # 3. Filtres personnalisés
            if custom_filters:
                for filter_expr in custom_filters:
                    query = query.where(filter_expr)
            
            # 4. Filtres de date
            if params.date_from:
                if hasattr(model, "created_at"):
                    query = query.where(model.created_at >= params.date_from)
            if params.date_to:
                if hasattr(model, "created_at"):
                    query = query.where(model.created_at <= params.date_to)
            
            # 5. Recherche textuelle multi-colonnes
            if params.search and search_columns:
                search_filters = []
                for col_name in search_columns:
                    if hasattr(model, col_name):
                        search_filters.append(
                            getattr(model, col_name).ilike(f"%{params.search}%")
                        )
                if search_filters:
                    query = query.where(or_(*search_filters))
            
            # 6. Group By et Having
            if group_by:
                query = query.group_by(*group_by)
            if having:
                query = query.having(having)
            
            # 7. Tri dynamique
            if params.sort_by and hasattr(model, params.sort_by):
                sort_column = getattr(model, params.sort_by)
                if params.sort_order.lower() == "desc":
                    sort_column = sort_column.desc()
                query = query.order_by(sort_column)
            elif hasattr(model, "created_at"):
                query = query.order_by(model.created_at.desc())
            elif hasattr(model, "id"):
                query = query.order_by(model.id.desc())
            
            # 8. Compter le total (optimisé)
            count_query = select(func.count()).select_from(query.subquery())
            total = await db.scalar(count_query) or 0
            
            # 9. Pagination
            offset = (params.page - 1) * params.per_page
            query = query.offset(offset).limit(params.per_page)
            
            # 10. Exécution
            result = await db.execute(query)
            
            if select_columns:
                # Si des colonnes spécifiques sont sélectionnées
                items = result.fetchall()
            else:
                items = result.scalars().all()
            
            # 11. Calcul des métadonnées
            pages = (total + params.per_page - 1) // params.per_page if total > 0 else 0
            
            return PaginatedResponse(
                items=items,
                total=total,
                page=params.page,
                per_page=params.per_page,
                pages=pages,
                has_next=params.page < pages,
                has_previous=params.page > 1
            )
            
        except Exception as e:
            logger.error(f"❌ Erreur de pagination: {e}", exc_info=True)
            raise

    @staticmethod
    async def paginate_cursor(
        db: AsyncSession,
        model: Type,
        params: CursorPaginationParams,
        filters: Optional[dict] = None,
        search_columns: Optional[List[str]] = None,
        search_term: Optional[str] = None,
    ) -> CursorPaginatedResponse:
        """
        Pagination basée sur un curseur (plus performante pour les grands datasets).
        
        Args:
            db: Session de base de données
            model: Modèle SQLAlchemy
            params: Paramètres de pagination
            filters: Filtres exacts
            search_columns: Colonnes pour la recherche
            search_term: Terme de recherche
        """
        query = select(model)
        
        # Soft Delete
        if hasattr(model, "is_deleted"):
            query = query.where(model.is_deleted == False)
        
        # Filtres
        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(model, key):
                    query = query.where(getattr(model, key) == value)
        
        # Recherche
        if search_term and search_columns:
            search_filters = []
            for col_name in search_columns:
                if hasattr(model, col_name):
                    search_filters.append(
                        getattr(model, col_name).ilike(f"%{search_term}%")
                    )
            if search_filters:
                query = query.where(or_(*search_filters))
        
        # Pagination par curseur
        sort_column = getattr(model, params.sort_by)
        if params.cursor:
            if params.sort_order.lower() == "desc":
                query = query.where(sort_column < params.cursor)
            else:
                query = query.where(sort_column > params.cursor)
        
        # Tri
        if params.sort_order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        # Limite (+1 pour vérifier s'il y a plus)
        query = query.limit(params.limit + 1)
        
        result = await db.execute(query)
        items = result.scalars().all()
        
        # Vérifier s'il y a plus d'éléments
        has_more = len(items) > params.limit
        if has_more:
            items = items[:-1]  # Retirer le dernier élément
        
        # Récupérer le curseur suivant
        next_cursor = None
        if items and has_more:
            last_item = items[-1]
            next_cursor = getattr(last_item, params.sort_by, None)
        
        return CursorPaginatedResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=params.limit
        )

# ==================== DÉCORATEUR DE PAGINATION ====================

def paginated(
    model: Type,
    search_columns: Optional[List[str]] = None,
    default_sort: str = "created_at",
    default_order: str = "desc",
    use_soft_delete: bool = True,
):
    """
    Décorateur pour paginer automatiquement les endpoints.
    
    Args:
        model: Modèle SQLAlchemy
        search_columns: Colonnes pour la recherche
        default_sort: Champ de tri par défaut
        default_order: Ordre de tri par défaut
        use_soft_delete: Utiliser le soft delete
    
    Exemple:
        @router.get("/users")
        @paginated(Utilisateur, search_columns=["nom", "prenom", "email"])
        async def list_users(...):
            return await get_users(...)
    """
    def decorator(func: Callable):
        async def wrapper(
            *args,
            db: AsyncSession = None,
            page: int = 1,
            per_page: int = 20,
            sort_by: Optional[str] = None,
            sort_order: str = "asc",
            search: Optional[str] = None,
            **kwargs
        ):
            # Construire les paramètres de pagination
            params = PaginationParams(
                page=page,
                per_page=per_page,
                sort_by=sort_by or default_sort,
                sort_order=sort_order or default_order,
                search=search,
                **kwargs
            )
            
            # Exécuter la fonction
            result = await func(*args, **kwargs)
            
            # Si la fonction retourne déjà des données paginées
            if isinstance(result, PaginatedResponse):
                return result
            
            # Sinon, paginer le résultat
            if isinstance(result, list):
                items = result
                total = len(items)
                start = (params.page - 1) * params.per_page
                end = start + params.per_page
                paginated_items = items[start:end]
                
                pages = (total + params.per_page - 1) // params.per_page if total > 0 else 0
                
                return PaginatedResponse(
                    items=paginated_items,
                    total=total,
                    page=params.page,
                    per_page=params.per_page,
                    pages=pages,
                    has_next=params.page < pages,
                    has_previous=params.page > 1
                )
            
            # Si la fonction retourne autre chose, la retourner telle quelle
            return result
            
        return wrapper
    return decorator

# ==================== UTILITAIRES DE FILTRAGE ====================

class FilterBuilder:
    """Builder pour construire des filtres SQLAlchemy complexes"""
    
    def __init__(self, model: Type):
        self.model = model
        self.filters = []
    
    def eq(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre d'égalité"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) == value)
        return self
    
    def ne(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre d'inégalité"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) != value)
        return self
    
    def like(self, field: str, value: str) -> 'FilterBuilder':
        """Filtre LIKE"""
        if value and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field).ilike(f"%{value}%"))
        return self
    
    def in_(self, field: str, values: List[Any]) -> 'FilterBuilder':
        """Filtre IN"""
        if values and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field).in_(values))
        return self
    
    def between(self, field: str, start: Any, end: Any) -> 'FilterBuilder':
        """Filtre BETWEEN"""
        if start is not None and end is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field).between(start, end))
        return self
    
    def gt(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre supérieur à"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) > value)
        return self
    
    def gte(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre supérieur ou égal à"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) >= value)
        return self
    
    def lt(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre inférieur à"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) < value)
        return self
    
    def lte(self, field: str, value: Any) -> 'FilterBuilder':
        """Filtre inférieur ou égal à"""
        if value is not None and hasattr(self.model, field):
            self.filters.append(getattr(self.model, field) <= value)
        return self
    
    def is_null(self, field: str) -> 'FilterBuilder':
        """Filtre IS NULL"""
        if hasattr(self.model, field):
            self.filters.append(getattr(self.model, field).is_(None))
        return self
    
    def is_not_null(self, field: str) -> 'FilterBuilder':
        """Filtre IS NOT NULL"""
        if hasattr(self.model, field):
            self.filters.append(getattr(self.model, field).isnot(None))
        return self
    
    def build(self) -> List[ColumnElement]:
        """Retourne la liste des filtres"""
        return self.filters
    
    def get_query(self, query) -> Any:
        """Applique les filtres à une requête"""
        for filter_expr in self.filters:
            query = query.where(filter_expr)
        return query