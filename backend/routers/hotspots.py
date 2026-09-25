from fastapi import APIRouter, Query, BackgroundTasks, HTTPException, Request, Depends
from typing import List, Dict, Any, Optional
import logging
from services.classifier import classify_and_store, classify_hotspots
from services.firms_service import fetch_realtime_hotspots, point_in_india
from services.persistence_service import calculate_persistent_sources
from db.supabase_client import supabase_service
from limiter import limiter
from core.security import verify_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hotspots", tags=["Hotspots"])

# Module-level cache for latest results
latest_results = []

@router.get("/classified")
@limiter.limit("60/minute")
async def get_classified_hotspots(
    request: Request,
    country: str = Query("IND"),
    days: int = Query(1),
    classification: Optional[str] = None,
    min_frp: Optional[float] = None,
    max_frp: Optional[float] = None,
    min_confidence: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = Query(500, le=1000)
):
    try:
        # Build query for Supabase
        query = supabase_service.table("hotspots").select("*, classifications(*)").order("created_at", desc=True)
        
        if min_frp is not None:
            query = query.gte("frp", min_frp)
        if max_frp is not None:
            query = query.lte("frp", max_frp)
            
        # Execute query
        try:
            res = query.execute()
            records = res.data or []
        except Exception as q_err:
            logger.warning(f"Database query failed: {q_err}")
            records = []

        # If Supabase has no records, serve identified anomalies from in-memory cache or on-demand classification
        if not records:
            if not latest_results:
                logger.info("Empty database/cold start: Triggering on-demand classification from live FIRMS observations")
                try:
                    await classify_and_store(country=country, days=days)
                except Exception as c_err:
                    logger.warning(f"On-demand classification failed: {c_err}")

            if latest_results:
                features = []
                for item in latest_results:
                    h = item.hotspot
                    cls = item.classification
                    osm = item.osm_context
                    cls_val = cls.classification.value if hasattr(cls.classification, "value") else str(cls.classification)
                    
                    if classification and cls_val != classification:
                        continue
                    if risk_level and cls.risk_level != risk_level:
                        continue
                    if min_frp is not None and (h.frp or 0) < min_frp:
                        continue
                    if max_frp is not None and (h.frp or 0) > max_frp:
                        continue

                    features.append({
                        "type": "Feature",
                        "id": getattr(h, "_db_id", f"firms-{h.latitude}-{h.longitude}"),
                        "geometry": {
                            "type": "Point",
                            "coordinates": [h.longitude, h.latitude]
                        },
                        "properties": {
                            "hotspot": h.dict(),
                            "classification": {
                                "classification": cls_val,
                                "confidence_score": cls.confidence_score,
                                "explanation": cls.explanation,
                                "evidence": cls.evidence,
                                "risk_score": cls.risk_score,
                                "risk_level": cls.risk_level,
                                "source_data": cls.source_data
                            },
                            "osm_context": {
                                "nearby_facilities": osm.nearby_facilities,
                                "nearest_facility_distance": osm.nearest_facility_distance,
                                "nearest_facility_type": osm.nearest_facility_type,
                                "land_use_context": osm.land_use_context,
                                "water_context": osm.water_context,
                                "near_water": osm.near_water,
                                "osm_source": osm.osm_source.value if hasattr(osm.osm_source, "value") else str(osm.osm_source)
                            }
                        }
                    })
                    if len(features) >= limit:
                        break
                return {
                    "type": "FeatureCollection",
                    "features": features
                }

        # Find the latest available acquisition date among records.
        # If new observations have arrived, filter to the active window (latest date).
        # If today's pass hasn't arrived yet, records from the most recent available date
        # stay visible so the operational view doesn't disappear prematurely.
        valid_dates = [str(r.get("acq_date"))[:10] for r in records if r.get("acq_date")]
        if valid_dates and days is not None and days > 0:
            from datetime import datetime, timedelta
            try:
                latest_dt = max(datetime.strptime(d, "%Y-%m-%d") for d in valid_dates)
                cutoff_dt = latest_dt - timedelta(days=days - 1)
                cutoff_date_str = cutoff_dt.strftime("%Y-%m-%d")
                records = [
                    r for r in records
                    if not r.get("acq_date") or str(r.get("acq_date"))[:10] >= cutoff_date_str
                ]
            except Exception as dt_err:
                logger.warning(f"Could not apply date cutoff on hotspots: {dt_err}")

        features = []
        for r in records:
            lat = float(r.get("latitude", 0))
            lon = float(r.get("longitude", 0))
            if not point_in_india(lat, lon):
                continue

            # Filter by classification fields (since postgrest nested filtering can be tricky, we do it in memory for now)
            class_data = r.get("classifications", [])
            class_data.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            primary_class = class_data[0] if class_data and len(class_data) > 0 else {}
            
            primary_osm = dict(primary_class.get("osm_context") or {}) if primary_class else {}
            
            if primary_class and primary_class.get("classification"):
                from services.classifier import calculate_risk_score, calculate_dynamic_confidence, ClassificationEnum
                frp = float(r.get("frp") or 0.0)
                conf = str(r.get("confidence") or "n")
                dist = primary_osm.get("nearest_facility_distance")
                cls_val = primary_class.get("classification")
                try:
                    enum_val = ClassificationEnum(cls_val)
                    score, level = calculate_risk_score(enum_val, frp, dist, conf)
                    primary_class["risk_score"] = score
                    primary_class["risk_level"] = level

                    # Dynamically compute realistic confidence if legacy score was hardcoded 0.7 or missing
                    curr_conf = primary_class.get("confidence_score")
                    if curr_conf is None or abs(float(curr_conf) - 0.70) < 0.001:
                        primary_class["confidence_score"] = calculate_dynamic_confidence(r, enum_val, primary_osm)
                except Exception:
                    pass
            
            if classification and primary_class.get("classification") != classification:
                continue
            if risk_level and primary_class.get("risk_level") != risk_level:
                continue
                
            features.append({
                "type": "Feature",
                "id": r.get("id"),
                "geometry": {
                    "type": "Point",
                    "coordinates": [r.get("longitude", 0), r.get("latitude", 0)]
                },
                "properties": {
                    "hotspot": r,
                    "classification": primary_class,
                    "osm_context": primary_osm
                }
            })
            
            if len(features) >= limit:
                break
                
        return {
            "type": "FeatureCollection",
            "features": features
        }
    except Exception as e:
        logger.warning(f"Database fetch failed, returning empty collection: {e}")
        return {
            "type": "FeatureCollection",
            "features": []
        }

@router.post("/persistent-sources/calculate")
@limiter.limit("5/minute")
async def calculate_persistent_sources_endpoint(request: Request):
    try:
        data = await calculate_persistent_sources()
        return {"count": len(data), "persistent_sources": data}
    except Exception as e:
        logger.warning(f"Could not calculate persistent sources: {e}")
        return {"count": 0, "persistent_sources": []}

@router.get("/persistent-sources")
@limiter.limit("60/minute")
async def get_persistent_sources(request: Request, limit: int = Query(500, le=1000)):
    try:
        res = supabase_service.table("persistent_sources").select("*").order("active_days", desc=True).limit(limit).execute()
        return {"persistent_sources": res.data or []}
    except Exception as e:
        logger.warning(f"Could not load persistent sources: {e}")
        return {"persistent_sources": []}


@router.post("/reclassify-current")
@limiter.limit("2/minute")
async def reclassify_current(request: Request, admin_user: Any = Depends(verify_admin_user)):
    """Re-enrich and reclassify current FIRMS observations so improved context rules are applied."""
    try:
        live = await fetch_realtime_hotspots(country="IND", days=1)
        recent = supabase_service.table("hotspots").select("id,latitude,longitude,acq_date,acq_time").order("created_at", desc=True).limit(5000).execute().data or []
        lookup = {}
        for row in recent:
            key = (round(float(row.get("latitude")), 6), round(float(row.get("longitude")), 6), str(row.get("acq_date")), str(row.get("acq_time")).zfill(4))
            lookup[key] = row
        matched = []
        for h in live:
            key = (round(float(h.latitude), 6), round(float(h.longitude), 6), str(h.acq_date), str(h.acq_time).zfill(4))
            row = lookup.get(key)
            if row:
                setattr(h, "_db_id", row["id"])
                matched.append(h)
        results = await classify_hotspots(matched)
        updated = 0
        for item in results:
            db_id = getattr(item.hotspot, "_db_id", None)
            if not db_id:
                continue
            payload = {
                "classification": item.classification.classification.value,
                "confidence_score": item.classification.confidence_score,
                "explanation": item.classification.explanation,
                "evidence": item.classification.evidence,
                "risk_score": item.classification.risk_score,
                "risk_level": item.classification.risk_level,
                "source_data": item.classification.source_data,
                "osm_context": {
                    "nearby_facilities": item.osm_context.nearby_facilities,
                    "nearest_facility_distance": item.osm_context.nearest_facility_distance,
                    "nearest_facility_type": item.osm_context.nearest_facility_type,
                    "facility_count_in_radius": item.osm_context.facility_count_in_radius,
                    "land_use_context": item.osm_context.land_use_context,
                    "water_context": item.osm_context.water_context,
                    "near_water": item.osm_context.near_water,
                    "osm_source": item.osm_context.osm_source.value if hasattr(item.osm_context.osm_source, "value") else str(item.osm_context.osm_source),
                },
            }
            latest = supabase_service.table("classifications").select("id").eq("hotspot_id", db_id).order("created_at", desc=True).limit(1).execute().data or []
            if latest:
                supabase_service.table("classifications").update(payload).eq("id", latest[0]["id"]).execute()
                updated += 1
        return {"matched": len(matched), "reclassified": updated}
    except Exception as exc:
        logger.exception("Current reclassification failed")
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/{id}")
@limiter.limit("60/minute")
async def get_hotspot_by_id(request: Request, id: str):
    """
    Fetch a single hotspot from the Supabase database.
    """
    try:
        response = supabase_service.table("hotspots").select("*, classifications(*)").eq("id", id).single().execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Hotspot not found")
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/classify")
@limiter.limit("5/minute")
async def trigger_classification(
    request: Request,
    background_tasks: BackgroundTasks,
    country: str = Query("IND"),
    days: int = Query(1),
    admin_user: Any = Depends(verify_admin_user)
):
    """
    Triggers the pipeline as a background task.
    """
    background_tasks.add_task(classify_and_store, country, days)
    return {"message": "Classification pipeline started"}

@router.post("/sweep_pending")
async def sweep_pending_records():
    res = supabase_service.table('classifications').select('*').limit(1).execute()
    if res.data:
        keys = list(res.data[0].keys())
        return {"keys": keys}
    return {"message": "No data"}
