"""
VERTEX Database Repopulation and Reclassification Script

This script clears the old corrupted records (NULL brightness, fake 950m distance,
falsely classified persistent industrial sources) and repopulates the database
with fresh FIRMS satellite data and accurate AI classifications.

Usage:
    python repopulate_and_reclassify.py --fresh      # Delete old data & repopulate fresh (Recommended)
    python repopulate_and_reclassify.py --backfill   # In-place update of existing hotspots
"""

import sys
import os
import argparse
import asyncio
import logging
from collections import Counter

# Fix Windows console encoding
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.supabase_client import supabase_service
from services.firms_service import fetch_realtime_hotspots, point_in_india
from services.classifier import classify_and_store, classify_hotspots, persist_classification
from models.hotspot import FIRMSHotspot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("repopulate")


def get_current_stats():
    """Display current database state."""
    try:
        hotspots = supabase_service.table("hotspots").select("id, brightness").execute().data or []
        classifications = supabase_service.table("classifications").select("id, classification").execute().data or []
        
        null_brightness = sum(1 for h in hotspots if h.get("brightness") is None)
        valid_brightness = sum(1 for h in hotspots if h.get("brightness") is not None)
        class_counts = Counter(c.get("classification") for c in classifications)
        
        print("\n" + "=" * 60)
        print("CURRENT DATABASE STATUS:")
        print(f"  * Total Hotspots in DB: {len(hotspots)}")
        print(f"    - With Valid Brightness: {valid_brightness}")
        print(f"    - With NULL Brightness (shows 0.0 K): {null_brightness}")
        print(f"  * Total Classifications: {len(classifications)}")
        print("  * Classification Breakdown:")
        for cls_name, count in class_counts.most_common():
            print(f"    - {cls_name}: {count}")
        print("=" * 60 + "\n")
        return len(hotspots), null_brightness
    except Exception as e:
        logger.error(f"Error fetching current stats: {e}")
        return 0, 0


def clean_database():
    """Delete old corrupted hotspots, classifications, and stale caches."""
    print("Step 1: Cleaning old corrupted records...")
    
    # 1. Clear classifications
    try:
        print("  -> Clearing 'classifications' table...")
        supabase_service.table("classifications").delete().gt("id", 0).execute()
        print("  [OK] Cleared classifications.")
    except Exception as e:
        logger.warning(f"Error clearing classifications: {e}")

    # 2. Clear hotspots
    try:
        print("  -> Clearing 'hotspots' table...")
        supabase_service.table("hotspots").delete().gt("id", 0).execute()
        print("  [OK] Cleared hotspots.")
    except Exception as e:
        logger.warning(f"Error clearing hotspots: {e}")

    # 3. Clear osm_context_cache
    try:
        print("  -> Clearing stale 'osm_context_cache' entries...")
        supabase_service.table("osm_context_cache").delete().gt("id", 0).execute()
        print("  [OK] Cleared osm_context_cache.")
    except Exception as e:
        logger.warning(f"Error clearing osm_context_cache: {e}")

    print("  [OK] Old records cleared.\n")


async def repopulate_fresh(days: int = 1):
    """Fetch fresh FIRMS data and run fixed classification pipeline."""
    clean_database()
    
    print(f"Step 2: Fetching live NASA FIRMS satellite data for India (past {days} day(s))...")
    hotspots = await fetch_realtime_hotspots(country="IND", days=days)
    print(f"  [OK] Fetched {len(hotspots)} active hotspots inside India.")
    
    if not hotspots:
        print("No hotspots found from FIRMS API. Check FIRMS_MAP_KEY.")
        return

    print("\nStep 3: Ingesting hotspots with full telemetry (Brightness, Scan, Track, Bright_T31)...")
    insert_payload = []
    for h in hotspots:
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
        insert_payload.append(payload)

    inserted_hotspots = []
    # Insert in chunks of 50 for speed and safety
    chunk_size = 50
    for i in range(0, len(insert_payload), chunk_size):
        chunk = insert_payload[i : i + chunk_size]
        try:
            res = supabase_service.table("hotspots").insert(chunk).execute()
            if res.data:
                for j, db_row in enumerate(res.data):
                    hs = hotspots[i + j]
                    setattr(hs, "_db_id", db_row["id"])
                    inserted_hotspots.append(hs)
        except Exception as err:
            logger.warning(f"Chunk {i // chunk_size + 1} insert error: {err}")
            # Fallback to single-item insert for this chunk
            for j, single_row in enumerate(chunk):
                try:
                    res = supabase_service.table("hotspots").insert(single_row).execute()
                    if res.data:
                        hs = hotspots[i + j]
                        setattr(hs, "_db_id", res.data[0]["id"])
                        inserted_hotspots.append(hs)
                except Exception as row_err:
                    logger.debug(f"Row insert skipped: {row_err}")

    print(f"  [OK] Successfully stored {len(inserted_hotspots)} hotspots in database.")

    # Sort by FRP for classification priority
    inserted_hotspots.sort(key=lambda x: x.frp or 0.0, reverse=True)
    top_candidates = inserted_hotspots
    
    print(f"\nStep 4: Classifying all {len(top_candidates)} thermal events...")
    print("  (Using fixed rules: Wildfire >= 15 MW, true facility proximity, forest/wood detection, Gemini 3.5 Flash Lite)")
    
    classified = await classify_hotspots(top_candidates)
    
    print(f"  [OK] Classification complete. Persisting {len(classified)} classifications to database...")
    for c in classified:
        persist_classification(c)

    print("\n" + "=" * 60)
    print("REPOPULATION COMPLETE!")
    get_current_stats()


async def backfill_existing():
    """In-place backfill of brightness and reclassification of existing database records."""
    print("Fetching live FIRMS data for matching...")
    live_hotspots = await fetch_realtime_hotspots(country="IND", days=2)
    
    live_lookup = {}
    for h in live_hotspots:
        key = (round(float(h.latitude), 4), round(float(h.longitude), 4), str(h.acq_date), str(h.acq_time).zfill(4))
        live_lookup[key] = h

    db_hotspots = supabase_service.table("hotspots").select("*").execute().data or []
    print(f"Found {len(db_hotspots)} hotspots in DB to examine.")
    
    updated_brightness = 0
    matched_for_reclass = []
    
    for row in db_hotspots:
        key = (round(float(row["latitude"]), 4), round(float(row["longitude"]), 4), str(row.get("acq_date")), str(row.get("acq_time", "")).zfill(4))
        matched = live_lookup.get(key)
        
        if matched:
            update_data = {
                "brightness": matched.brightness or matched.bright_ti4,
                "scan": matched.scan,
                "track": matched.track,
                "bright_t31": matched.bright_t31,
            }
            supabase_service.table("hotspots").update(update_data).eq("id", row["id"]).execute()
            updated_brightness += 1
            
            hs = matched
            setattr(hs, "_db_id", row["id"])
            matched_for_reclass.append(hs)

    print(f"Updated brightness for {updated_brightness} hotspots.")
    
    if matched_for_reclass:
        matched_for_reclass.sort(key=lambda x: x.frp or 0.0, reverse=True)
        top_to_reclass = matched_for_reclass
        print(f"Reclassifying all {len(top_to_reclass)} matched hotspots...")
        reclassified = await classify_hotspots(top_to_reclass)
        for c in reclassified:
            persist_classification(c)
        print("Reclassification complete.")

    get_current_stats()


def main():
    parser = argparse.ArgumentParser(description="VERTEX Repopulate & Reclassify Tool")
    parser.add_argument("--fresh", action="store_true", help="Wipe old corrupted records and repopulate fresh (Recommended)")
    parser.add_argument("--backfill", action="store_true", help="Backfill brightness on existing records without deleting")
    parser.add_argument("--days", type=int, default=1, help="Number of days of FIRMS data to fetch (1 or 2)")
    args = parser.parse_args()

    get_current_stats()

    if args.backfill:
        asyncio.run(backfill_existing())
    else:
        # Default to fresh repopulation
        asyncio.run(repopulate_fresh(days=args.days))


if __name__ == "__main__":
    main()
