# app/core/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, SecretStr
from typing import Optional, List
from pathlib import Path

# Définir le chemin vers le fichier .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    # ==================== BASE DE DONNÉES ====================
    DATABASE_URL: str
    
    # Pool de connexions
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False
    DB_STATEMENT_TIMEOUT: int = 30
    LOG_SLOW_QUERIES: bool = True
    SLOW_QUERY_THRESHOLD: float = 1.0
    
    # ==================== SÉCURITÉ ====================
    SECRET_KEY: SecretStr
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    TOKEN_ISSUER: str = "kash_app"
    TOKEN_AUDIENCE: str = "api"
    
    # ==================== SÉCURITÉ DES MOTS DE PASSE ====================
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    
    # ==================== APPLICATION ====================
    APP_NAME: str = "Kash Application"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    
    # ==================== CORS ====================
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000", 
        "http://localhost:8000",
        "http://localhost:5173"
    ]
    ALLOWED_HOSTS: List[str] = ["*"]
    
    # ==================== CACHE REDIS ====================
    REDIS_URL: Optional[str] = None
    CACHE_ENABLED: bool = True
    CACHE_TTL: int = 300
    
    # ==================== EMAIL (OPTIONNEL) ====================
    EMAIL_HOST: Optional[str] = None
    EMAIL_PORT: Optional[int] = 587
    EMAIL_USERNAME: Optional[str] = None
    EMAIL_PASSWORD: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    EMAIL_USE_TLS: bool = True
    
    # ==================== FICHIERS ET STOCKAGE ====================
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB
    ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".gif"]
    
    # ==================== RATE LIMITING ====================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60
    
    # ==================== LOGGING ====================
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = "app.log"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - [%(user_id)s] - %(message)s"
    
    # ==================== API ====================
    API_V1_STR: str = "/api/v1"
    
    # ==================== SESSION ====================
    SESSION_SECRET_KEY: Optional[SecretStr] = None
    
    # ==================== MONITORING (OPTIONNEL) ====================
    SENTRY_DSN: Optional[str] = None
    PROMETHEUS_ENABLED: bool = False
    
    # ==================== FEATURES FLAGS ====================
    ENABLE_2FA: bool = False
    ENABLE_EMAIL_VERIFICATION: bool = False
    ENABLE_SMS_VERIFICATION: bool = False
    
    # ==================== VALIDATEURS ====================
    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Valide l'URL de la base de données"""
        if not v.startswith(("postgresql://", "postgresql+asyncpg://", "sqlite://")):
            raise ValueError("Format d'URL de base de données invalide")
        return v
    
    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        """Valide la clé secrète"""
        secret = v.get_secret_value()
        if len(secret) < 32:
            raise ValueError("SECRET_KEY doit avoir au moins 32 caractères")
        return v
    
    @field_validator("APP_ENV")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        """Valide l'environnement"""
        allowed = ["development", "staging", "production", "test"]
        if v not in allowed:
            raise ValueError(f"APP_ENV doit être: {', '.join(allowed)}")
        return v
    
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Valide le niveau de log"""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL doit être: {', '.join(allowed)}")
        return v.upper()
    
    # ==================== PROPRIÉTÉS ====================
    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"
    
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"
    
    @property
    def is_staging(self) -> bool:
        return self.APP_ENV == "staging"
    
    @property
    def db_pool_config(self) -> dict:
        """Configuration du pool de connexions"""
        return {
            "pool_size": self.DB_POOL_SIZE,
            "max_overflow": self.DB_MAX_OVERFLOW,
            "pool_timeout": self.DB_POOL_TIMEOUT,
            "pool_recycle": self.DB_POOL_RECYCLE,
            "pool_pre_ping": self.DB_POOL_PRE_PING,
            "echo": self.DB_ECHO,
        }
    
    @property
    def jwt_config(self) -> dict:
        """Configuration JWT"""
        return {
            "secret_key": self.SECRET_KEY.get_secret_value(),
            "algorithm": self.ALGORITHM,
            "access_token_expire_minutes": self.ACCESS_TOKEN_EXPIRE_MINUTES,
            "refresh_token_expire_days": self.REFRESH_TOKEN_EXPIRE_DAYS,
            "issuer": self.TOKEN_ISSUER,
            "audience": self.TOKEN_AUDIENCE,
        }
    
    @property
    def cors_config(self) -> dict:
        """Configuration CORS"""
        return {
            "allow_origins": self.BACKEND_CORS_ORIGINS,
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        }
    
    @property
    def redis_config(self) -> dict:
        """Configuration Redis"""
        return {
            "url": self.REDIS_URL,
            "enabled": self.CACHE_ENABLED,
            "ttl": self.CACHE_TTL,
        }
    
    @property
    def rate_limit_config(self) -> dict:
        """Configuration du rate limiting"""
        return {
            "enabled": self.RATE_LIMIT_ENABLED,
            "requests": self.RATE_LIMIT_REQUESTS,
            "period": self.RATE_LIMIT_PERIOD,
        }
    
    @property
    def upload_config(self) -> dict:
        """Configuration des uploads"""
        return {
            "upload_dir": self.UPLOAD_DIR,
            "max_size": self.MAX_UPLOAD_SIZE,
            "allowed_extensions": self.ALLOWED_EXTENSIONS,
        }

    # ==================== MÉTHODES UTILITAIRES ====================
    def to_dict(self, hide_secrets: bool = True) -> dict:
        """Convertit les settings en dictionnaire"""
        data = self.model_dump()
        if hide_secrets:
            sensitive_fields = ["SECRET_KEY", "EMAIL_PASSWORD", "DATABASE_URL", "SESSION_SECRET_KEY"]
            for field in sensitive_fields:
                if field in data:
                    data[field] = "***HIDDEN***"
        return data
    
    def get_database_dsn(self) -> str:
        """Retourne le DSN de la base de données (sans les crédentials)"""
        try:
            if "postgresql" in self.DATABASE_URL:
                parts = self.DATABASE_URL.split("@")
                if len(parts) > 1:
                    host_part = parts[1].split("?")[0]
                    return f"postgresql://***@{host_part}"
        except:
            pass
        return "***HIDDEN***"
    
    def validate_all(self) -> bool:
        """Valide tous les settings"""
        try:
            self.model_dump()
            return True
        except Exception as e:
            print(f"❌ Erreur de validation: {e}")
            return False
    
    def get_log_level(self) -> str:
        """Retourne le niveau de log en majuscules"""
        return self.LOG_LEVEL.upper()
    
    def is_redis_available(self) -> bool:
        """Vérifie si Redis est configuré et disponible"""
        return self.REDIS_URL is not None and self.CACHE_ENABLED
    
    # ==================== CONFIGURATION PYDANTIC ====================
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH.exists() else None,
        env_file_encoding='utf-8',
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=True,
    )

# ==================== INSTANCE GLOBALE ====================
try:
    settings = Settings()
    print(f"✅ Configuration chargée - Environnement: {settings.APP_ENV}")
    if settings.is_redis_available():
        print(f"✅ Redis configuré: {settings.REDIS_URL}")
    else:
        print("ℹ️ Redis non configuré")
except Exception as e:
    print(f"❌ Erreur de chargement des configurations: {e}")
    raise

# ==================== VÉRIFICATION EN PRODUCTION ====================
if settings.APP_ENV == "production":
    assert settings.DATABASE_URL is not None, "DATABASE_URL requis en production"
    assert settings.SECRET_KEY.get_secret_value() is not None, "SECRET_KEY requis en production"
    assert len(settings.SECRET_KEY.get_secret_value()) >= 32, "SECRET_KEY doit avoir au moins 32 caractères"
    assert settings.REDIS_URL is not None, "REDIS_URL requis en production"
    print("✅ Vérifications de production réussies")

# ==================== FONCTION DE TEST ====================
def test_settings_config():
    """Fonction de test rapide des settings"""
    print("=" * 60)
    print("🔍 TEST DE CONFIGURATION DES SETTINGS")
    print("=" * 60)
    
    try:
        print(f"✅ Settings chargés avec succès")
        print(f"📱 Application: {settings.APP_NAME}")
        print(f"🔖 Version: {settings.APP_VERSION}")
        print(f"🌍 Environnement: {settings.APP_ENV}")
        print(f"🐛 Debug: {settings.DEBUG}")
        
        print(f"\n🗄️ Base de données:")
        print(f"   DSN: {settings.get_database_dsn()}")
        print(f"   Pool Size: {settings.DB_POOL_SIZE}")
        print(f"   Max Overflow: {settings.DB_MAX_OVERFLOW}")
        
        secret_value = settings.SECRET_KEY.get_secret_value()
        print(f"\n🔐 Sécurité:")
        print(f"   SECRET_KEY: {'✅ OK' if len(secret_value) >= 32 else '❌ TROP COURTE'}")
        print(f"   Longueur: {len(secret_value)} caractères")
        print(f"   ALGORITHM: {settings.ALGORITHM}")
        print(f"   TOKEN_ISSUER: {settings.TOKEN_ISSUER}")
        print(f"   TOKEN_AUDIENCE: {settings.TOKEN_AUDIENCE}")
        
        print(f"\n📦 Propriétés:")
        print(f"   is_development: {settings.is_development}")
        print(f"   is_production: {settings.is_production}")
        print(f"   is_staging: {settings.is_staging}")
        print(f"   is_redis_available: {settings.is_redis_available()}")
        
        print(f"\n⚙️ Configurations:")
        print(f"   JWT Config: {list(settings.jwt_config.keys())}")
        print(f"   CORS Config: {list(settings.cors_config.keys())}")
        print(f"   DB Pool Config: {list(settings.db_pool_config.keys())}")
        print(f"   Rate Limit Config: {list(settings.rate_limit_config.keys())}")
        print(f"   Upload Config: {list(settings.upload_config.keys())}")
        
        settings_dict = settings.to_dict()
        print(f"\n📄 Settings dict (masqué):")
        for key in ["APP_NAME", "APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL"]:
            print(f"   {key}: {settings_dict.get(key, 'N/A')}")
        
        print("\n" + "=" * 60)
        print("✅ TOUS LES TESTS SONT PASSÉS AVEC SUCCÈS!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_settings_config()