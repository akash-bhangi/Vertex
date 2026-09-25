import {
  ClassifiedHotspot,
  FIRMSHotspot,
  HealthResponse,
  SystemStatus,
  ClassificationType,
} from '@/types';


/*
 * =========================================================
 * API CONFIG
 * =========================================================
 */

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined' ? '' : 'http://127.0.0.1:8000');


/*
 * =========================================================
 * HOTSPOT ID HELPERS
 * =========================================================
 *
 * The UI displays IDs such as:
 *
 *   VTX-506
 *
 * But the backend/Supabase hotspot table uses:
 *
 *   506
 *
 * Keep the VTX ID in the frontend, but strip the VTX-
 * prefix whenever calling backend endpoints that expect
 * the database hotspot ID.
 */

function getDatabaseHotspotId(
  hotspotId: string | number
): string {

  const value =
    String(hotspotId).trim();


  /*
   * VTX-506 -> 506
   */

  if (
    value.toUpperCase().startsWith('VTX-')
  ) {

    return value.substring(4);
  }


  /*
   * Already a database ID.
   */

  return value;
}


/*
 * =========================================================
 * HEALTH
 * =========================================================
 */

export async function fetchHealth(): Promise<HealthResponse> {

  const res =
    await fetch(
      `${API_URL}/api/v1/health`
    );


  if (!res.ok) {

    throw new Error(
      'Failed to fetch health status'
    );
  }


  return res.json();
}


/*
 * =========================================================
 * SYSTEM STATUS
 * =========================================================
 */

export async function fetchSystemStatus(): Promise<SystemStatus> {

  const res =
    await fetch(
      `${API_URL}/api/v1/health`
    );


  if (!res.ok) {

    throw new Error(
      'Failed to fetch system status'
    );
  }


  return res.json();
}


/*
 * =========================================================
 * ANALYTICS
 * =========================================================
 */

export async function fetchAnalyticsSummary(): Promise<any> {

  const res =
    await fetch(
      `${API_URL}/api/v1/analytics/summary`
    );


  if (!res.ok) {

    if (res.status === 503) {

      throw new Error(
        '503: Database connection failed'
      );
    }


    throw new Error(
      'Failed to fetch analytics summary'
    );
  }


  return res.json();
}


/*
 * =========================================================
 * CLASSIFICATION ENUM MAPPING
 * =========================================================
 */

function mapClassificationEnum(
  value: string | undefined
): ClassificationType {

  if (!value) {

    return ClassificationType.UNCLASSIFIED;
  }


  const v =
    value.toUpperCase();


  if (
    v === 'INDUSTRIAL_FIRE' ||
    v === 'INDUSTRIAL_FLARE'
  ) {

    return ClassificationType.INDUSTRIAL_FIRE;
  }


  if (
    v === 'PERSISTENT_INDUSTRIAL_SOURCE'
  ) {

    return ClassificationType.PERSISTENT_INDUSTRIAL_SOURCE;
  }


  if (
    v === 'GAS_FLARE'
  ) {

    return ClassificationType.GAS_FLARE;
  }


  if (
    v === 'WILDFIRE_FOREST_FIRE' ||
    v === 'VEGETATION_FIRE'
  ) {

    return ClassificationType.WILDFIRE_FOREST_FIRE;
  }


  if (
    v === 'AGRICULTURAL_BURN'
  ) {

    return ClassificationType.AGRICULTURAL_BURN;
  }


  if (
    v === 'MINING_THERMAL_ACTIVITY'
  ) {

    return ClassificationType.MINING_THERMAL_ACTIVITY;
  }


  if (
    v === 'OTHER_THERMAL_ANOMALY'
  ) {

    return ClassificationType.OTHER_THERMAL_ANOMALY;
  }


  if (
    v === 'UNCLASSIFIED'
  ) {

    return ClassificationType.UNCLASSIFIED;
  }


  return ClassificationType.UNKNOWN_UNCERTAIN;
}


/*
 * =========================================================
 * FETCH CLASSIFIED HOTSPOTS
 * =========================================================
 */

export async function fetchClassifiedHotspots(
  country = 'IND',
  days = 1
): Promise<ClassifiedHotspot[]> {
  try {
    const res =
      await fetch(
      `${API_URL}/api/v1/hotspots/classified?country=${country}&days=${days}`
    );


  if (!res.ok) {

    if (res.status === 503) {

      throw new Error(
        'Database connection failed'
      );
    }


    throw new Error(
      'Failed to fetch classified hotspots'
    );
  }


  const geojson =
    await res.json();


  /*
   * Backend returns:
   *
   * FeatureCollection
   */

  if (
    geojson?.type === 'FeatureCollection' &&
    Array.isArray(geojson.features)
  ) {

    return geojson.features.map(
      (
        feature: any,
        index: number
      ) => {

        const props =
          feature.properties || {};


        const coords =
          feature.geometry?.coordinates ||
          [0, 0];


        const hotspot =
          props.hotspot || {};


        const classification =
          props.classification || {};


        const osmCtx =
          props.osm_context || {};


        /*
         * Preserve the backend feature ID.
         *
         * This is normally something like:
         *
         *   VTX-506
         */

        const frontendId =
          feature.id ||
          `hotspot-${index}`;


        return {

          /*
           * UI ID
           */

          id: frontendId,


          /*
           * FIRMS hotspot information
           */

          hotspot: {

            /*
             * Keep the real backend ID when available.
             *
             * Otherwise fall back to a generated value.
             */

            id:
              hotspot.id ??
              getDatabaseHotspotId(
                frontendId
              ),


            latitude:
              coords[1],


            longitude:
              coords[0],


            brightness:
              hotspot.brightness ??
              hotspot.bright_ti4 ??
              0,


            scan:
              hotspot.scan ??
              0,


            track:
              hotspot.track ??
              0,


            acq_date:
              hotspot.acq_date ||
              '',


            acq_time:
              hotspot.acq_time ||
              '',


            satellite:
              hotspot.satellite ||
              '',


            instrument:
              hotspot.instrument ||
              '',


            confidence:
              hotspot.confidence ??
              'nominal',


            version:
              hotspot.version ||
              '',


            bright_t31:
              hotspot.bright_t31 ??
              hotspot.bright_ti5 ??
              0,


            frp:
              hotspot.frp ??
              0,


            daynight:
              hotspot.daynight ||
              'D',
          },


          /*
           * Classification
           */

          classification: {

            classification:
              mapClassificationEnum(
                classification.classification
              ),


            confidence_score:
              classification.confidence_score ||
              0,


            explanation:
              classification.explanation ||
              'No explanation available',


            evidence:
              classification.evidence ||
              [],


            risk_score:
              classification.risk_score ||
              0,


            risk_level:
              classification.risk_level ||
              'LOW',
          },


          /*
           * OSM context
           */

          context: {

            nearby_facilities:
              osmCtx.nearby_facilities ||
              [],


            nearest_facility_distance:
              osmCtx.nearest_facility_distance ??
              null,


            nearest_facility_type:
              osmCtx.nearest_facility_type ??
              null,


            facility_count_in_radius:
              osmCtx.facility_count_in_radius ??
              0,


            land_use_context:
              osmCtx.land_use_context ||
              [],


            osm_source:
              osmCtx.osm_source ??
              'PENDING',


            queried_at:
              osmCtx.queried_at ??
              null,
          },

        } as unknown as ClassifiedHotspot;
      }
    );
  }


    return [];
  } catch (err: any) {
    if (
      err?.name === 'AbortError' ||
      String(err?.message || '').includes('aborted')
    ) {
      return [];
    }
    throw err;
  }
}


/*
 * =========================================================
 * REALTIME FIRMS HOTSPOTS
 * =========================================================
 */

export async function fetchRealtimeHotspots(
  country = 'IND',
  days = 1
): Promise<FIRMSHotspot[]> {

  const res =
    await fetch(
      `${API_URL}/api/v1/firms/realtime?country=${country}&days=${days}`
    );


  if (!res.ok) {

    throw new Error(
      'Failed to fetch real-time hotspots'
    );
  }


  return res.json();
}


/*
 * =========================================================
 * INDUSTRIAL CONTEXT
 * =========================================================
 */

export async function fetchIndustrialZones(
  lat: number,
  lon: number,
  radius = 5000
): Promise<any> {

  const res =
    await fetch(
      `${API_URL}/api/v1/osm/industrial?lat=${lat}&lon=${lon}&radius=${radius}`
    );


  if (!res.ok) {

    throw new Error(
      'Failed to fetch industrial zones'
    );
  }


  return res.json();
}


/*
 * =========================================================
 * TOP-50 OSM ENRICHMENT
 * =========================================================
 *
 * Receives frontend IDs:
 *
 *   VTX-506
 *   VTX-505
 *   VTX-6
 *
 * Converts them to database IDs:
 *
 *   506
 *   505
 *   6
 *
 * Then sends those IDs to the backend.
 *
 * The backend performs:
 *
 *   Supabase cache HIT
 *        ↓
 *   return cached context
 *
 *   OR
 *
 *   cache MISS
 *        ↓
 *   Overpass
 *        ↓
 *   save Supabase
 */

export async function enrichTop50Hotspots(
  hotspots: ClassifiedHotspot[]
): Promise<any> {

  if (
    !hotspots ||
    hotspots.length === 0
  ) {

    return {
      requested: 0,
      processed: 0,
      successful: 0,
      failed: 0,
      results: [],
    };
  }


  /*
   * Select current highest-priority 50
   * based on FRP.
   */

  const top50 =
    [...hotspots]
      .sort(
        (a, b) => {

          const frpA =
            Number(
              a?.hotspot?.frp ??
              0
            );


          const frpB =
            Number(
              b?.hotspot?.frp ??
              0
            );


          return frpB - frpA;
        }
      )
      .slice(0, 50);


  /*
   * Convert UI IDs to database IDs.
   */

  const hotspotIds =
    top50
      .map(
        (hotspot) =>
          getDatabaseHotspotId(
            hotspot.id
          )
      )
      .filter(
        (id) =>
          id &&
          id !== 'undefined' &&
          id !== 'null' &&
          !id.startsWith('hotspot-')
      );


  if (
    hotspotIds.length === 0
  ) {

    console.warn(
      '[VERTEX] Top-50 enrichment skipped: no valid database hotspot IDs.'
    );


    return {
      requested: 0,
      processed: 0,
      successful: 0,
      failed: 0,
      results: [],
    };
  }


  console.log(
    `[VERTEX] Sending ${hotspotIds.length} hotspots for OSM enrichment`
  );


  try {

    const res =
      await fetch(
        `${API_URL}/api/v1/osm/enrich/top50`,
        {
          method: 'POST',

          headers: {
            'Content-Type':
              'application/json',
          },

          body:
            JSON.stringify(
              { hotspot_ids: hotspotIds }
            ),
        }
      );


    if (!res.ok) {

      const errorText =
        await res.text();


      throw new Error(
        `Top-50 OSM enrichment failed (${res.status}): ${errorText}`
      );
    }


    const result =
      await res.json();


    console.log(
      '[VERTEX] Top-50 OSM enrichment complete:',
      result
    );


    return result;

  } catch (error) {

    console.warn(
      '[VERTEX] Top-50 OSM enrichment request failed:',
      error
    );


    /*
     * Don't kill the entire dashboard if OSM
     * enrichment has a temporary failure.
     */

    return {
      requested:
        hotspotIds.length,

      processed: 0,

      successful: 0,

      failed:
        hotspotIds.length,

      results: [],

      error:
        error instanceof Error
          ? error.message
          : String(error),
    };
  }
}


/*
 * =========================================================
 * FORCE ENRICH SINGLE HOTSPOT
 * =========================================================
 *
 * This is used by the manual refresh button.
 *
 * Example:
 *
 *   VTX-506
 *
 * becomes:
 *
 *   506
 *
 * before calling the backend.
 */

export async function forceEnrichHotspot(
  hotspotId: string
): Promise<any> {

  const databaseHotspotId =
    getDatabaseHotspotId(
      hotspotId
    );


  const res =
    await fetch(
      `${API_URL}/api/v1/osm/enrich/${encodeURIComponent(databaseHotspotId)}?force=true`,
      {
        method: 'POST',
      }
    );


  if (!res.ok) {

    const errorText =
      await res.text();


    throw new Error(
      `Failed to force enrich hotspot (${res.status}): ${errorText}`
    );
  }


  return res.json();
}