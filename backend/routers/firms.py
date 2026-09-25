from fastapi import APIRouter, Query, Request
from typing import List, Dict, Any
from services.firms_service import fetch_realtime_hotspots, fetch_area_hotspots
from models.hotspot import FIRMSHotspot, HotspotGeoJSON
from limiter import limiter

router = APIRouter(prefix="/firms", tags=["FIRMS Data"])

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

import logging

logger = logging.getLogger(__name__)

@router.get("/realtime")
@limiter.limit("60/minute")
async def get_realtime(
    request: Request,
    country: str = Query("IND", description="Country Code"),
    days: int = Query(1, description="Number of days"),
    source: str = Query("VIIRS_SNPP_NRT", description="FIRMS Source")
):
    try:
        hotspots = await fetch_realtime_hotspots(country, days, source)
        return to_geojson(hotspots)
    except Exception as e:
        logger.error(f"Error fetching realtime FIRMS hotspots: {e}")
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
