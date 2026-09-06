from app.core.config import get_settings
from app.core.supabase import get_supabase_client, get_supabase_anon_client
import traceback

s = get_settings()
print("=== Config ===")
print("SUPABASE_URL:", s.supabase_url)
print("FRONTEND_URL:", s.frontend_url)
print("JWT secret is placeholder?", s.supabase_jwt_secret == "YOUR_JWT_SECRET")
print()

anon = get_supabase_anon_client()
service = get_supabase_client()
print("anon client is None?", anon is None)
print("service client is None?", service is None)
print()

# Try anon query profiles
if anon:
    try:
        r = anon.table("profiles").select("*").limit(1).execute()
        print("anon profiles query success:", r.data)
    except Exception as e:
        print("anon profiles query failed:", str(e)[:500])

print()

# Try service query profiles
if service:
    try:
        r = service.table("profiles").select("*").limit(1).execute()
        print("service profiles query success:", r.data)
    except Exception as e:
        print("service profiles query failed:", str(e)[:1000])
        traceback.print_exc()

print()
# Try to check table existence via service
if service:
    try:
        # Try to create a test profile with dummy data to see error
        # First try to insert a dummy and see what happens (will fail due to FK)
        pass
    except:
        pass

# Try anon signUp with random email to test auth flow
if anon:
    import uuid
    test_email = f"diag_{uuid.uuid4().hex[:8]}@example.com"
    test_pass = "TestPass123!"
    print(f"Trying anon signUp with {test_email}")
    try:
        res = anon.auth.sign_up({"email": test_email, "password": test_pass})
        print("signUp response:", res)
        if res.user:
            print("user id:", res.user.id)
            # Try to get session
            # sign_up may return session if email confirmation disabled
            if res.session:
                print("session token exists, len", len(res.session.access_token) if res.session.access_token else "no token")
                token = res.session.access_token
                # Now try backend verification via service client get_user
                try:
                    cres = service.auth.get_user(token)
                    print("service get_user with anon token success:", cres.user.id if cres.user else "no user")
                except Exception as e:
                    print("service get_user failed:", str(e)[:500])
                # Try backend security decode via jwt fallback
                import jwt
                try:
                    payload = jwt.decode(token, options={"verify_signature": False})
                    print("jwt decode success, sub:", payload.get("sub"))
                except Exception as e:
                    print("jwt decode failed:", e)
                # Try to create profile via service
                try:
                    payload2 = {
                        "user_id": res.user.id,
                        "full_name": "Diag Test",
                        "college": "Test College",
                        "degree": "B.Tech",
                        "branch": "Computer Science",
                        "current_year": "3rd Year",
                        "graduation_year": 2027,
                        "career_interests": ["Software Engineering"],
                        "hours_per_week": 10,
                        "profile_completed": True,
                    }
                    r2 = service.table("profiles").insert(payload2).execute()
                    print("insert test profile success:", r2.data)
                    # cleanup
                    service.table("profiles").delete().eq("user_id", res.user.id).execute()
                    print("cleaned up test profile")
                except Exception as e:
                    print("insert test profile failed:", str(e)[:1000])
                # cleanup user via admin
                try:
                    service.auth.admin.delete_user(res.user.id)
                    print("deleted test user")
                except Exception as e:
                    print("delete user failed:", str(e)[:500])
            else:
                print("no session returned — email confirmation likely required")
                # Need to try sign_in instead? But user not confirmed.
                # Try admin create user with email_confirm true
                print("Trying admin create_user with email_confirm True")
                try:
                    admin_res = service.auth.admin.create_user({"email": test_email, "password": test_pass, "email_confirm": True})
                    print("admin create_user success:", admin_res.user.id if admin_res.user else "no user")
                    if admin_res.user:
                        # Try sign in
                        sign_in = anon.auth.sign_in_with_password({"email": test_email, "password": test_pass})
                        print("sign_in after admin create:", sign_in.session.access_token[:20] if sign_in.session else "no session")
                        # cleanup
                        service.auth.admin.delete_user(admin_res.user.id)
                        print("cleaned admin user")
                except Exception as e:
                    print("admin create failed:", str(e)[:1000])
        else:
            print("no user returned")
    except Exception as e:
        print("signUp failed:", str(e)[:1000])
        traceback.print_exc()
