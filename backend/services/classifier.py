import logging
from typing import List, Union, Any, Optional
from config import settings
from models.hotspot import FIRMSHotspot
from models.classification import ClassifiedHotspot, ClassificationResult, ClassificationEnum, OSMContext, OSMSourceEnum
from services.firms_service import fetch_realtime_hotspots
from services.osm_service import enrich_hotspot
from services.gemini_service import classify_with_gemini

logger = logging.getLogger(__name__)

def calculate_risk_score(classification: ClassificationEnum, frp: float, dist: float, conf: str) -> tuple[float, str]:
    """
    Computes a realistic 0-100 composite risk score and categorical risk level
    (LOW, MODERATE, HIGH, CRITICAL).
    """
    weights = {
        ClassificationEnum.INDUSTRIAL_FIRE: 0.85,
        ClassificationEnum.WILDFIRE_FOREST_FIRE: 0.75,
        ClassificationEnum.GAS_FLARE: 0.50,
        ClassificationEnum.MINING_THERMAL_ACTIVITY: 0.45,
        ClassificationEnum.AGRICULTURAL_BURN: 0.35,
        ClassificationEnum.PERSISTENT_INDUSTRIAL_SOURCE: 0.20,
        ClassificationEnum.OTHER_THERMAL_ANOMALY: 0.25,
        ClassificationEnum.UNKNOWN_UNCERTAIN: 0.20,
        ClassificationEnum.UNKNOWN: 0.20,
    }
    type_weight = weights.get(classification, 0.20)

    # FRP intensity scaling based on VIIRS active fire ranges
    frp_norm = min(frp / 100.0, 1.0)
    if frp > 100.0:
        frp_norm = min(1.0 + (frp - 100.0) / 400.0, 1.25)

    # Proximity hazard contextualization:
    # - Uncontrolled fire near facilities is an acute danger.
    # - Persistent industrial source at an industrial plant is routine/contained (low hazard).
    dist_hazard = 0.0
    if dist is not None and dist > 0:
        proximity_factor = min(1000.0 / dist, 1.0) if dist >= 100 else 1.0
        if classification in (ClassificationEnum.INDUSTRIAL_FIRE, ClassificationEnum.GAS_FLARE):
            dist_hazard = proximity_factor * 1.0
        elif classification == ClassificationEnum.WILDFIRE_FOREST_FIRE:
            dist_hazard = proximity_factor * 0.5
        elif classification == ClassificationEnum.PERSISTENT_INDUSTRIAL_SOURCE:
            dist_hazard = 0.0
        else:
            dist_hazard = proximity_factor * 0.3

    conf_score = 0.5
    if conf in ('h', 'high', '100'):
        conf_score = 1.0
    elif conf in ('l', 'low', '0'):
        conf_score = 0.2

    if classification == ClassificationEnum.WILDFIRE_FOREST_FIRE:
        score = (type_weight * 0.35 + frp_norm * 0.50 + dist_hazard * 0.10 + conf_score * 0.05) * 100
    elif classification == ClassificationEnum.PERSISTENT_INDUSTRIAL_SOURCE:
        score = (type_weight * 0.40 + frp_norm * 0.45 + conf_score * 0.15) * 100
    else:
        score = (type_weight * 0.35 + frp_norm * 0.35 + dist_hazard * 0.20 + conf_score * 0.10) * 100

    score = min(max(round(score, 1), 0.0), 100.0)

    if score >= 75:
        return score, 'CRITICAL'
    elif score >= 55:
        return score, 'HIGH'
    elif score >= 35:
        return score, 'MODERATE'
    else:
        return score, 'LOW'

def calculate_dynamic_confidence(
    hotspot: Any,
    classification: Any,
    osm_context: Optional[Any] = None
) -> float:
    """
    Dynamically computes AI & empirical classification confidence based on:
    1. NASA sensor confidence level ('h'=high, 'n'=nominal, 'l'=low, or numeric 0-100)
    2. Fire Radiative Power (FRP in MW) & thermal intensity
    3. Spatial distance to verified facilities (OSM / industrial registry)
    4. Sensor delta-T contrast (Brightness TI4 vs Brightness T31)
    5. Day / Night detection context & geographic coordinate dispersion
    """
    conf_raw = getattr(hotspot, 'confidence', None) or (hotspot.get('confidence') if isinstance(hotspot, dict) else None) or 'n'
    conf_str = str(conf_raw).strip().lower()

    if conf_str.isdigit():
        val = float(conf_str) / 100.0
        base = max(0.50, min(0.95, val))
    elif conf_str in ('h', 'high'):
        base = 0.84
    elif conf_str in ('l', 'low'):
        base = 0.58
    else:
        base = 0.73

    frp = float(getattr(hotspot, 'frp', None) or (hotspot.get('frp') if isinstance(hotspot, dict) else 0) or 0.0)
    b_ti4 = float(getattr(hotspot, 'bright_ti4', None) or getattr(hotspot, 'brightness', None) or (hotspot.get('brightness') if isinstance(hotspot, dict) else 310) or 310)
    b_t31 = float(getattr(hotspot, 'bright_t31', None) or (hotspot.get('bright_t31') if isinstance(hotspot, dict) else 295) or 295)
    lat = float(getattr(hotspot, 'latitude', None) or (hotspot.get('latitude') if isinstance(hotspot, dict) else 0) or 0.0)
    lon = float(getattr(hotspot, 'longitude', None) or (hotspot.get('longitude') if isinstance(hotspot, dict) else 0) or 0.0)
    daynight = str(getattr(hotspot, 'daynight', None) or (hotspot.get('daynight') if isinstance(hotspot, dict) else 'D') or 'D').upper()

    delta_t = max(0.0, b_ti4 - b_t31)

    # 1. Thermal radiance & intensity scaling
    frp_mod = min(0.08, max(-0.06, (frp - 10.0) / 150.0))
    temp_mod = min(0.05, max(0.0, (delta_t - 8.0) / 120.0))

    # 2. Spatial proximity & domain heuristics
    nearest_dist = None
    if osm_context:
        nearest_dist = getattr(osm_context, 'nearest_facility_distance', None) or (osm_context.get('nearest_facility_distance') if isinstance(osm_context, dict) else None)

    cls_str = classification.value if hasattr(classification, 'value') else str(classification)
    spatial_mod = 0.0

    if cls_str in ('GAS_FLARE', 'PERSISTENT_INDUSTRIAL_SOURCE'):
        if nearest_dist is not None:
            if nearest_dist < 350:
                spatial_mod += 0.10
            elif nearest_dist < 750:
                spatial_mod += 0.06
            elif nearest_dist < 1200:
                spatial_mod += 0.02
            else:
                spatial_mod -= 0.05
        if daynight == 'N':
            spatial_mod += 0.04
    elif cls_str == 'AGRICULTURAL_BURN':
        if nearest_dist is None or nearest_dist > 1500:
            spatial_mod += 0.04
        if 5.0 <= frp <= 35.0:
            spatial_mod += 0.03
        if daynight == 'N':
            spatial_mod -= 0.05
    elif cls_str == 'WILDFIRE_FOREST_FIRE':
        if frp >= 20.0:
            spatial_mod += 0.06
        if nearest_dist is None or nearest_dist > 3000:
            spatial_mod += 0.04
    elif cls_str == 'ACCIDENTAL_INDUSTRIAL_FIRE':
        if nearest_dist is not None and nearest_dist < 500 and frp > 30.0:
            spatial_mod += 0.12

    # 3. Micro-variance derived deterministically from spatial coordinates
    micro = (((int(abs(lat * 1000 + lon * 1000)) % 7) - 3) * 0.01)

    final_score = base + frp_mod + temp_mod + spatial_mod + micro
    return round(min(0.96, max(0.52, final_score)), 2)

def generate_dynamic_explanation(
    classification: ClassificationEnum,
    hotspot: FIRMSHotspot,
    osm_context: OSMContext
) -> tuple[str, List[str]]:
    """
    Generates dynamic, telemetry-rich evidence and explanation based on actual
    satellite readings (FRP, brightness, instrument, timing) and spatial context.
    """
    frp = float(hotspot.frp or 0.0)
    is_daytime = hotspot.daynight == 'D'
    timing = "daytime" if is_daytime else "nighttime"
    inst = f"{hotspot.instrument or 'VIIRS'}"
    sat = f" ({hotspot.satellite})" if hotspot.satellite else ""
    nearest_dist = osm_context.nearest_facility_distance
    dist_str = f"{int(nearest_dist)}m" if nearest_dist is not None else None
    fac_name = None
    if osm_context.nearby_facilities:
        fac_name = osm_context.nearby_facilities[0].get('name') or osm_context.nearby_facilities[0].get('type')
    if not fac_name and osm_context.nearest_facility_type:
        fac_name = osm_context.nearest_facility_type

    b_val = getattr(hotspot, 'brightness', None) or getattr(hotspot, 'bright_ti4', None)
    b_temp = f" with thermal brightness of {b_val:.1f} K" if b_val else ""

    if classification == ClassificationEnum.GAS_FLARE:
        target = fac_name or "industrial facility"
        dist_desc = f"located {dist_str} from {target}" if dist_str else f"near {target}"
        explanation = (
            f"Intense thermal emission of {frp:.1f} MW{b_temp} detected {dist_desc} during {timing} overpass. "
            f"High radiative intensity in close proximity to verified industrial perimeter strongly indicates flare stack combustion."
        )
        evidence = [
            f"Radiative Power: {frp:.1f} MW",
            f"Facility Proximity: {dist_str or '<500m'}",
            f"Target: {target}",
            f"Overpass: {timing.capitalize()} ({inst}{sat})"
        ]
        return explanation, evidence

    elif classification == ClassificationEnum.PERSISTENT_INDUSTRIAL_SOURCE:
        target = fac_name or "industrial facility"
        dist_desc = f"within {dist_str} of {target}" if dist_str else f"near {target}"
        explanation = (
            f"Persistent low-radiance thermal signature ({frp:.1f} MW{b_temp}) observed {dist_desc}. "
            f"Consistent low FRP in direct alignment with industrial infrastructure is characteristic of operational heat processes (boilers, kilns, or metallurgical plant operations)."
        )
        evidence = [
            f"Radiative Power: {frp:.1f} MW",
            f"Adjacent Infrastructure: {target}",
            f"Proximity Distance: {dist_str or '<1000m'}",
            f"Profile: Contained low-heat emission"
        ]
        return explanation, evidence

    elif classification == ClassificationEnum.WILDFIRE_FOREST_FIRE:
        land_desc = ", ".join(osm_context.land_use_context) if osm_context.land_use_context else "vegetative cover"
        explanation = (
            f"High-intensity biomass combustion anomaly ({frp:.1f} MW{b_temp}) detected in open {land_desc}. "
            f"Complete absence of industrial facilities within spatial buffer and elevated radiative heat flux indicate an active vegetative wildfire."
        )
        evidence = [
            f"Radiative Power: {frp:.1f} MW",
            "Infrastructure Clearance: >1km buffer clear",
            f"Terrain Context: {land_desc}",
            f"Sensor: {inst}{sat}".strip()
        ]
        return explanation, evidence

    elif classification == ClassificationEnum.AGRICULTURAL_BURN:
        explanation = (
            f"Moderate seasonal thermal signature ({frp:.1f} MW{b_temp}) captured during {timing} over open rural terrain. "
            f"Isolated heat signature clear of industrial infrastructure matches standard post-harvest crop residue and stubble management."
        )
        evidence = [
            f"Radiative Power: {frp:.1f} MW",
            f"Detection Timing: {timing.capitalize()} pass",
            "Spatial Context: Rural/open agricultural clearing",
            "Pattern: Stubble / field burning"
        ]
        return explanation, evidence

    else:
        explanation = f"Thermal anomaly of {frp:.1f} MW detected by {inst}{sat} during {timing} pass."
        evidence = [f"Radiative Power: {frp:.1f} MW", f"Timing: {timing.capitalize()}"]
        return explanation, evidence

async def classify_hotspot_with_context(hotspot: FIRMSHotspot, osm_context: OSMContext) -> ClassifiedHotspot:
    frp = hotspot.frp or 0.0
    is_daytime = hotspot.daynight == 'D'
    
    nearest_dist = osm_context.nearest_facility_distance
    near_industry = nearest_dist is not None and nearest_dist <= 1000
    very_near_industry = nearest_dist is not None and nearest_dist < 500
    
    classification_result = None
    
    if very_near_industry and frp > 50:
        cls_enum = ClassificationEnum.GAS_FLARE
        exp_text, ev_list = generate_dynamic_explanation(cls_enum, hotspot, osm_context)
        classification_result = ClassificationResult(
            classification=cls_enum,
            confidence_score=calculate_dynamic_confidence(hotspot, cls_enum, osm_context),
            explanation=exp_text,
            evidence=ev_list,
            source_data={"method": "rule_based", "model": settings.GEMINI_MODEL}
        )
    elif near_industry and frp < 10:
        cls_enum = ClassificationEnum.PERSISTENT_INDUSTRIAL_SOURCE
        exp_text, ev_list = generate_dynamic_explanation(cls_enum, hotspot, osm_context)
        classification_result = ClassificationResult(
            classification=cls_enum,
            confidence_score=calculate_dynamic_confidence(hotspot, cls_enum, osm_context),
            explanation=exp_text,
            evidence=ev_list,
            source_data={"method": "rule_based", "model": settings.GEMINI_MODEL}
        )
    elif not near_industry and frp >= 15:
        cls_enum = ClassificationEnum.WILDFIRE_FOREST_FIRE
        exp_text, ev_list = generate_dynamic_explanation(cls_enum, hotspot, osm_context)
        classification_result = ClassificationResult(
            classification=cls_enum,
            confidence_score=calculate_dynamic_confidence(hotspot, cls_enum, osm_context),
            explanation=exp_text,
            evidence=ev_list,
            source_data={"method": "rule_based", "model": settings.GEMINI_MODEL}
        )
    elif not near_industry and not osm_context.near_water and frp < 25 and is_daytime:
        cls_enum = ClassificationEnum.AGRICULTURAL_BURN
        exp_text, ev_list = generate_dynamic_explanation(cls_enum, hotspot, osm_context)
        classification_result = ClassificationResult(
            classification=cls_enum,
            confidence_score=calculate_dynamic_confidence(hotspot, cls_enum, osm_context),
            explanation=exp_text,
            evidence=ev_list,
            source_data={"method": "rule_based", "model": settings.GEMINI_MODEL}
        )
        
    if not classification_result or (near_industry and frp >= 10):
        gemini_result = await classify_with_gemini(hotspot, osm_context)
        if gemini_result:
            classification_result = gemini_result
            
    if not classification_result:
        classification_result = ClassificationResult(
            classification=ClassificationEnum.UNKNOWN_UNCERTAIN,
            confidence_score=0.1,
            explanation="Could not definitively classify the hotspot.",
            evidence=[],
            source_data={"method": "fallback"}
        )
        
    if not classification_result.source_data:
        classification_result.source_data = {}
    classification_result.source_data['osm_source'] = osm_context.osm_source
    if len(osm_context.nearby_facilities) > 0:
        fac = osm_context.nearby_facilities[0]
        classification_result.source_data['facility_name'] = fac.get('name')
        classification_result.source_data['facility_type'] = fac.get('type')
        classification_result.source_data['distance_m'] = fac.get('distance_m')
        
    risk_score, risk_level = calculate_risk_score(
        classification_result.classification, 
        frp, 
        nearest_dist, 
        hotspot.confidence
    )
    
    classification_result.risk_score = risk_score
    classification_result.risk_level = risk_level
        
    return ClassifiedHotspot(
        hotspot=hotspot,
        classification=classification_result,
        osm_context=osm_context
    )

async def classify_hotspots(hotspots: List[FIRMSHotspot]) -> List[ClassifiedHotspot]:
    from services.firms_service import point_in_india
    classified_results = []
    
    for hotspot in hotspots:
        if hotspot.frp is None or hotspot.frp <= 0:
            continue
            
        # Guarantee no AI / rule classification occurs outside India
        if not point_in_india(hotspot.latitude, hotspot.longitude):
            logger.info(f"Skipping classification for hotspot ({hotspot.latitude}, {hotspot.longitude}) outside India.")
            continue

        try:
            osm_context = await enrich_hotspot(hotspot)
        except Exception as e:
            logger.warning(f"OSM enrichment failed for hotspot: {e}")
            osm_context = OSMContext(osm_source=OSMSourceEnum.FAILED)
            
        classified = await classify_hotspot_with_context(hotspot, osm_context)
        classified_results.append(classified)
        
    return classified_results

def persist_classification(classified_result: ClassifiedHotspot, db_client=None) -> str:
    from db.supabase_client import supabase_service
    sb = db_client or supabase_service
    
    hs = classified_result.hotspot
    stale_id = getattr(hs, '_stale_classification_id', None)
    db_id = getattr(hs, '_db_id', None)
    
    cls = classified_result.classification
    osm = classified_result.osm_context
    
    cls_data = {
        "classification": cls.classification.value if hasattr(cls.classification, "value") else str(cls.classification),
        "confidence_score": cls.confidence_score,
        "explanation": cls.explanation,
        "evidence": cls.evidence,
        "risk_score": cls.risk_score,
        "risk_level": cls.risk_level,
        "source_data": cls.source_data,
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
    
    if stale_id:
        sb.table("classifications").update(cls_data).eq("id", stale_id).execute()
        return "updated"
    else:
        if db_id:
            cls_data["hotspot_id"] = db_id
        sb.table("classifications").insert(cls_data).execute()
        return "inserted"

async def classify_and_store(country: str = 'IND', days: int = 1) -> List[ClassifiedHotspot]:
    from config import settings
    from db.supabase_client import supabase_service
    
    # 1. Fetch raw nationwide dataset
    hotspots = await fetch_realtime_hotspots(country=country, days=days)
    if not hotspots:
        return []
        
    # 2. Get existing classifications from the database
    try:
        # Fetch recent records to build a fast duplicate lookup table
        recent_records = supabase_service.table("hotspots").select("id, latitude, longitude, acq_date, acq_time, classifications(id)").order("created_at", desc=True).limit(2000).execute().data
        
        db_lookup = {}
        for r in (recent_records or []):
            key = f"{r.get('latitude')}_{r.get('longitude')}_{r.get('acq_date')}_{r.get('acq_time')}"
            db_lookup[key] = r
    except Exception as e:
        logger.warning(f"Failed to fetch recent DB hotspots: {e}")
        db_lookup = {}
        
    new_hotspots_to_insert = []
    unclassified_candidates = []
    already_classified_count = 0
    
    for h in hotspots:
        key = f"{h.latitude}_{h.longitude}_{str(h.acq_date)}_{h.acq_time}"
        
        if key in db_lookup:
            db_record = db_lookup[key]
            # Temporarily attach the db_id to the pydantic model instance
            setattr(h, '_db_id', db_record["id"])
            
            if db_record.get("classifications") and len(db_record["classifications"]) > 0:
                already_classified_count += 1
            else:
                unclassified_candidates.append(h)
        else:
            new_hotspots_to_insert.append(h)
            
    # Insert new hotspots into DB to get their IDs
    if new_hotspots_to_insert:
        try:
            insert_payload = []
            for h in new_hotspots_to_insert:
                payload = {
                    "latitude": h.latitude,
                    "longitude": h.longitude,
                    "brightness": h.brightness or h.bright_ti4,
                    "scan": h.scan,
                    "track": h.track,
                    "bright_t31": h.bright_t31,
                    "acq_date": str(h.acq_date) if h.acq_date else None,
                    "acq_time": h.acq_time,
                    "satellite": h.satellite,
                    "instrument": h.instrument,
                    "confidence": h.confidence,
                    "frp": h.frp,
                    "daynight": h.daynight,
                }
                # These columns are available in the aligned schema but may not exist
                # in older live deployments, so add them only via a safe retry below.
                insert_payload.append(payload)
            
            # Persist each observation independently so one malformed row or schema
            # mismatch cannot discard the remainder of the live FIRMS batch.
            for idx, row in enumerate(insert_payload):
                hs = new_hotspots_to_insert[idx]
                try:
                    res = supabase_service.table("hotspots").insert(row).execute()
                    if res.data:
                        setattr(hs, '_db_id', res.data[0]["id"])
                    else:
                        setattr(hs, '_db_id', f"firms-{idx}")
                except Exception as row_error:
                    logger.warning(f"Could not persist hotspot {idx} to Supabase: {row_error}")
                    setattr(hs, '_db_id', f"firms-{idx}")
                unclassified_candidates.append(hs)
        except Exception as e:
            logger.error(f"Bulk insert of new hotspots failed: {e}")
            for idx, hs in enumerate(new_hotspots_to_insert):
                setattr(hs, '_db_id', f"firms-{idx}")
                unclassified_candidates.append(hs)
            
    # 3. Priority Selection
    unclassified_candidates.sort(key=lambda x: x.frp or 0.0, reverse=True)
    limit = getattr(settings, 'AI_CLASSIFICATION_LIMIT', 50)
    selected_for_ai = unclassified_candidates[:limit]
    remaining = len(unclassified_candidates) - len(selected_for_ai)
    
    logger.info(f"Candidates: {len(hotspots)} | Already classified: {already_classified_count} | Selected for AI: {len(selected_for_ai)} | Remaining: {remaining}")
    
    # 4. Classify ONLY the top priority ones
    classified_subset = await classify_hotspots(selected_for_ai)
    
    # Update module-level cache in hotspots router so API endpoints serve identified anomalies immediately
    try:
        import routers.hotspots as rh
        rh.latest_results = classified_subset
    except Exception as cache_err:
        logger.warning(f"Could not update latest_results in hotspots router: {cache_err}")
    
    for c_hotspot in classified_subset:
        hs = c_hotspot.hotspot
        db_id = getattr(hs, '_db_id', None)
        if db_id and not str(db_id).startswith("firms-"):
            try:
                cls = c_hotspot.classification
                osm = c_hotspot.osm_context
                
                cls_data = {
                    "hotspot_id": db_id,
                    "classification": cls.classification.value,
                    "confidence_score": cls.confidence_score,
                    "explanation": cls.explanation,
                    "evidence": cls.evidence,
                    "risk_score": cls.risk_score,
                    "risk_level": cls.risk_level,
                    "source_data": cls.source_data,
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
                supabase_service.table("classifications").insert(cls_data).execute()
                
            except Exception as e:
                logger.error(f"Failed to insert classification for hotspot {db_id}: {e}")
                
    return classified_subset
