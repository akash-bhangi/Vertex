import httpx
import csv
from io import StringIO
from typing import List, Optional
import logging
from config import settings
from models.hotspot import FIRMSHotspot

logger = logging.getLogger(__name__)

# India bounding box: West, South, East, North
INDIA_BBOX = "68.0,6.0,97.5,37.0"
# Karnataka bounding box for faster testing
KARNATAKA_BBOX = "74.0,11.5,78.5,18.5"

import json
from pathlib import Path
from shapely.geometry import shape, Point
from shapely.prepared import prep

# Load high-fidelity India boundary GeoJSON
_INDIA_BOUNDARY_SHAPE = None
_INDIA_BOUNDARY_PREPARED = None
try:
    _geojson_path = Path(__file__).parent / 'india_boundary.geojson'
    with open(_geojson_path, 'r', encoding='utf-8') as f:
        _india_geojson = json.load(f)
        _INDIA_BOUNDARY_SHAPE = shape(_india_geojson['geometry'])
        _INDIA_BOUNDARY_PREPARED = prep(_INDIA_BOUNDARY_SHAPE)
except Exception as e:
    logger.error(f"Failed to load India boundary GeoJSON: {e}")

def point_in_india(lat: float, lon: float) -> bool:
    if _INDIA_BOUNDARY_PREPARED is not None:
        return _INDIA_BOUNDARY_PREPARED.covers(Point(lon, lat))
    # Fallback to India bounding box check if GeoJSON is missing
    return 6.0 <= lat <= 37.0 and 68.0 <= lon <= 97.5

_point_in_india = point_in_india

import time

_FIRMS_CACHE = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes

async def fetch_realtime_hotspots(
    country: str = 'IND',
    days: int = 1,
    source: str = 'VIIRS_SNPP_NRT',
    bbox: Optional[str] = None
) -> List[FIRMSHotspot]:
    """
    Fetch real-time FIRMS hotspots. Uses area/bbox API (more reliable than country API).
    Defaults to India's bounding box to keep processing bounded.
    """
    if bbox is None:
        bbox = INDIA_BBOX

    cache_key = f"{country}_{days}_{source}_{bbox}"
    now = time.time()
    if cache_key in _FIRMS_CACHE:
        cached_time, cached_data = _FIRMS_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS and cached_data:
            logger.info(f"Serving {len(cached_data)} FIRMS hotspots from cache ({int(now - cached_time)}s old)")
            return cached_data

    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.FIRMS_MAP_KEY}/{source}/{bbox}/{days}"
    hotspots = await _fetch_and_parse(url)
    
    # Fallback to country API if area query returns empty or times out
    if not hotspots and country:
        country_url = f"https://firms.modaps.eosdis.nasa.gov/api/country/csv/{settings.FIRMS_MAP_KEY}/{source}/{country}/{days}"
        logger.info(f"Area query returned 0 hotspots, trying country API: {country_url}")
        hotspots = await _fetch_and_parse(country_url)
    
    before = len(hotspots)
    hotspots = [h for h in hotspots if point_in_india(h.latitude, h.longitude)]
    logger.info(f"India boundary filter: {before} → {len(hotspots)} hotspots")
        
    # Sort by FRP descending so clients can easily slice highest priority if needed
    hotspots.sort(key=lambda h: h.frp or 0.0, reverse=True)
    if hotspots:
        _FIRMS_CACHE[cache_key] = (now, hotspots)
    return hotspots

async def fetch_area_hotspots(
    bbox: str,
    days: int = 1,
    source: str = 'VIIRS_SNPP_NRT'
) -> List[FIRMSHotspot]:
    """Fetch FIRMS hotspots for a specific bounding box (filtered strictly to India)."""
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.FIRMS_MAP_KEY}/{source}/{bbox}/{days}"
    hotspots = await _fetch_and_parse(url)
    hotspots = [h for h in hotspots if point_in_india(h.latitude, h.longitude)]
    return hotspots

async def _fetch_and_parse(url: str) -> List[FIRMSHotspot]:
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(url, timeout=60.0)
            response.raise_for_status()

            csv_data = response.text
            if not csv_data or csv_data.strip() == "Invalid API call.":
                logger.warning(f"FIRMS API returned invalid response for URL: {url[:80]}...")
                return []

            reader = csv.DictReader(StringIO(csv_data))

            hotspots = []
            for row in reader:
                try:
                    def num(name, fallback=None):
                        value = row.get(name, fallback)
                        if value in (None, ''):
                            return None
                        return float(value)

                    hotspot = FIRMSHotspot(
                        latitude=num('latitude', 0) or 0.0,
                        longitude=num('longitude', 0) or 0.0,
                        bright_ti4=num('bright_ti4', row.get('bright_ti5')),
                        brightness=num('brightness', row.get('bright_ti4')),
                        scan=num('scan'),
                        track=num('track'),
                        version=row.get('version'),
                        bright_t31=num('bright_t31'),
                        frp=num('frp'),
                        confidence=row.get('confidence'),
                        daynight=row.get('daynight'),
                        satellite=row.get('satellite'),
                        acq_date=row.get('acq_date'),
                        acq_time=row.get('acq_time'),
                        instrument=row.get('instrument')
                    )
                    hotspots.append(hotspot)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse FIRMS row: {e}")

            logger.info(f"Fetched {len(hotspots)} hotspots from FIRMS")
            return hotspots
        except httpx.HTTPStatusError as e:
            logger.error(f"FIRMS API HTTP error {e.response.status_code}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching FIRMS data: {e}")
            return []
