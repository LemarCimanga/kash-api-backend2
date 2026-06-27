# app/core/cache.py
import json
import logging
from typing import Any, Optional, Union, List, Dict
from datetime import datetime, timedelta
import redis.asyncio as redis
from functools import wraps
from app.core.config import settings
import hashlib

logger = logging.getLogger(__name__)

class CacheService:
    """
    Service de caching Redis asynchrone haute performance
    Supporte les stratégies de cache, les tags et l'invalidation automatique
    """
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._connected: bool = False
        self._default_ttl: int = 300  # 5 minutes
    
    async def connect(self):
        """Initialise la connexion asynchrone au pool Redis"""
        if not settings.REDIS_URL:
            logger.warning("⚠️ REDIS_URL absent des configurations. Cache désactivé.")
            return
        
        try:
            self.redis = redis.from_url(
                settings.REDIS_URL, 
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            # Ping de validation pour confirmer le canal actif
            await self.redis.ping()
            self._connected = True
            logger.info("✅ Connexion au cluster Redis établie avec succès")
            
            # Nettoyer les clés expirées si nécessaire
            if settings.DEBUG:
                await self._cleanup_expired_keys()
                
        except redis.ConnectionError as e:
            logger.error(f"❌ Erreur de connexion Redis : {e}")
            self.redis = None
            self._connected = False
        except Exception as e:
            logger.error(f"❌ Échec de la connexion Redis : {e}")
            self.redis = None
            self._connected = False

    async def disconnect(self):
        """Ferme proprement les connexions au pool"""
        if self.redis:
            try:
                await self.redis.close()
                self._connected = False
                logger.info("🔄 Connexions Redis fermées proprement")
            except Exception as e:
                logger.error(f"❌ Erreur lors de la fermeture de Redis : {e}")
    
    async def _cleanup_expired_keys(self):
        """Nettoie les clés expirées (en développement uniquement)"""
        try:
            # Récupérer toutes les clés
            keys = await self.redis.keys("cache:*")
            expired_count = 0
            for key in keys:
                ttl = await self.redis.ttl(key)
                if ttl <= 0:
                    await self.redis.delete(key)
                    expired_count += 1
            if expired_count > 0:
                logger.info(f"🧹 {expired_count} clés expirées nettoyées du cache")
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors du nettoyage du cache: {e}")
    
    @property
    def is_connected(self) -> bool:
        """Vérifie si Redis est connecté"""
        return self._connected and self.redis is not None
    
    async def get(self, key: str, default: Any = None) -> Optional[Any]:
        """
        Récupère une valeur désérialisée du cache
        
        Args:
            key: Clé du cache
            default: Valeur par défaut si la clé n'existe pas
            
        Returns:
            Valeur désérialisée ou default
        """
        if not self.is_connected:
            return default
        try:
            value = await self.redis.get(key)
            if value is None:
                return default
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Erreur de désérialisation pour la clé {key}: {e}")
            await self.delete(key)
            return default
        except Exception as e:
            logger.warning(f"⚠️ Erreur de lecture du cache pour la clé {key}: {e}")
            return default
    
    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        Récupère plusieurs valeurs du cache en une seule opération
        
        Args:
            keys: Liste des clés
            
        Returns:
            Dictionnaire {clé: valeur} pour les clés existantes
        """
        if not self.is_connected or not keys:
            return {}
        
        try:
            values = await self.redis.mget(keys)
            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
            return result
        except Exception as e:
            logger.warning(f"⚠️ Erreur de lecture multiple du cache: {e}")
            return {}
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """
        Stocke une valeur sérialisée dans le cache
        
        Args:
            key: Clé du cache
            value: Valeur à stocker
            ttl: Durée de vie en secondes (None = durée par défaut)
            nx: Ne définir que si la clé n'existe pas
            xx: Ne définir que si la clé existe
            
        Returns:
            bool: True si le stockage a réussi
        """
        if not self.is_connected:
            return False
        
        ttl = ttl or self._default_ttl
        
        try:
            serialized = json.dumps(value, default=self._json_encoder)
            
            if nx:
                result = await self.redis.setnx(key, serialized)
                if result:
                    await self.redis.expire(key, ttl)
                return bool(result)
            elif xx:
                result = await self.redis.set(key, serialized, xx=True)
                if result:
                    await self.redis.expire(key, ttl)
                return bool(result)
            else:
                await self.redis.setex(key, ttl, serialized)
                return True
                
        except Exception as e:
            logger.warning(f"⚠️ Erreur d'écriture dans le cache pour la clé {key}: {e}")
            return False
    
    def _json_encoder(self, obj: Any) -> Any:
        """Encodeur JSON personnalisé pour les objets spéciaux"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        raise TypeError(f"Type {type(obj)} non sérialisable en JSON")
    
    async def set_many(self, items: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Stocke plusieurs valeurs en une seule opération
        
        Args:
            items: Dictionnaire {clé: valeur}
            ttl: Durée de vie en secondes
            
        Returns:
            bool: True si toutes les valeurs ont été stockées
        """
        if not self.is_connected or not items:
            return False
        
        ttl = ttl or self._default_ttl
        
        try:
            pipeline = self.redis.pipeline()
            for key, value in items.items():
                serialized = json.dumps(value, default=self._json_encoder)
                pipeline.setex(key, ttl, serialized)
            await pipeline.execute()
            return True
        except Exception as e:
            logger.warning(f"⚠️ Erreur d'écriture multiple dans le cache: {e}")
            return False
    
    async def delete(self, *keys: str) -> int:
        """
        Supprime une ou plusieurs clés du cache
        
        Args:
            keys: Clés à supprimer
            
        Returns:
            int: Nombre de clés supprimées
        """
        if not self.is_connected or not keys:
            return 0
        
        try:
            return await self.redis.delete(*keys)
        except Exception as e:
            logger.warning(f"⚠️ Erreur de suppression du cache: {e}")
            return 0
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        Supprime toutes les clés correspondant à un pattern
        
        Args:
            pattern: Pattern (ex: "cache:user:*")
            
        Returns:
            int: Nombre de clés supprimées
        """
        if not self.is_connected:
            return 0
        
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                return await self.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors du nettoyage du pattern {pattern}: {e}")
            return 0
    
    async def exists(self, key: str) -> bool:
        """Vérifie si une clé existe dans le cache"""
        if not self.is_connected:
            return False
        
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.warning(f"⚠️ Erreur de vérification d'existence pour {key}: {e}")
            return False
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Modifie le TTL d'une clé"""
        if not self.is_connected:
            return False
        
        try:
            return await self.redis.expire(key, ttl)
        except Exception as e:
            logger.warning(f"⚠️ Erreur de mise à jour TTL pour {key}: {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Récupère le TTL restant d'une clé (-1 = illimité, -2 = n'existe pas)"""
        if not self.is_connected:
            return -2
        
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.warning(f"⚠️ Erreur de récupération TTL pour {key}: {e}")
            return -2
    
    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Incrémente une valeur numérique dans le cache"""
        if not self.is_connected:
            return None
        
        try:
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.warning(f"⚠️ Erreur d'incrémentation pour {key}: {e}")
            return None
    
    async def clear(self) -> bool:
        """Vide tout le cache (attention : opération lourde)"""
        if not self.is_connected:
            return False
        
        try:
            await self.redis.flushdb()
            logger.info("🧹 Cache vidé")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur lors du vidage du cache: {e}")
            return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques du cache"""
        if not self.is_connected:
            return {"status": "disconnected"}
        
        try:
            info = await self.redis.info()
            keys = await self.redis.keys("cache:*")
            
            # Compter les clés par type
            key_types = {}
            for key in keys[:1000]:  # Limiter pour performance
                key_type = key.split(":")[1] if ":" in key else "unknown"
                key_types[key_type] = key_types.get(key_type, 0) + 1
            
            return {
                "status": "connected",
                "total_keys": len(keys),
                "memory_used": info.get("used_memory_human", "0"),
                "connected_clients": info.get("connected_clients", 0),
                "key_types": key_types,
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "hit_rate": info.get("keyspace_hits_rate", 0),
            }
        except Exception as e:
            logger.warning(f"⚠️ Erreur de récupération des stats: {e}")
            return {"status": "error", "message": str(e)}

# ==================== INSTANCE GLOBALE ====================
cache_service = CacheService()

# ==================== DÉCORATEURS DE CACHE ====================
def cached(ttl: int = 300, key_prefix: str = "", tags: List[str] = None):
    """
    Décorateur asynchrone pour mettre en cache les résultats de fonctions.
    
    Args:
        ttl: Durée de vie en secondes
        key_prefix: Préfixe pour les clés
        tags: Tags pour l'invalidation groupée
    
    Exemple:
        @cached(ttl=60, key_prefix="user", tags=["users", "profiles"])
        async def get_user(db: Session, user_id: int):
            return await db.get(User, user_id)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Générer une clé de cache unique
            key_parts = [key_prefix or "cache", func.__name__]
            
            # Traiter les arguments positionnels
            for arg in args:
                # Ignorer les objets complexes
                if type(arg).__name__ in ["AsyncSession", "Session", "Request", "Response"]:
                    continue
                if hasattr(arg, 'id'):
                    key_parts.append(str(arg.id))
                elif hasattr(arg, '__dict__'):
                    # Pour les objets Pydantic, utiliser leur dict
                    try:
                        key_parts.append(str(arg.dict()))
                    except:
                        key_parts.append(str(arg))
                else:
                    key_parts.append(str(arg))
            
            # Traiter les arguments nommés
            for k, v in kwargs.items():
                if k in ["db", "session", "request", "response"]:
                    continue
                if hasattr(v, 'id'):
                    key_parts.append(f"{k}:{v.id}")
                else:
                    key_parts.append(f"{k}:{v}")
            
            # Générer un hash pour les clés longues
            cache_key = ":".join(key_parts)
            if len(cache_key) > 200:
                cache_key = f"{key_prefix}:{func.__name__}:{hashlib.md5(cache_key.encode()).hexdigest()}"
            
            # Vérifier le cache
            cached_value = await cache_service.get(cache_key)
            if cached_value is not None:
                logger.debug(f"✅ Cache hit: {cache_key}")
                return cached_value
            
            # Exécuter la fonction
            result = await func(*args, **kwargs)
            
            # Mettre en cache si résultat non None
            if result is not None:
                await cache_service.set(cache_key, result, ttl)
                logger.debug(f"✅ Cache set: {cache_key} (TTL: {ttl}s)")
                
                # Si des tags sont fournis, les stocker pour invalidation groupée
                if tags:
                    for tag in tags:
                        tag_key = f"tag:{tag}:keys"
                        await cache_service.redis.sadd(tag_key, cache_key)
                        await cache_service.redis.expire(tag_key, ttl * 2)
            
            return result
        return wrapper
    return decorator

def invalidate_tags(*tags: str):
    """
    Invalide toutes les clés de cache associées à des tags
    
    Args:
        tags: Tags à invalider
    
    Exemple:
        @invalidate_tags("users", "profiles")
        async def update_user(user_id: int):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            
            # Invalider les tags
            for tag in tags:
                tag_key = f"tag:{tag}:keys"
                keys = await cache_service.redis.smembers(tag_key)
                if keys:
                    await cache_service.delete(*keys)
                    await cache_service.delete(tag_key)
                    logger.debug(f"🧹 Cache invalidé pour tag: {tag} ({len(keys)} clés)")
            
            return result
        return wrapper
    return decorator

# ==================== FONCTIONS D'INITIALISATION ====================
async def init_cache():
    """Initialise le service de cache au démarrage de l'application"""
    await cache_service.connect()
    if cache_service.is_connected:
        logger.info("🚀 Cache service initialisé avec succès")
    else:
        logger.warning("⚠️ Cache service démarré en mode fallback (sans Redis)")

async def close_cache():
    """Ferme les connexions Redis à l'arrêt de l'application"""
    await cache_service.disconnect()
    logger.info("🔄 Cache service fermé")

# ==================== CONTEXT MANAGER ====================
from contextlib import asynccontextmanager

@asynccontextmanager
async def cache_context():
    """Context manager pour utiliser le cache dans une session"""
    try:
        await init_cache()
        yield cache_service
    finally:
        await close_cache()