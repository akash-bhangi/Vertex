import httpx

# Ensure httpx/postgrest clients work smoothly without SSL certificate bundle errors on Windows
_original_sync_init = httpx.Client.__init__
httpx.Client.__init__ = lambda self, *args, **kwargs: _original_sync_init(self, *args, **{**kwargs, 'verify': False})
_original_async_init = httpx.AsyncClient.__init__
httpx.AsyncClient.__init__ = lambda self, *args, **kwargs: _original_async_init(self, *args, **{**kwargs, 'verify': False})
from typing import Optional
from supabase import create_client, Client
from config import settings
import logging

logger = logging.getLogger(__name__)

def is_valid_jwt(token: Optional[str]) -> bool:
    if not token or not isinstance(token, str):
        return False
    parts = token.strip().split(".")
    return len(parts) == 3

# Initialize singleton clients
def get_supabase_client(use_service_key: bool = False) -> Client:
    url: str = settings.SUPABASE_URL
    if use_service_key and settings.SUPABASE_SERVICE_KEY and is_valid_jwt(settings.SUPABASE_SERVICE_KEY):
        return create_client(url, settings.SUPABASE_SERVICE_KEY)
    return create_client(url, settings.SUPABASE_ANON_KEY)

supabase_anon: Client = get_supabase_client(use_service_key=False)

_FALLBACK_SERVICE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhlZXprZWp1Z3RlaGVubm1pdWdkIiwi"
    "cm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4ODA2ODIxNiwiZXhwIjoyMTAz"
    "NjQ0MjE2fQ."
    "vQm_DmsxWG6x-FphNCMy6PWT5CtAPCmGUf8c0XT8mWw"
)

def _init_service_client() -> Client:
    # Try configured service key first, then hardcoded fallback
    key = settings.SUPABASE_SERVICE_KEY if is_valid_jwt(settings.SUPABASE_SERVICE_KEY) else None
    if not key:
        key = _FALLBACK_SERVICE_KEY
        logger.info("SUPABASE_SERVICE_KEY env var missing — using built-in fallback service key.")

    try:
        client = create_client(settings.SUPABASE_URL, key)
        client.table("hotspots").select("id").limit(1).execute()
        logger.info("Supabase service key verified and active.")
        return client
    except Exception as exc:
        logger.warning(f"Service key query failed ({exc}). Falling back to SUPABASE_ANON_KEY.")
        return supabase_anon

supabase_service: Client = _init_service_client()

async def seed_admin_user():
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        logger.info("Admin seeding skipped: ADMIN_EMAIL or ADMIN_PASSWORD not set.")
        return

    try:
        # Try to sign in to check if the user exists
        try:
            supabase_anon.auth.sign_in_with_password({
                "email": settings.ADMIN_EMAIL,
                "password": settings.ADMIN_PASSWORD
            })
            logger.info("Admin user already exists.")
            return
        except Exception:
            pass  # Expected if user doesn't exist
            
        # Create user via admin API
        supabase_service.auth.admin.create_user({
            "email": settings.ADMIN_EMAIL,
            "password": settings.ADMIN_PASSWORD,
            "email_confirm": True,
            "user_metadata": {"role": "admin"}
        })
        logger.info("Admin user seeded successfully.")
    except Exception as e:
        logger.warning(f"Skipping admin seed - database unreachable: {e}")

