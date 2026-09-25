from fastapi import APIRouter, Query, Request, BackgroundTasks
from typing import List, Dict, Any
from services.firms_service import (
    fetch_realtime_hotspots,
    fetch_area_hotspots,
    fetch_raw_debug,
    _FIRMS_CACHE,
    _CACHE_TTL_SECONDS,
    _EMPTY_CACHE_TTL_SECONDS,
    INDIA_BBOX,
    _FIRMS_SOURCES,
)
from models.hotspot import FIRMSHotspot
from limiter import limiter
import logging
import time
import asyncio

router = APIRouter(prefix="/firms", tags=["FIRMS Data"])

logger = logging.getLogger(__name__)

# In-memory flag: True while a background FIRMS fetch is in progress
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
            "properties": h.dict(exclude={"latitude", "longitude"})
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
        result = await fetch_realtime_hotspots(country, days, source)
        logger.info(f"Background FIRMS fetch complete — {len(result)} hotspots cached.")
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
    source: str = Query("VIIRS_SNPP_NRT", description="FIRMS Source"),
):
    """
    Returns FIRMS hotspots instantly from cache if available.
    On cold cache triggers a background fetch and returns empty immediately.
    The client auto-retries so data appears without 500 errors.
    """
    cache_key = f"{country}_{days}_multi_{INDIA_BBOX}"
    now = time.time()

    # Serve from cache if fresh
    if cache_key in _FIRMS_CACHE:
        cached_time, cached_data = _FIRMS_CACHE[cache_key]
        ttl = _CACHE_TTL_SECONDS if cached_data else _EMPTY_CACHE_TTL_SECONDS
        if now - cached_time < ttl:
            logger.info(f"Cache hit → {len(cached_data)} hotspots (realtime endpoint)")
            return to_geojson(cached_data)

    # Cold or stale — kick off background fetch and return immediately
    logger.info("Cache cold/stale — triggering background FIRMS fetch.")
    background_tasks.add_task(_background_firms_fetch, country, days, source)
    return to_geojson([])


@router.get("/debug")
@limiter.limit("10/minute")
async def debug_firms(
    request: Request,
    source: str = Query("VIIRS_SNPP_NRT"),
    days: int = Query(1),
):
    """
    Debug endpoint: returns raw NASA FIRMS response metadata so you can
    verify the API key is valid and data is actually arriving.
    Also shows the current cache state.
    """
    results = []
    for src in _FIRMS_SOURCES:
        info = await fetch_raw_debug(source=src, days=days, bbox=INDIA_BBOX)
        results.append(info)

    cache_key = f"IND_{days}_multi_{INDIA_BBOX}"
    cached = _FIRMS_CACHE.get(cache_key)
    cache_info = None
    if cached:
        cached_time, cached_data = cached
        cache_info = {
            "hotspot_count": len(cached_data),
            "age_seconds": int(time.time() - cached_time),
        }

    return {
        "nasa_responses": results,
        "cache": cache_info,
        "fetch_in_progress": _fetch_in_progress,
    }


@router.get("/area")
@limiter.limit("60/minute")
async def get_area(
    request: Request,
    bbox: str = Query(..., description="Bounding box (W,S,E,N)"),
    days: int = Query(1, description="Number of days"),
    source: str = Query("VIIRS_SNPP_NRT", description="FIRMS Source"),
):
    try:
        hotspots = await fetch_area_hotspots(bbox, days, source)
        return to_geojson(hotspots)
    except Exception as e:
        logger.error(f"Error fetching area FIRMS hotspots: {e}")
        return to_geojson([])
