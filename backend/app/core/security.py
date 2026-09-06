from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from .config import get_settings
from .supabase import get_supabase_client

security = HTTPBearer(auto_error=False)

# Minimal user representation from validated token
class CurrentUser:
    def __init__(self, user_id: str, email: str | None = None):
        self.id = user_id
        self.email = email


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — missing token",
        )
    token = credentials.credentials
    settings = get_settings()

    # Try supabase verification via service client if configured
    # Fallback to local JWT decode if JWT secret is available
    # If no supabase config, allow token as opaque for local dev (but still require it)
    if settings.supabase_url and settings.supabase_service_role_key:
        try:
            client = get_supabase_client()
            if client:
                # Supabase Auth: get user from token
                # Using anon client with token in header would be ideal, but we can try service client
                # Supabase-py: client.auth.get_user(token)
                resp = client.auth.get_user(token)
                if resp and resp.user:
                    return CurrentUser(user_id=resp.user.id, email=resp.user.email)
        except Exception:
            pass  # fall through to JWT decode

    # Fallback: decode without verification if no secret, or verify if secret present
    # This allows local dev without Supabase to still have a user_id from token payload if present
    try:
        if settings.supabase_jwt_secret:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            payload = jwt.decode(
                token, options={"verify_signature": False}
            )
        user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
        email = payload.get("email")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token — no subject")
        return CurrentUser(user_id=user_id, email=email)
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
