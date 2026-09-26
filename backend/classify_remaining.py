"""Classify the remaining unclassified hotspots in the database."""
import sys, os, asyncio, logging

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("classify_remaining")

from db.supabase_client import supabase_service
from services.classifier import classify_hotspots, persist_classification
from models.hotspot import FIRMSHotspot


async def main():
    # Find hotspots without classifications
    all_hotspots = supabase_service.table("hotspots").select("*, classifications(id)").execute().data or []
    
    unclassified = [h for h in all_hotspots if not h.get("classifications") or len(h["classifications"]) == 0]
    print(f"Total hotspots: {len(all_hotspots)}")
    print(f"Unclassified: {len(unclassified)}")
    
    if not unclassified:
        print("All hotspots are already classified!")
        return
    
    # Convert DB records to FIRMSHotspot models
    hotspot_models = []
    for r in unclassified:
        try:
            h = FIRMSHotspot(
                latitude=r["latitude"],
                longitude=r["longitude"],
                brightness=r.get("brightness"),
                scan=r.get("scan"),
                track=r.get("track"),
                bright_t31=r.get("bright_t31"),
                acq_date=r.get("acq_date"),
                acq_time=r.get("acq_time"),
                satellite=r.get("satellite"),
                instrument=r.get("instrument"),
                confidence=r.get("confidence"),
                frp=r.get("frp"),
                daynight=r.get("daynight"),
            )
            setattr(h, "_db_id", r["id"])
            hotspot_models.append(h)
        except Exception as e:
            logger.warning(f"Skipping hotspot {r.get('id')}: {e}")
    
    print(f"\nClassifying {len(hotspot_models)} remaining hotspots...")
    classified = await classify_hotspots(hotspot_models)
    
    print(f"Classified {len(classified)}. Persisting to database...")
    for c in classified:
        try:
            persist_classification(c)
        except Exception as e:
            logger.warning(f"Persist error: {e}")
    
    # Final stats
    total_cls = supabase_service.table("classifications").select("id", count="exact").execute()
    print(f"\nDone! Total classifications now: {total_cls.count or len(total_cls.data or [])}")


if __name__ == "__main__":
    asyncio.run(main())
