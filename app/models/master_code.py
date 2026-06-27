from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, func, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.core.database import Base
from datetime import datetime, timedelta
import hashlib
import secrets

class MasterCode(Base):
    __tablename__ = "master_codes"
    __table_args__ = (
        UniqueConstraint('code_hash', name='uq_master_code_hash'),
        {'comment': 'Table des codes d\'activation pour l\'inscription des utilisateurs'}
    )

    id = Column(Integer, primary_key=True, index=True)
    code_hash = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True, comment="Description du code (ex: Code promo janvier 2025)")
    
    # Créateur et gestion
    created_by = Column(Integer, ForeignKey("utilisateurs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=True, comment="Date d'expiration du code")
    
    # Statut et utilisation
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    max_uses = Column(Integer, nullable=True, comment="Nombre maximum d'utilisations (NULL = illimité)")
    used_count = Column(Integer, default=0, nullable=False)
    
    # Métadonnées additionnelles
    last_used_at = Column(DateTime, nullable=True)
    used_by_roles = Column(String(255), nullable=True, comment="Rôles autorisés à utiliser ce code (séparés par des virgules)")
    
    # Relations
    creator = relationship("Utilisateur", foreign_keys=[created_by], lazy="joined")
    utilisations = relationship("MasterCodeUsage", back_populates="master_code", cascade="all, delete-orphan")
    
    @hybrid_property
    def is_expired(self) -> bool:
        """Vérifie si le code est expiré"""
        if self.expires_at:
            return datetime.utcnow() > self.expires_at
        return False
    
    @hybrid_property
    def is_exhausted(self) -> bool:
        """Vérifie si le code a atteint son nombre maximum d'utilisations"""
        if self.max_uses is not None:
            return self.used_count >= self.max_uses
        return False
    
    @hybrid_property
    def is_available(self) -> bool:
        """Vérifie si le code est disponible pour utilisation"""
        return self.is_active and not self.is_expired and not self.is_exhausted
    
    @staticmethod
    def hash_code(raw_code: str) -> str:
        """Hash le code en utilisant SHA-256"""
        return hashlib.sha256(raw_code.encode()).hexdigest()
    
    @staticmethod
    def generate_random_code(length: int = 8) -> str:
        """Génère un code aléatoire sécurisé"""
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def increment_usage(self, session) -> None:
        """Incrémente le compteur d'utilisation"""
        self.used_count += 1
        self.last_used_at = datetime.utcnow()
        session.add(self)