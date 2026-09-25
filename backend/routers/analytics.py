from fastapi import APIRouter, Request
from routers.hotspots import latest_results
from limiter import limiter

from services.firms_service import point_in_india

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/summary")
@limiter.limit("30/minute")
async def get_analytics_summary(request: Request):
    try:
        from db.supabase_client import supabase_service
        
        all_data = []
        page_size = 1000
        start = 0
        while True:
            res = supabase_service.table("hotspots").select(
                "id, latitude, longitude, frp, classifications(classification, risk_level, created_at)"
            ).range(start, start + page_size - 1).execute()
            if not res.data:
                break
            all_data.extend(res.data)
            if len(res.data) < page_size:
                break
            start += page_size
            
        if not all_data:
            import routers.hotspots as rh
            if rh.latest_results:
                counts = {}
                risks = {}
                frps = []
                for item in rh.latest_results:
                    cls = item.classification
                    cls_val = cls.classification.value if hasattr(cls.classification, "value") else str(cls.classification)
                    risk_val = cls.risk_level or "LOW"
                    counts[cls_val] = counts.get(cls_val, 0) + 1
                    risks[risk_val] = risks.get(risk_val, 0) + 1
                    if item.hotspot.frp is not None:
                        frps.append(float(item.hotspot.frp))
                
                total = len(rh.latest_results)
                return {
                    "total_hotspots": total,
                    "total_firms_observations": total,
                    "ai_classified": total,
                    "ai_pending": 0,
                    "classification_counts": counts,
                    "risk_level_counts": risks,
                    "frp_statistics": {
                        "min": round(min(frps), 2) if frps else 0,
                        "max": round(max(frps), 2) if frps else 0,
                        "avg": round(sum(frps) / len(frps), 2) if frps else 0
                    }
                }
            return {
                "total_hotspots": 0,
                "total_firms_observations": 0,
                "ai_classified": 0,
                "ai_pending": 0,
                "classification_counts": {},
                "risk_level_counts": {},
                "frp_statistics": {"min": 0, "max": 0, "avg": 0}
            }
        
        counts = {}
        risks = {}
        frps = []
        ai_classified = 0
        ai_pending = 0
        
        for r in all_data:
            lat = float(r.get("latitude", 0))
            lon = float(r.get("longitude", 0))
            if not point_in_india(lat, lon):
                continue

            frp = r.get("frp")
            if frp is not None:
                frps.append(float(frp))
            
            class_data = r.get("classifications", [])
            has_valid_classification = False
            
            if class_data and len(class_data) > 0:
                # Sort by created_at desc and take the latest
                class_data.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                latest = class_data[0]
                clf = latest.get("classification", "UNKNOWN")
                risk = latest.get("risk_level", "LOW")
                
                if clf and clf.upper() != "PENDING":
                    counts[clf] = counts.get(clf, 0) + 1
                    risks[risk] = risks.get(risk, 0) + 1
                    ai_classified += 1
                    has_valid_classification = True
            
            if not has_valid_classification:
                ai_pending += 1
        
        total = ai_classified + ai_pending
        
        return {
            "total_hotspots": total,
            "total_firms_observations": total,
            "ai_classified": ai_classified,
            "ai_pending": ai_pending,
            "classification_counts": counts,
            "risk_level_counts": risks,
            "frp_statistics": {
                "min": round(min(frps), 2) if frps else 0,
                "max": round(max(frps), 2) if frps else 0,
                "avg": round(sum(frps) / len(frps), 2) if frps else 0
            }
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not load analytics summary: {e}")
        return {
            "total_hotspots": 0,
            "total_firms_observations": 0,
            "ai_classified": 0,
            "ai_pending": 0,
            "classification_counts": {},
            "risk_level_counts": {},
            "frp_statistics": {"min": 0, "max": 0, "avg": 0}
        }
