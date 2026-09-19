import threading
import time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient
from .config import get_settings
from .supabase import get_supabase_client

security = HTTPBearer(auto_error=False)

# Minimal user representation from validated token
class CurrentUser:
    def __init__(self, user_id: str, email: str | None = None):
        self.id = user_id
        self.email = email


# Tokens Supabase has already confirmed, so each page load doesn't re-ask Supabase
# (~0.4s per request). Kept only until the token itself expires.
_verified: dict[str, tuple[float, CurrentUser]] = {}
_verified_lock = threading.Lock()
_MAX_VERIFIED = 1000


def _remember(token: str, user: CurrentUser) -> None:
    try:
        exp = float(jwt.decode(token, options={"verify_signature": False}).get("exp") or 0)
    except Exception:
        return
    if exp <= time.time():
        return
    with _verified_lock:
        if len(_verified) >= _MAX_VERIFIED:
            now = time.time()
            for k in [k for k, (e, _) in _verified.items() if e <= now]:
                del _verified[k]
            if len(_verified) >= _MAX_VERIFIED:
                _verified.clear()
        _verified[token] = (exp, user)


def _recall(token: str) -> CurrentUser | None:
    with _verified_lock:
        hit = _verified.get(token)
        if hit and hit[0] > time.time():
            return hit[1]
        _verified.pop(token, None)
    return None


# Plain `def` so FastAPI runs it on a worker thread: the Supabase call below blocks,
# and inside `async def` it would stall every other request while it waits.
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — missing token",
        )
    token = credentials.credentials
    cached = _recall(token)
    if cached:
        return cached
    settings = get_settings()

    # 1. Check the signature here, using Supabase's public key (no network call per request)
    try:
        payload = _verify_locally(token, settings)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Invalid token: session expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception:
        payload = None  # keys unreachable or not configured, so ask Supabase instead
    if payload is not None:
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token — no subject")
        user = CurrentUser(user_id=user_id, email=payload.get("email"))
        _remember(token, user)
        return user

    # 2. Ask Supabase directly
    if settings.supabase_url and settings.supabase_service_role_key:
        try:
            client = get_supabase_client()
            if client:
                resp = client.auth.get_user(token)
                if resp and resp.user:
                    user = CurrentUser(user_id=resp.user.id, email=resp.user.email)
                    _remember(token, user)
                    return user
        except Exception:
            pass

    # A token nobody could verify is never trusted
    raise HTTPException(status_code=401, detail="Invalid token: could not be verified")


_ASYMMETRIC = {"ES256", "RS256", "EdDSA"}
_jwks_client: PyJWKClient | None = None
_jwks_lock = threading.Lock()


def _jwks(settings) -> PyJWKClient:
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None:
            _jwks_client = PyJWKClient(
                settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json",
                headers={"apikey": settings.supabase_anon_key or ""},
                cache_keys=True,
                lifespan=3600,
                timeout=10,
            )
        return _jwks_client


def _verify_locally(token: str, settings) -> dict | None:
    """Returns the verified token contents, raises if the token is forged or expired,
    or returns None when this server can't check it itself."""
    alg = jwt.get_unverified_header(token).get("alg")
    options = {"verify_aud": False, "require": ["exp", "sub"]}
    if alg in _ASYMMETRIC and settings.supabase_url:
        key = _jwks(settings).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], options=options)
    if alg == "HS256" and settings.supabase_jwt_secret:
        try:
            return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], options=options)
        except jwt.InvalidSignatureError:
            return None  # the configured value may not be the real secret, so let Supabase decide
    if alg in _ASYMMETRIC or alg == "HS256":
        return None
    raise jwt.InvalidTokenError(f"unsupported algorithm {alg}")
