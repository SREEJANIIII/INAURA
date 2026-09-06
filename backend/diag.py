from app.core.config import get_settings
s = get_settings()
print("URL:", s.supabase_url)
print("anon len", len(s.supabase_anon_key) if s.supabase_anon_key else None)
print("service len", len(s.supabase_service_role_key) if s.supabase_service_role_key else None)
print("jwt secret", repr(s.supabase_jwt_secret))
from app.core.supabase import get_supabase_client
c = get_supabase_client()
print("client is None?", c is None)
if c:
    print("client created")
    try:
        r = c.table("profiles").select("*").limit(1).execute()
        print("profiles query success")
        print("data:", r.data[:2] if r.data else "empty")
        print("count:", len(r.data) if r.data else 0)
    except Exception as e:
        import traceback
        print("profiles query failed:", str(e)[:2000])
        traceback.print_exc()
else:
    print("no client, check env")
