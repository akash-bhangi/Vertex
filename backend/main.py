from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging
from config import settings
from limiter import limiter

from routers import health, firms, osm, hotspots, analytics, satellite
from db.supabase_client import supabase_anon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="VERTEX API",
    description="AI-based industrial fire detection platform for SIH 26162",
    version="1.0.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(firms.router, prefix="/api/v1")
app.include_router(osm.router, prefix="/api/v1")
app.include_router(hotspots.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(satellite.router, prefix="/api/v1")

from jobs.scheduler import start_scheduler, stop_scheduler
from db.supabase_client import seed_admin_user

@app.on_event("startup")
async def startup_event():
    logger.info("Starting VERTEX API...")
    logger.info("Validating settings...")
    
    assert settings.FIRMS_MAP_KEY, "FIRMS_MAP_KEY is missing!"
    assert settings.SUPABASE_URL, "SUPABASE_URL is missing!"
    assert settings.SUPABASE_ANON_KEY, "SUPABASE_ANON_KEY is missing!"
    assert settings.GEMINI_API_KEY, "GEMINI_API_KEY is missing!"
    
    logger.info(f"EARTHDATA credentials present: {bool(settings.EARTHDATA_USER)}")
    logger.info(f"CDSE credentials present: {bool(settings.CDSE_CLIENT_ID)}")
    logger.info(f"PLANETARY_COMPUTER_KEY present: False (Not required)")
    
    # Simple Supabase connection check
    try:
        supabase_anon.table("hotspots").select("id").limit(1).execute()
        logger.info("Supabase connection initialized successfully.")
    except Exception as e:
        logger.warning(f"Could not reach Supabase tables on startup (ignoring): {e}")

    # Seed Admin User
    await seed_admin_user()
    
    # Start Scheduler
    start_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down VERTEX API...")
    stop_scheduler()

