from fastapi import APIRouter, Query, Request, BackgroundTasks
from typing import List, Dict, Any
from services.firms_service import fetch_realtime_hotspots, fetch_area_hotspots, _FIRMS_CACHE, _CACHE_TTL_SECONDS, INDIA_BBOX
from models.hotspot import FIRMSHotspot, HotspotGeoJSON
from limiter import limiter
import logging
import time
import asyncio

router = APIRouter(prefix="/firms", tags=["FIRMS Data"])

logger = logging.getLogger(__name__)

# In-memory flag: True while a background FIRMS fetch is in progress so we
# never dispatch more than one concurrent NASA request
_fetch_in_progress = False


def to_geojson(hotspots: List[FIRMSHotspot]) -> Dict[str, Any]:
    features = []
    for h in hotspots:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [h.longitude, h.latitude]
            },
            "properties": h.dict(exclude={'latitude', 'longitude'})
        })
    return {
        "type": "FeatureCollection",
        "features": features
    }


async def _background_firms_fetch(country: str, days: int, source: str):
    """Runs a FIRMS fetch in the background and populates the cache."""
    global _fetch_in_progress
    if _fetch_in_progress:
        return
    _fetch_in_progress = True
    try:
        await fetch_realtime_hotspots(country, days, source)
        logger.info("Background FIRMS fetch complete — cache populated.")
    except Exception as e:
        logger.error(f"Background FIRMS fetch failed: {e}")
    finally:
        _fetch_in_progress = False


@router.get("/realtime")
@limiter.limit("60/minute")
async def get_realtime(
    request: Request,
    background_tasks: BackgroundTasks,
    country: str = Query("IND", description="Country Code"),
    days: int = Query(1, description="Number of days"),
    source: str = Query("VIIRS_SNPP_NRT", description="FIRMS Source")
):
    """
    Returns FIRMS hotspots instantly from cache if available.
    On first call (cold cache), triggers a background fetch and immediately
    returns an empty FeatureCollection — the client can retry in ~30 seconds.
    This prevents the 30-second Next.js proxy timeout that causes 500 errors.
    """
    cache_key = f"{country}_{days}_{source}_{INDIA_BBOX}"
    now = time.time()

    # Serve from cache if fresh
    if cache_key in _FIRMS_CACHE:
        cached_time, cached_data = _FIRMS_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            logger.info(f"Serving {len(cached_data)} FIRMS hotspots from cache (realtime endpoint)")
            return to_geojson(cached_data)

    # Cache is cold or stale — kick off background fetch and return immediately
    logger.info("FIRMS cache is cold. Triggering background fetch — returning empty for now.")
    background_tasks.add_task(_background_firms_fetch, country, days, source)
    return to_geojson([])


@router.get("/area")
@limiter.limit("60/minute")
async def get_area(
    request: Request,
    bbox: str = Query(..., description="Bounding box (W,S,E,N)"),
    days: int = Query(1, description="Number of days"),
    source: str = Query("VIIRS_SNPP_NRT", description="FIRMS Source")
):
    try:
        hotspots = await fetch_area_hotspots(bbox, days, source)
        return to_geojson(hotspots)
    except Exception as e:
        logger.error(f"Error fetching area FIRMS hotspots: {e}")
        return to_geojson([])
