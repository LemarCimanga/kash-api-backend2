from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.core.database import Base
from datetime import datetime, timedelta
import re

class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    __table_args__ = (
        UniqueConstraint('matricule', name='uq_utilisateur_matricule'),
        UniqueConstraint('numero_telephone', name='uq_utilisateur_telephone'),
        {'comment': 'Table des utilisateurs du système'}
    )

    # Identifiants
    id = Column(Integer, primary_key=True, index=True)
    matricule = Column(String(50), unique=True, nullable=False, index=True)
    
    # Informations personnelles
    nom = Column(String(50), nullable=False)
    postnom = Column(String(50), nullable=False)
    prenom = Column(String(50), nullable=False)
    numero_telephone = Column(String(20), unique=True, nullable=True)
    email = Column(String(100), unique=True, nullable=True, index=True)  # Ajout pour futur support
    photo = Column(Text, nullable=False, server_default="")
    
    # Sécurité
    mot_de_passe = Column(String(255), nullable=False)
    password_changed_at = Column(DateTime, nullable=True)
    password_reset_token = Column(String(255), nullable=True, index=True)
    password_reset_expires = Column(DateTime, nullable=True)
    
    # Rôle et statut
    role = Column(String(50), nullable=False, index=True)
    statut = Column(String(20), default="actif", index=True)
    
    # Sécurité des connexions
    tentative_connexion = Column(Integer, default=0)
    verrouille_jusqua = Column(DateTime, nullable=True)
    derniere_connexion = Column(DateTime, nullable=True)
    derniere_ip = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    
    # Audit
    created_by = Column(Integer, ForeignKey("utilisateurs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now(), nullable=True)
    last_modified_by = Column(Integer, ForeignKey("utilisateurs.id", ondelete="SET NULL"), nullable=True)
    
    # Relations
    creator = relationship("Utilisateur", foreign_keys=[created_by], remote_side=[id])
    modifier = relationship("Utilisateur", foreign_keys=[last_modified_by], remote_side=[id])
    
    # Sessions et tokens
    tokens = relationship("UserToken", back_populates="user", cascade="all, delete-orphan")
    utilisations_master_code = relationship("MasterCodeUsage", back_populates="utilisateur")
    
    @hybrid_property
    def full_name(self) -> str:
        """Retourne le nom complet de l'utilisateur"""
        return f"{self.prenom} {self.nom} {self.postnom}".strip()
    
    @hybrid_property
    def is_locked(self) -> bool:
        """Vérifie si le compte est verrouillé"""
        if self.verrouille_jusqua:
            return datetime.utcnow() < self.verrouille_jusqua
        return False
    
    @hybrid_property
    def is_active(self) -> bool:
        """Vérifie si le compte est actif"""
        return self.statut == "actif" and not self.is_locked
    
    def increment_login_attempts(self, max_attempts: int = 5, lock_duration_minutes: int = 30):
        """Incrémente les tentatives de connexion et verrouille si nécessaire"""
        self.tentative_connexion += 1
        
        if self.tentative_connexion >= max_attempts:
            self.verrouille_jusqua = datetime.utcnow() + timedelta(minutes=lock_duration_minutes)
            self.statut = "suspendu"
        
        return self.tentative_connexion
    
    def reset_login_attempts(self):
        """Réinitialise les tentatives de connexion"""
        self.tentative_connexion = 0
        self.verrouille_jusqua = None
        if self.statut == "suspendu":
            self.statut = "actif"
    
    def update_last_login(self, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """Met à jour les informations de dernière connexion"""
        self.derniere_connexion = datetime.utcnow()
        if ip_address:
            self.derniere_ip = ip_address
        if user_agent:
            self.user_agent = user_agent
        self.reset_login_attempts()
    
    @staticmethod
    def generate_matricule(prefix: str = "KASH", db_session=None) -> str:
        """Génère un matricule unique"""
        if db_session:
            # Compter les utilisateurs existants avec ce préfixe
            count = db_session.query(Utilisateur).filter(
                Utilisateur.matricule.like(f"{prefix}%")
            ).count()
            return f"{prefix}{str(count + 1).zfill(5)}"
        else:
            # Fallback avec timestamp
            from datetime import datetime
            return f"{prefix}{datetime.utcnow().strftime('%y%m%d%H%M%S')}"
    
    def to_dict(self, exclude_sensitive: bool = True) -> dict:
        """Convertit l'utilisateur en dictionnaire"""
        data = {
            "id": self.id,
            "matricule": self.matricule,
            "nom": self.nom,
            "postnom": self.postnom,
            "prenom": self.prenom,
            "full_name": self.full_name,
            "numero_telephone": self.numero_telephone,
            "email": self.email,
            "photo": self.photo,
            "role": self.role,
            "statut": self.statut,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "derniere_connexion": self.derniere_connexion.isoformat() if self.derniere_connexion else None,
            "is_locked": self.is_locked,
            "is_active": self.is_active
        }
        
        if not exclude_sensitive:
            data.update({
                "tentative_connexion": self.tentative_connexion,
                "verrouille_jusqua": self.verrouille_jusqua.isoformat() if self.verrouille_jusqua else None,
                "derniere_ip": self.derniere_ip,
                "created_by": self.created_by
            })
        
        return data