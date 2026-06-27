# app/models/base.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Type, List
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Boolean, String, func, Index
from sqlalchemy.orm import declarative_mixin, declared_attr, Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import Base
import logging

logger = logging.getLogger(__name__)

# ==================== MIXINS DE BASE ====================

@declarative_mixin
class TimestampMixin:
    """
    Mixin pour les timestamps automatiques.
    Ajoute les champs created_at et updated_at.
    """
    created_at = Column(
        DateTime, 
        server_default=func.now(), 
        nullable=False,
        index=True,
        comment="Date de création"
    )
    updated_at = Column(
        DateTime, 
        onupdate=func.now(), 
        nullable=True,
        comment="Date de dernière modification"
    )
    
    def update_timestamp(self):
        """Met à jour manuellement le timestamp de modification"""
        self.updated_at = datetime.now(timezone.utc)


@declarative_mixin
class AuditMixin:
    """
    Mixin pour l'audit (qui a créé/modifié).
    Ajoute les champs created_by et updated_by.
    """
    @declared_attr
    def created_by(cls):
        return Column(
            Integer, 
            ForeignKey("utilisateurs.id", ondelete="SET NULL"), 
            nullable=True,
            index=True,
            comment="Utilisateur qui a créé"
        )
    
    @declared_attr
    def updated_by(cls):
        return Column(
            Integer, 
            ForeignKey("utilisateurs.id", ondelete="SET NULL"), 
            nullable=True,
            comment="Utilisateur qui a modifié"
        )
    
    def set_audit(self, user_id: Optional[int]):
        """Définit l'utilisateur qui crée/modifie"""
        if not self.created_by:
            self.created_by = user_id
        self.updated_by = user_id


@declarative_mixin
class SoftDeleteMixin:
    """
    Mixin pour la suppression logique.
    Ajoute les champs is_deleted, deleted_at et deleted_by.
    """
    is_deleted = Column(
        Boolean, 
        default=False, 
        index=True, 
        nullable=False,
        comment="Indicateur de suppression logique"
    )
    deleted_at = Column(
        DateTime, 
        nullable=True,
        comment="Date de suppression"
    )
    deleted_by = Column(
        Integer, 
        ForeignKey("utilisateurs.id", ondelete="SET NULL"), 
        nullable=True,
        comment="Utilisateur qui a supprimé"
    )
    
    def soft_delete(self, user_id: int):
        """
        Exécute une suppression logique (soft delete) en traçant l'auteur.
        
        Args:
            user_id: ID de l'utilisateur qui effectue la suppression
        """
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_by = user_id
        logger.info(f"🗑️ Soft delete: {self.__class__.__name__} ID={self.id} par utilisateur {user_id}")
    
    def restore(self, user_id: Optional[int] = None):
        """
        Restaure un élément supprimé logiquement.
        
        Args:
            user_id: ID de l'utilisateur qui restaure (optionnel)
        """
        self.is_deleted = False
        self.deleted_at = None
        if user_id:
            self.deleted_by = user_id
        logger.info(f"♻️ Restauration: {self.__class__.__name__} ID={self.id}")


@declarative_mixin
class VersionedMixin:
    """
    Mixin pour le versionnement des données.
    Ajoute un champ de version pour le contrôle de concurrence optimiste.
    """
    version = Column(
        Integer, 
        default=1, 
        nullable=False,
        comment="Version pour contrôle de concurrence"
    )
    
    def increment_version(self):
        """Incrémente la version"""
        self.version += 1


@declarative_mixin
class ActiveMixin:
    """
    Mixin pour l'activation/désactivation.
    Ajoute un champ is_active.
    """
    is_active = Column(
        Boolean, 
        default=True, 
        index=True, 
        nullable=False,
        comment="Indicateur d'activité"
    )
    
    def activate(self):
        """Active l'élément"""
        self.is_active = True
    
    def deactivate(self):
        """Désactive l'élément"""
        self.is_active = False


@declarative_mixin
class SlugMixin:
    """
    Mixin pour les slugs.
    Ajoute un champ slug unique.
    """
    slug = Column(
        String(255), 
        unique=True, 
        index=True, 
        nullable=False,
        comment="Slug unique pour les URLs"
    )


@declarative_mixin
class OrderableMixin:
    """
    Mixin pour le classement personnalisé.
    Ajoute un champ order.
    """
    order = Column(
        Integer, 
        default=0, 
        index=True,
        comment="Ordre de classement"
    )


@declarative_mixin
class MetadataMixin:
    """
    Mixin pour les métadonnées extensibles.
    Ajoute un champ JSON pour les données flexibles.
    """
    metadata = Column(
        String(2000),  # Pour compatibilité SQLite/PostgreSQL
        nullable=True,
        comment="Métadonnées au format JSON"
    )


# ==================== MODÈLE DE BASE ====================

class BaseModel(
    Base, 
    TimestampMixin, 
    AuditMixin, 
    SoftDeleteMixin,
    VersionedMixin,
    ActiveMixin
):
    """
    Modèle de base avec tous les mixins pour l'ensemble des tables.
    Inclut : Timestamp, Audit, SoftDelete, Version, Active.
    """
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Index composites communs
    __table_args__ = (
        Index('ix_created_at_updated_at', 'created_at', 'updated_at'),
        Index('ix_is_deleted_created_at', 'is_deleted', 'created_at'),
        Index('ix_is_active_created_at', 'is_active', 'created_at'),
    )
    
    def to_dict(self, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Convertit le modèle en dictionnaire.
        
        Args:
            exclude: Liste des champs à exclure
            
        Returns:
            Dict[str, Any]: Dictionnaire des données
        """
        exclude = exclude or []
        
        # Exclure les champs sensibles par défaut
        default_exclude = ['mot_de_passe', 'password', 'secret', 'token']
        exclude.extend(default_exclude)
        
        data = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            
            # Convertir les datetime en ISO
            if isinstance(value, datetime):
                value = value.isoformat()
            
            data[column.name] = value
        
        return data
    
    @classmethod
    async def get_by_id(
        cls, 
        db: AsyncSession, 
        id: int, 
        include_deleted: bool = False
    ) -> Optional['BaseModel']:
        """
        Récupère un enregistrement par ID.
        
        Args:
            db: Session de base de données
            id: ID de l'enregistrement
            include_deleted: Inclure les éléments supprimés
            
        Returns:
            Optional[BaseModel]: L'enregistrement ou None
        """
        query = select(cls).where(cls.id == id)
        
        if not include_deleted and hasattr(cls, 'is_deleted'):
            query = query.where(cls.is_deleted == False)
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @classmethod
    async def get_all(
        cls, 
        db: AsyncSession, 
        include_deleted: bool = False,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by: Optional[str] = None,
        **filters
    ) -> List['BaseModel']:
        """
        Récupère tous les enregistrements avec filtres.
        
        Args:
            db: Session de base de données
            include_deleted: Inclure les éléments supprimés
            limit: Limite de résultats
            offset: Offset
            order_by: Champ de tri
            **filters: Filtres exacts
            
        Returns:
            List[BaseModel]: Liste des enregistrements
        """
        query = select(cls)
        
        # Soft delete
        if not include_deleted and hasattr(cls, 'is_deleted'):
            query = query.where(cls.is_deleted == False)
        
        # Filtres
        for key, value in filters.items():
            if hasattr(cls, key) and value is not None:
                query = query.where(getattr(cls, key) == value)
        
        # Tri
        if order_by:
            if hasattr(cls, order_by):
                query = query.order_by(getattr(cls, order_by))
            elif order_by.startswith('-'):
                field = order_by[1:]
                if hasattr(cls, field):
                    query = query.order_by(getattr(cls, field).desc())
        
        # Pagination
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @classmethod
    async def count_all(
        cls, 
        db: AsyncSession, 
        include_deleted: bool = False,
        **filters
    ) -> int:
        """
        Compte le nombre d'enregistrements.
        
        Args:
            db: Session de base de données
            include_deleted: Inclure les éléments supprimés
            **filters: Filtres exacts
            
        Returns:
            int: Nombre d'enregistrements
        """
        from sqlalchemy import func
        
        query = select(func.count())
        
        # Soft delete
        if not include_deleted and hasattr(cls, 'is_deleted'):
            query = query.where(cls.is_deleted == False)
        
        # Filtres
        for key, value in filters.items():
            if hasattr(cls, key) and value is not None:
                query = query.where(getattr(cls, key) == value)
        
        result = await db.execute(query)
        return result.scalar() or 0
    
    @classmethod
    async def exists(
        cls, 
        db: AsyncSession, 
        include_deleted: bool = False,
        **filters
    ) -> bool:
        """
        Vérifie si des enregistrements existent.
        
        Args:
            db: Session de base de données
            include_deleted: Inclure les éléments supprimés
            **filters: Filtres exacts
            
        Returns:
            bool: True si des enregistrements existent
        """
        from sqlalchemy import func
        
        query = select(func.count()).where(cls.id > 0)
        
        # Soft delete
        if not include_deleted and hasattr(cls, 'is_deleted'):
            query = query.where(cls.is_deleted == False)
        
        # Filtres
        for key, value in filters.items():
            if hasattr(cls, key) and value is not None:
                query = query.where(getattr(cls, key) == value)
        
        result = await db.execute(query)
        return (result.scalar() or 0) > 0
    
    async def save(self, db: AsyncSession, user_id: Optional[int] = None):
        """
        Sauvegarde l'enregistrement en base de données.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur (pour audit)
        """
        # Audit
        if user_id:
            self.set_audit(user_id)
        
        # Timestamp
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        
        db.add(self)
        await db.flush()
        return self
    
    async def delete(self, db: AsyncSession, user_id: int, soft: bool = True):
        """
        Supprime l'enregistrement.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            soft: Soft delete (True) ou hard delete (False)
        """
        if soft and hasattr(self, 'soft_delete'):
            self.soft_delete(user_id)
            db.add(self)
        else:
            await db.delete(self)
        
        await db.flush()


# ==================== FONCTIONS UTILITAIRES ====================

async def bulk_soft_delete(
    db: AsyncSession, 
    model: Type[BaseModel], 
    ids: List[int], 
    user_id: int
) -> int:
    """
    Supprime logiquement plusieurs enregistrements.
    
    Args:
        db: Session de base de données
        model: Modèle
        ids: Liste des IDs
        user_id: ID de l'utilisateur
        
    Returns:
        int: Nombre d'enregistrements supprimés
    """
    from sqlalchemy import update
    
    stmt = (
        update(model)
        .where(model.id.in_(ids))
        .where(model.is_deleted == False)
        .values(
            is_deleted=True,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=user_id
        )
    )
    
    result = await db.execute(stmt)
    await db.flush()
    
    logger.info(f"🗑️ Bulk soft delete: {len(ids)} enregistrements de {model.__name__}")
    return result.rowcount


async def bulk_restore(
    db: AsyncSession, 
    model: Type[BaseModel], 
    ids: List[int], 
    user_id: Optional[int] = None
) -> int:
    """
    Restaure plusieurs enregistrements supprimés logiquement.
    
    Args:
        db: Session de base de données
        model: Modèle
        ids: Liste des IDs
        user_id: ID de l'utilisateur (optionnel)
        
    Returns:
        int: Nombre d'enregistrements restaurés
    """
    from sqlalchemy import update
    
    values = {
        'is_deleted': False,
        'deleted_at': None
    }
    if user_id:
        values['deleted_by'] = user_id
    
    stmt = (
        update(model)
        .where(model.id.in_(ids))
        .where(model.is_deleted == True)
        .values(**values)
    )
    
    result = await db.execute(stmt)
    await db.flush()
    
    logger.info(f"♻️ Bulk restore: {len(ids)} enregistrements de {model.__name__}")
    return result.rowcount