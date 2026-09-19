import threading
from supabase import create_client, Client
from .config import get_settings

# Frontend should use anon key; backend uses service_role for DB access
# Never expose service_role to frontend

_local = threading.local()


def get_supabase_client() -> Client | None:
    """One client per worker thread. Requests run in parallel threads, and a client's HTTP/2
    connection breaks ("ConnectionTerminated") when two threads use it at the same time."""
    client = getattr(_local, "client", None)
    if client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_role_key:
            return None
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        _local.client = client
    return client


def get_supabase_anon_client() -> Client | None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_anon_key)
