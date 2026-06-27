# app/services/user_service.py
from app.core.cache import cache_service, cached, invalidate_tags
from typing import Optional

class UserService:
    
    @cached(ttl=300, key_prefix="user", tags=["users", "profiles"])
    async def get_user_by_id(self, db: AsyncSession, user_id: int) -> Optional[Utilisateur]:
        """Récupère un utilisateur par ID avec cache"""
        result = await db.execute(
            select(Utilisateur).where(Utilisateur.id == user_id)
        )
        return result.scalar_one_or_none()
    
    @cached(ttl=60, key_prefix="user_by_email", tags=["users"])
    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[Utilisateur]:
        """Récupère un utilisateur par email avec cache"""
        result = await db.execute(
            select(Utilisateur).where(Utilisateur.email == email)
        )
        return result.scalar_one_or_none()
    
    @invalidate_tags("users", "profiles")
    async def update_user(self, db: AsyncSession, user_id: int, data: dict) -> Utilisateur:
        """Met à jour un utilisateur et invalide le cache associé"""
        user = await self.get_user_by_id(db, user_id)
        if user:
            for key, value in data.items():
                setattr(user, key, value)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user
        raise NotFoundException("Utilisateur", user_id)
    
    async def search_users(self, db: AsyncSession, query: str) -> List[Utilisateur]:
        """Recherche des utilisateurs avec cache intelligent"""
        cache_key = f"search:{query}"
        
        # Vérifier le cache
        cached_results = await cache_service.get(cache_key)
        if cached_results is not None:
            return cached_results
        
        # Exécuter la recherche
        results = await db.execute(
            select(Utilisateur).where(
                Utilisateur.nom.ilike(f"%{query}%") | 
                Utilisateur.prenom.ilike(f"%{query}%")
            )
        )
        users = results.scalars().all()
        
        # Mettre en cache (TTL plus court car résultats dynamiques)
        await cache_service.set(cache_key, users, ttl=30)
        
        return users