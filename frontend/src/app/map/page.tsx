'use client';

import { useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';

import {
  ClassifiedHotspot,
  ClassificationType,
} from '@/types';

import { Sidebar } from '@/components/layout/Sidebar';
import { RightPanel } from '@/components/layout/RightPanel';
import { BottomTicker } from '@/components/layout/BottomTicker';

import {
  INDIA_CENTER,
  INDIA_ZOOM,
} from '@/lib/constants';

import { useGlobalState } from '@/lib/GlobalStateContext';
import { useVertexUser } from '@/lib/auth-session';
import { AuthRequiredDialog } from '@/components/auth/AuthRequiredDialog';

const MapView = dynamic(
  () =>
    import('@/components/map/MapView').then(
      (mod) => mod.MapView
    ),
  {
    ssr: false,
  }
);

interface FilterState {
  classifications: ClassificationType[];
  minFrp: number;
  maxFrp: number;
  minConfidence: number;
  riskLevels: string[];
}

function MapWorkspace() {
  const {
    hotspots,
    mapHotspots,
    streamFilter,
    loading,
    error,
    selectedHotspot,
    setSelectedHotspot,
    minConfidenceDisplay,
    strictRiskFiltering,
  } = useGlobalState();

  /*
   * =========================================================
   * FILTERS
   * =========================================================
   *
   * These filters apply to the classified / priority hotspot
   * stream used by the sidebar and dashboard controls.
   *
   * The map itself is handled by MapView, which now consumes
   * the complete current FIRMS observation stream through
   * GlobalStateContext.
   */

  const [filters, setFilters] = useState<FilterState>({
    classifications: [],
    minFrp: 0,
    maxFrp: 1000,
    minConfidence: 0,
    riskLevels: [],
  });

  /*
   * =========================================================
   * FILTER HOTSPOTS
   * =========================================================
   */

  /*
   * =========================================================
   * MERGE CLASSIFICATION DATA INTO MAP OBSERVATIONS
   * =========================================================
   *
   * The FIRMS map stream contains every current observation,
   * while the classified stream contains the AI/enrichment data.
   *
   * Match them by the FIRMS observation identity (coordinates,
   * acquisition date/time, satellite) so map markers inherit
   * their real classification, confidence, risk and context.
   */
  const hotspotIdentity = (h: ClassifiedHotspot) => {
    const lat = Number(h?.hotspot?.latitude);
    const lon = Number(h?.hotspot?.longitude);
    const date = String(h?.hotspot?.acq_date ?? '');
    const timeRaw = String(h?.hotspot?.acq_time ?? '');
    const time = timeRaw.padStart(4, '0');
    const satellite = String(h?.hotspot?.satellite ?? '');

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return '';
    }

    return `${lat.toFixed(5)}|${lon.toFixed(5)}|${date}|${time}|${satellite}`;
  };

  const classifiedByIdentity = useMemo(() => {
    const index = new Map<string, ClassifiedHotspot>();

    for (const hotspot of hotspots) {
      const key = hotspotIdentity(hotspot);
      if (key) {
        index.set(key, hotspot);
      }
    }

    return index;
  }, [hotspots]);

  const mergedMapHotspots = useMemo(() => {
    // 1. All classified hotspots from Supabase (authoritative catalog)
    const classifiedList = Array.isArray(hotspots) ? hotspots : [];
    const knownIds = new Set<string>();
    const knownCoords = new Set<string>();

    for (const h of classifiedList) {
      if (h.id) {
        knownIds.add(String(h.id));
        knownIds.add(String(h.id).replace(/^vtx-/i, ''));
      }
      const lat = Number(h?.hotspot?.latitude);
      const lon = Number(h?.hotspot?.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        knownCoords.add(`${lat.toFixed(3)}|${lon.toFixed(3)}`);
      }
    }

    const merged = [...classifiedList];

    // 2. Include any live FIRMS observations that are not yet classified
    const mapList = Array.isArray(mapHotspots) ? mapHotspots : [];
    for (const raw of mapList) {
      const rawId = String(raw.id);
      const rawDbId = String(raw?.hotspot?.id ?? '');
      if (knownIds.has(rawId) || knownIds.has(rawDbId)) {
        continue;
      }
      const lat = Number(raw?.hotspot?.latitude);
      const lon = Number(raw?.hotspot?.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        const coordKey = `${lat.toFixed(3)}|${lon.toFixed(3)}`;
        if (knownCoords.has(coordKey)) {
          continue;
        }
      }
      merged.push(raw);
    }

    return merged;
  }, [hotspots, mapHotspots]);

  /*
   * =========================================================
   * FILTER ONE UNIFIED DATASET
   * =========================================================
   *
   * The exact same dataset is rendered in the Sidebar and MapView.
   */
  const matchesFilters = (h: ClassifiedHotspot) => {
    const classification =
      h?.classification?.classification ??
      ClassificationType.UNCLASSIFIED;

    const frp = Number(h?.hotspot?.frp ?? 0);
    const confidence = Number(
      h?.classification?.confidence_score ?? 0
    );
    const risk = String(
      h?.classification?.risk_level ?? ''
    ).toUpperCase();

    // FRP Range applies to all observations
    if (
      frp < filters.minFrp ||
      frp > filters.maxFrp
    ) {
      return false;
    }

    // Determine if this is an unclassified / pending raw satellite detection
    const isPending =
      !h?.classification ||
      !h.classification.classification ||
      h.classification.classification === ClassificationType.UNCLASSIFIED;

    // Raw satellite observations appear on the map unless explicitly filtered
    if (isPending) {
      if (
        filters.classifications.length > 0 &&
        !filters.classifications.includes(ClassificationType.UNCLASSIFIED)
      ) {
        return false;
      }
      return true;
    }

    // Classification filter for AI-classified events
    if (
      filters.classifications.length > 0 &&
      !filters.classifications.includes(classification)
    ) {
      return false;
    }

    // Risk level filter for AI-classified events (from Filter tab)
    if (
      filters.riskLevels.length > 0 &&
      !filters.riskLevels.includes(risk)
    ) {
      return false;
    }

    // Confidence threshold from Filter tab
    if (filters.minConfidence > 0 && confidence < filters.minConfidence) {
      return false;
    }

    return true;
  };

  const displayHotspots = useMemo(() => {
    let list = mergedMapHotspots;

    if (streamFilter === 'CLASSIFIED') {
      list = list.filter(
        (h) =>
          h.classification?.classification &&
          h.classification.classification !== ClassificationType.UNCLASSIFIED
      );
    } else if (streamFilter === 'PENDING') {
      list = list.filter(
        (h) =>
          !h.classification?.classification ||
          h.classification.classification === ClassificationType.UNCLASSIFIED
      );
    }

    return list.filter(matchesFilters);
  }, [mergedMapHotspots, streamFilter, filters]);


  /*
   * =========================================================
   * KEEP SELECTED HOTSPOT IN SYNC
   * =========================================================
   *
   * Do not maintain a second OSM-context store here.
   *
   * The selected hotspot already comes from GlobalStateContext,
   * while fresh OSM enrichment is handled by RightPanel and
   * persisted by the backend/Supabase layer.
   */

  const persistedSelectedHotspot = useMemo(() => {
    if (!selectedHotspot) {
      return null;
    }

    /*
     * If the selected hotspot still exists in the current
     * classified stream, use the latest object from that stream.
     *
     * This prevents stale classification/hotspot data from
     * remaining selected after a refresh.
     */

    const currentHotspot =
      displayHotspots.find(
        (hotspot) =>
          String(hotspot.id) === String(selectedHotspot.id)
      ) ??
      hotspots.find(
        (hotspot) =>
          String(hotspot.id) === String(selectedHotspot.id)
      );

    return currentHotspot ?? selectedHotspot;
  }, [selectedHotspot, hotspots, displayHotspots]);

  /*
   * =========================================================
   * SELECT HOTSPOT
   * =========================================================
   *
   * MapView may call this with null when the map selection
   * is cleared.
   *
   * Always handle null safely.
   */

  const handleSelectHotspot = (
    hotspot: ClassifiedHotspot | null
  ) => {
    if (!hotspot) {
      setSelectedHotspot(null);
      return;
    }

    setSelectedHotspot(hotspot);
  };

  /*
   * =========================================================
   * RENDER
   * =========================================================
   */

  return (
    <>
      <div
        className="
          flex-1
          relative
          w-full
          h-[calc(100vh-72px)]
          overflow-hidden
          mb-[32px]
        "
      >
        {/* =================================================
            SIDEBAR
            ================================================= */}

        <Sidebar
          hotspots={displayHotspots}
          selectedId={
            persistedSelectedHotspot?.id
          }
          onSelect={handleSelectHotspot}
          onFiltersChange={setFilters}
        />

        {/* =================================================
            MAIN MAP
            ================================================= */}

        <main
          className="
            absolute
            inset-0
            z-0
            bg-surface-dim
            ml-[300px]
            mr-[340px]
            overflow-hidden
          "
        >
          {/* ===============================================
              LOADING
              =============================================== */}

          {loading ? (
            <div
              className="
                w-full
                h-full
                flex
                flex-col
                items-center
                justify-center
                bg-surface-dim
                text-secondary
                space-y-4
              "
            >
              <span
                className="
                  material-symbols-outlined
                  text-4xl
                  animate-spin
                "
              >
                refresh
              </span>

              <span
                className="
                  font-mono
                  text-sm
                  tracking-widest
                  uppercase
                "
              >
                Initializing Geospatial Telemetry...
              </span>
            </div>
          ) : (
            /* =============================================
               MAP
               ============================================= */

            <div
              className="
                w-full
                h-full
                relative
              "
            >
              {error && (
                <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-black/80 border border-amber-500/60 px-4 py-2 rounded-lg backdrop-blur-md shadow-2xl flex items-center gap-2 text-amber-200 text-xs">
                  <span className="material-symbols-outlined text-sm text-amber-400">info</span>
                  <span>{error}</span>
                </div>
              )}
              <MapView
                /*
                 * Single authoritative map dataset.
                 *
                 * It has already been merged with the latest
                 * classification/context data and passed through
                 * every active filter.
                 */
                hotspots={displayHotspots}
                selectedHotspot={
                  persistedSelectedHotspot
                }
                onSelectHotspot={
                  handleSelectHotspot
                }
                center={INDIA_CENTER}
                zoom={INDIA_ZOOM}
              />
            </div>
          )}
        </main>

        {/* =================================================
            RIGHT PANEL
            ================================================= */}

        <RightPanel
          hotspot={persistedSelectedHotspot}
        />
      </div>

      {/* ===================================================
          BOTTOM TICKER
          =================================================== */}

      <BottomTicker
        hotspots={hotspots}
      />
    </>
  );
}

export default function DashboardPage() {
  const { user, ready } = useVertexUser();

  if (!ready) {
    return <div className="flex-1 bg-surface-dim" />;
  }

  return user ? <MapWorkspace /> : <AuthRequiredDialog />;
}
