import httpx
import csv
from io import StringIO
from typing import List, Optional, Tuple
import logging
import time
import json
from pathlib import Path

from config import settings
from models.hotspot import FIRMSHotspot

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# India bounding box: West, South, East, North
# ─────────────────────────────────────────────────────────────────────────────
INDIA_BBOX = "68.0,6.0,97.5,37.0"

# Sources tried in order — first one with data wins
_FIRMS_SOURCES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
]

# ─────────────────────────────────────────────────────────────────────────────
# India boundary (shapely) — load once at module import
# ─────────────────────────────────────────────────────────────────────────────
_INDIA_BOUNDARY_PREPARED = None
try:
    from shapely.geometry import shape, Point
    from shapely.prepared import prep

    _geojson_path = Path(__file__).parent / "india_boundary.geojson"
    with open(_geojson_path, "r", encoding="utf-8") as f:
        _india_geojson = json.load(f)
        _INDIA_BOUNDARY_PREPARED = prep(shape(_india_geojson["geometry"]))
    logger.info("India boundary GeoJSON loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load India boundary GeoJSON: {e}")


def point_in_india(lat: float, lon: float) -> bool:
    if _INDIA_BOUNDARY_PREPARED is not None:
        from shapely.geometry import Point
        return _INDIA_BOUNDARY_PREPARED.covers(Point(lon, lat))
    # Bbox fallback
    return 6.0 <= lat <= 37.0 and 68.0 <= lon <= 97.5


# ─────────────────────────────────────────────────────────────────────────────
# Cache — keyed by (source, days, bbox)
# Empty-result TTL is short (30 s) so we retry quickly; success TTL is 5 min
# ─────────────────────────────────────────────────────────────────────────────
_FIRMS_CACHE: dict = {}
_CACHE_TTL_SECONDS = 300        # 5 min for real data
_EMPTY_CACHE_TTL_SECONDS = 30   # 30 s for empty result (retry soon)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_realtime_hotspots(
    country: str = "IND",
    days: int = 1,
    source: str = "VIIRS_SNPP_NRT",
    bbox: Optional[str] = None,
) -> List[FIRMSHotspot]:
    """
    Fetch real-time FIRMS hotspots for India.
    Tries multiple satellite sources and expands to days=2 if day=1 is empty.
    Returns the first non-empty result; falls back to [] if all fail.
    """
    if bbox is None:
        bbox = INDIA_BBOX

    cache_key = f"{country}_{days}_multi_{bbox}"
    now = time.time()

    # Serve from cache if still fresh
    if cache_key in _FIRMS_CACHE:
        cached_time, cached_data = _FIRMS_CACHE[cache_key]
        ttl = _CACHE_TTL_SECONDS if cached_data else _EMPTY_CACHE_TTL_SECONDS
        if now - cached_time < ttl:
            logger.info(
                f"Cache hit: {len(cached_data)} hotspots "
                f"({int(now - cached_time)}s old)"
            )
            return cached_data

    hotspots = await _fetch_with_fallbacks(bbox, country, days)

    # If still empty, widen to 2 days
    if not hotspots:
        logger.info("No hotspots for 1 day — trying days=2")
        hotspots = await _fetch_with_fallbacks(bbox, country, days=2)

    # India boundary filter
    before = len(hotspots)
    hotspots = [h for h in hotspots if point_in_india(h.latitude, h.longitude)]
    logger.info(f"India boundary filter: {before} → {len(hotspots)} hotspots")

    # Sort by FRP descending
    hotspots.sort(key=lambda h: h.frp or 0.0, reverse=True)

    # Cache (empty or full)
    _FIRMS_CACHE[cache_key] = (now, hotspots)
    return hotspots


async def fetch_area_hotspots(
    bbox: str,
    days: int = 1,
    source: str = "VIIRS_SNPP_NRT",
) -> List[FIRMSHotspot]:
    """Fetch FIRMS hotspots for a specific bounding box (India-filtered)."""
    hotspots = await _fetch_with_fallbacks(bbox, country=None, days=days)
    return [h for h in hotspots if point_in_india(h.latitude, h.longitude)]


async def fetch_raw_debug(
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    bbox: str = INDIA_BBOX,
) -> dict:
    """
    Debug helper: returns the raw NASA response text and parsed count so
    you can see exactly what NASA is sending.
    """
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv"
        f"/{settings.FIRMS_MAP_KEY}/{source}/{bbox}/{days}"
    )
    async with httpx.AsyncClient(verify=False) as client:
        try:
            r = await client.get(url, timeout=60.0)
            raw = r.text
            lines = raw.strip().splitlines()
            return {
                "url": url.replace(settings.FIRMS_MAP_KEY, "***"),
                "status_code": r.status_code,
                "line_count": len(lines),
                "first_100_chars": raw[:200],
                "is_invalid_api_call": raw.strip() == "Invalid API call.",
            }
        except Exception as e:
            return {"url": url.replace(settings.FIRMS_MAP_KEY, "***"), "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_with_fallbacks(
    bbox: str, country: Optional[str], days: int
) -> List[FIRMSHotspot]:
    """Try each satellite source in order; return first non-empty result."""
    for src in _FIRMS_SOURCES:
        # 1. Area API (bbox)
        area_url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv"
            f"/{settings.FIRMS_MAP_KEY}/{src}/{bbox}/{days}"
        )
        hotspots = await _fetch_and_parse(area_url, label=f"{src}/area/{days}d")
        if hotspots:
            logger.info(f"Got {len(hotspots)} hotspots from {src} area API")
            return hotspots

        # 2. Country API fallback
        if country:
            country_url = (
                f"https://firms.modaps.eosdis.nasa.gov/api/country/csv"
                f"/{settings.FIRMS_MAP_KEY}/{src}/{country}/{days}"
            )
            hotspots = await _fetch_and_parse(country_url, label=f"{src}/country/{days}d")
            if hotspots:
                logger.info(f"Got {len(hotspots)} hotspots from {src} country API")
                return hotspots

    logger.warning(f"All FIRMS sources returned 0 hotspots for days={days}")
    return []


async def _fetch_and_parse(url: str, label: str = "") -> List[FIRMSHotspot]:
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(url, timeout=60.0)
            response.raise_for_status()

            csv_data = response.text
            stripped = csv_data.strip()

            if not stripped:
                logger.info(f"[{label}] Empty response from NASA")
                return []

            if stripped == "Invalid API call.":
                logger.warning(f"[{label}] NASA returned 'Invalid API call.' — check FIRMS_MAP_KEY")
                return []

            # NASA sometimes returns an HTML error page
            if stripped.startswith("<"):
                logger.warning(f"[{label}] NASA returned HTML (likely error page), {len(stripped)} chars")
                return []

            reader = csv.DictReader(StringIO(csv_data))

            hotspots: List[FIRMSHotspot] = []
            for row in reader:
                try:
                    def num(name: str, fallback=None):
                        value = row.get(name, fallback)
                        if value in (None, ""):
                            return None
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return None

                    hotspot = FIRMSHotspot(
                        latitude=num("latitude") or 0.0,
                        longitude=num("longitude") or 0.0,
                        bright_ti4=num("bright_ti4") or num("bright_ti5"),
                        brightness=num("brightness") or num("bright_ti4"),
                        scan=num("scan"),
                        track=num("track"),
                        version=row.get("version"),
                        bright_t31=num("bright_t31"),
                        frp=num("frp"),
                        confidence=row.get("confidence"),
                        daynight=row.get("daynight"),
                        satellite=row.get("satellite"),
                        acq_date=row.get("acq_date"),
                        acq_time=row.get("acq_time"),
                        instrument=row.get("instrument"),
                    )
                    hotspots.append(hotspot)
                except Exception as e:
                    logger.warning(f"[{label}] Failed to parse row: {e} — row={row}")

            logger.info(f"[{label}] Parsed {len(hotspots)} hotspots from NASA")
            return hotspots

        except httpx.HTTPStatusError as e:
            logger.error(f"[{label}] FIRMS HTTP error {e.response.status_code}")
            return []
        except httpx.TimeoutException:
            logger.warning(f"[{label}] NASA FIRMS request timed out after 60s")
            return []
        except Exception as e:
            logger.error(f"[{label}] Unexpected error: {e}")
            return []
