from functools import lru_cache
from supabase import create_client, Client
from .config import get_settings

# Frontend should use anon key; backend uses service_role for DB access
# Never expose service_role to frontend

@lru_cache
def get_supabase_client() -> Client | None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_supabase_anon_client() -> Client | None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_anon_key)
