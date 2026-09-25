'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from 'react';

import {
  ClassifiedHotspot,
  ClassificationType,
} from '@/types';

import {
  fetchClassifiedHotspots,
  fetchAnalyticsSummary,
  enrichTop50Hotspots,
} from '@/lib/api';

import {
  DEMO_HOTSPOTS,
  generateDemoSummary,
} from './demo-data';

import {
  INDIA_CENTER,
  INDIA_ZOOM,
} from './constants';

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined' ? '' : 'http://127.0.0.1:8000');

// Suppress harmless browser AbortErrors caused by component unmounting,
// rapid state updates, or MapLibre GL tile cancellation.
if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    const name = reason?.name || reason?.constructor?.name;
    const message = String(reason?.message || reason || '');
    if (
      name === 'AbortError' ||
      message.includes('signal is aborted') ||
      message.includes('aborted without reason') ||
      message.includes('The user aborted a request')
    ) {
      event.preventDefault();
    }
  });
}


/*
 * =========================================================
 * GLOBAL STATE INTERFACE
 * =========================================================
 */

interface GlobalState {
  hotspots: ClassifiedHotspot[];
  mapHotspots: ClassifiedHotspot[];
  analyticsSummary: any;
  loading: boolean;
  error: string | null;
  isDemoMode: boolean;
  selectedHotspot: ClassifiedHotspot | null;

  setSelectedHotspot: (
    hotspot: ClassifiedHotspot | null
  ) => void;

  mapStyle: string;

  setMapStyle: (
    style: string
  ) => void;

  streamFilter: string;

  setStreamFilter: (
    filter: string
  ) => void;

  mapCenter: [number, number];

  setMapCenter: (
    center: [number, number]
  ) => void;

  mapZoom: number;

  setMapZoom: (
    zoom: number
  ) => void;

  refreshData: () => Promise<void>;

  autoRefreshInterval: string;
  setAutoRefreshInterval: (interval: string) => void;
  minConfidenceDisplay: number;
  setMinConfidenceDisplay: (val: number) => void;
  strictRiskFiltering: boolean;
  setStrictRiskFiltering: (enabled: boolean) => void;
  criticalNotificationsEnabled: boolean;
  setCriticalNotificationsEnabled: (enabled: boolean) => void;
}


/*
 * =========================================================
 * CONTEXT
 * =========================================================
 */

const GlobalStateContext =
  createContext<
    GlobalState | undefined
  >(undefined);


/*
 * =========================================================
 * OBSERVATION HELPERS
 * =========================================================
 *
 * Never rely only on frontend/backend IDs because the live
 * FIRMS stream and the persisted VERTEX stream can use
 * different IDs.
 *
 * FIRMS observation identity:
 *
 * latitude
 * longitude
 * acquisition date
 * acquisition time
 */

function normalizeAcqTime(
  value: unknown
): string {

  if (
    value === null ||
    value === undefined
  ) {
    return '';
  }

  const digits =
    String(value)
      .trim()
      .replace(/\D/g, '');

  if (!digits) {
    return '';
  }

  return digits
    .padStart(4, '0')
    .slice(-4);
}


function getObservationKey(
  hotspot: ClassifiedHotspot
): string {

  const h =
    hotspot.hotspot;

  const latitude =
    Number(h.latitude);

  const longitude =
    Number(h.longitude);

  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude)
  ) {
    return '';
  }

  const date =
    String(h.acq_date || '')
      .slice(0, 10);

  const time =
    normalizeAcqTime(
      h.acq_time
    );

  return [
    latitude.toFixed(6),
    longitude.toFixed(6),
    date,
    time,
  ].join('|');
}


/*
 * =========================================================
 * MERGE BACKEND CLASSIFICATIONS INTO LIVE MAP DATA
 * =========================================================
 *
 * currentMapData:
 *     every FIRMS observation currently visible
 *
 * classifiedData:
 *     persisted VERTEX observations containing:
 *       - Gemini classification
 *       - confidence
 *       - risk
 *       - OSM context
 *       - evidence
 *
 * The classified backend object wins whenever the same FIRMS
 * observation exists in both streams.
 */

function mergeClassifiedIntoMap(
  currentMapData: ClassifiedHotspot[],
  classifiedData: ClassifiedHotspot[]
): ClassifiedHotspot[] {
  if (!currentMapData || currentMapData.length === 0) {
    return classifiedData || [];
  }

  const classifiedByKey = new Map<string, ClassifiedHotspot>();
  const classifiedById = new Map<string, ClassifiedHotspot>();

  for (const classified of classifiedData) {
    const key = getObservationKey(classified);
    if (key) {
      classifiedByKey.set(key, classified);
    }
    if (classified.id) {
      classifiedById.set(String(classified.id), classified);
    }
  }

  const matchedClassifiedIds = new Set<string>();

  const mergedLive = currentMapData.map((liveHotspot) => {
    const key = getObservationKey(liveHotspot);
    const classified =
      (key ? classifiedByKey.get(key) : undefined) ||
      classifiedById.get(String(liveHotspot.id));

    if (!classified) {
      return liveHotspot;
    }

    matchedClassifiedIds.add(String(classified.id));

    return {
      ...liveHotspot,
      id: classified.id,
      hotspot: {
        ...liveHotspot.hotspot,
        ...classified.hotspot,
      },
      classification: classified.classification,
      context: classified.context,
    };
  });

  // Determine latest acquisition date present in currentMapData (today's active batch)
  let latestLiveDate = '';
  for (const item of currentMapData) {
    const d = String(item.hotspot?.acq_date || '').slice(0, 10);
    if (d && d > latestLiveDate) {
      latestLiveDate = d;
    }
  }

  const result = [...mergedLive];
  for (const classified of classifiedData) {
    if (!matchedClassifiedIds.has(String(classified.id))) {
      const classDate = String(classified.hotspot?.acq_date || '').slice(0, 10);
      // Only retain unmatched historical items if no new live date exists
      // or if the classified item is from the same active date batch.
      // Once new live detections arrive, old ones from yesterday retire automatically.
      if (!latestLiveDate || classDate >= latestLiveDate) {
        result.push(classified);
      }
    }
  }

  return result;
}


/*
 * =========================================================
 * PROVIDER
 * =========================================================
 */

export function GlobalStateProvider({
  children,
}: {
  children: ReactNode;
}) {

  /*
   * -------------------------------------------------------
   * HOTSPOTS
   * -------------------------------------------------------
   */

  const [
    hotspots,
    setHotspots,
  ] = useState<
    ClassifiedHotspot[]
  >([]);

  const [
    mapHotspots,
    setMapHotspots,
  ] = useState<
    ClassifiedHotspot[]
  >([]);


  /*
   * -------------------------------------------------------
   * ANALYTICS
   * -------------------------------------------------------
   */

  const [
    analyticsSummary,
    setAnalyticsSummary,
  ] = useState<any>(null);


  /*
   * -------------------------------------------------------
   * LOADING
   * -------------------------------------------------------
   */

  const [
    loading,
    setLoading,
  ] = useState(true);


  /*
   * -------------------------------------------------------
   * ERROR
   * -------------------------------------------------------
   */

  const [
    error,
    setError,
  ] = useState<
    string | null
  >(null);


  /*
   * -------------------------------------------------------
   * DEMO MODE
   * -------------------------------------------------------
   */

  const [
    isDemoMode,
    setIsDemoMode,
  ] = useState(false);


  /*
   * =======================================================
   * SELECTED HOTSPOT
   * =======================================================
   */

  const [
    selectedHotspot,
    setSelectedHotspotState,
  ] = useState<
    ClassifiedHotspot | null
  >(null);


  const setSelectedHotspot = (
    hotspot: ClassifiedHotspot | null
  ) => {

    setSelectedHotspotState(
      hotspot
    );


    if (
      typeof window !==
      'undefined'
    ) {

      if (hotspot) {

        localStorage.setItem(
          'vtx_selectedHotspot',
          hotspot.id
        );

      } else {

        localStorage.removeItem(
          'vtx_selectedHotspot'
        );
      }
    }
  };


  /*
   * =======================================================
   * MAP STYLE
   * =======================================================
   */

  const [
    mapStyle,
    setMapStyleState,
  ] = useState<string>(
    'OSM Light'
  );


  const setMapStyle = (
    style: string
  ) => {

    setMapStyleState(
      style
    );


    if (
      typeof window !==
      'undefined'
    ) {

      localStorage.setItem(
        'vtx_mapStyle',
        style
      );
    }
  };


  /*
   * =======================================================
   * STREAM FILTER
   * =======================================================
   */

  const [
    streamFilter,
    setStreamFilterState,
  ] = useState<string>(
    'ALL'
  );


  const setStreamFilter = (
    filter: string
  ) => {

    setStreamFilterState(
      filter
    );


    if (
      typeof window !==
      'undefined'
    ) {

      localStorage.setItem(
        'vtx_streamFilter',
        filter
      );
    }
  };


  /*
   * =======================================================
   * PLATFORM SETTINGS & CONTROLS
   * =======================================================
   */

  const [autoRefreshInterval, setAutoRefreshIntervalState] = useState<string>('30 Minutes');
  const [minConfidenceDisplay, setMinConfidenceDisplayState] = useState<number>(0.30);
  const [strictRiskFiltering, setStrictRiskFilteringState] = useState<boolean>(false);
  const [criticalNotificationsEnabled, setCriticalNotificationsEnabledState] = useState<boolean>(true);

  const savePlatformSettings = (partial: Record<string, any>) => {
    if (typeof window === 'undefined') return;
    try {
      const existing = JSON.parse(localStorage.getItem('vtx_platform_settings') || '{}');
      localStorage.setItem('vtx_platform_settings', JSON.stringify({ ...existing, ...partial }));
    } catch {}
  };

  const setAutoRefreshInterval = (interval: string) => {
    setAutoRefreshIntervalState(interval);
    savePlatformSettings({ autoRefreshInterval: interval });
  };

  const setMinConfidenceDisplay = (val: number) => {
    setMinConfidenceDisplayState(val);
    savePlatformSettings({ minConfidenceDisplay: val });
  };

  const setStrictRiskFiltering = (enabled: boolean) => {
    setStrictRiskFilteringState(enabled);
    savePlatformSettings({ strictRiskFiltering: enabled });
  };

  const setCriticalNotificationsEnabled = (enabled: boolean) => {
    setCriticalNotificationsEnabledState(enabled);
    savePlatformSettings({ criticalNotificationsEnabled: enabled });
  };


  /*
   * =======================================================
   * MAP CENTER
   * =======================================================
   */

  const [
    mapCenter,
    setMapCenterState,
  ] = useState<
    [number, number]
  >(INDIA_CENTER);


  const setMapCenter = (
    center: [number, number]
  ) => {

    setMapCenterState(
      center
    );


    if (
      typeof window !==
      'undefined'
    ) {

      localStorage.setItem(
        'vtx_mapCenter',
        JSON.stringify(center)
      );
    }
  };


  /*
   * =======================================================
   * MAP ZOOM
   * =======================================================
   */

  const [
    mapZoom,
    setMapZoomState,
  ] = useState<number>(
    INDIA_ZOOM
  );


  const setMapZoom = (
    zoom: number
  ) => {

    setMapZoomState(
      zoom
    );


    if (
      typeof window !==
      'undefined'
    ) {

      localStorage.setItem(
        'vtx_mapZoom',
        zoom.toString()
      );
    }
  };


  /*
   * =======================================================
   * RESTORE UI STATE
   * =======================================================
   */

  useEffect(() => {

    if (
      typeof window ===
      'undefined'
    ) {
      return;
    }


    const savedStyle =
      localStorage.getItem(
        'vtx_mapStyle'
      );

    if (savedStyle && savedStyle === 'Esri World Imagery (Satellite)') {
      setMapStyleState(savedStyle);
    } else {
      setMapStyleState('OSM Light');
    }


    const savedFilter =
      localStorage.getItem(
        'vtx_streamFilter'
      );

    if (savedFilter) {

      setStreamFilterState(
        savedFilter
      );
    }


    const savedCenter =
      localStorage.getItem(
        'vtx_mapCenter'
      );

    if (savedCenter) {

      try {

        const parsed =
          JSON.parse(
            savedCenter
          );

        if (
          Array.isArray(parsed) &&
          parsed.length === 2 &&
          typeof parsed[0] ===
            'number' &&
          typeof parsed[1] ===
            'number'
        ) {

          setMapCenterState(
            parsed as [
              number,
              number
            ]
          );
        }

      } catch {
        // Ignore malformed map center.
      }
    }


    const savedZoom =
      localStorage.getItem(
        'vtx_mapZoom'
      );

    if (savedZoom) {

      const parsedZoom =
        parseFloat(
          savedZoom
        );

      if (
        Number.isFinite(
          parsedZoom
        )
      ) {

        setMapZoomState(
          parsedZoom
        );
      }
    }

    try {
      const savedSettings = JSON.parse(localStorage.getItem('vtx_platform_settings') || '{}');
      if (savedSettings.autoRefreshInterval) setAutoRefreshIntervalState(savedSettings.autoRefreshInterval);
      if (typeof savedSettings.minConfidenceDisplay === 'number') setMinConfidenceDisplayState(savedSettings.minConfidenceDisplay);
      if (typeof savedSettings.strictRiskFiltering === 'boolean') setStrictRiskFilteringState(savedSettings.strictRiskFiltering);
      if (typeof savedSettings.criticalNotificationsEnabled === 'boolean') setCriticalNotificationsEnabledState(savedSettings.criticalNotificationsEnabled);
    } catch {}

  }, []);

  /*
   * =======================================================
   * AUTO-REFRESH TIMER
   * =======================================================
   */
  useEffect(() => {
    if (autoRefreshInterval === 'Manual Only' || autoRefreshInterval === 'manual') return;

    let ms = 30 * 60 * 1000;
    if (autoRefreshInterval === '30 Seconds') ms = 30 * 1000;
    else if (autoRefreshInterval === '1 Minute') ms = 60 * 1000;
    else if (autoRefreshInterval === '5 Minutes') ms = 5 * 60 * 1000;
    else if (autoRefreshInterval === '30 Minutes') ms = 30 * 60 * 1000;
    else if (autoRefreshInterval === '1 Hour') ms = 60 * 60 * 1000;
    else if (autoRefreshInterval === '6 Hours') ms = 6 * 60 * 60 * 1000;

    const timer = setInterval(() => {
      refreshData().catch(() => {});
    }, ms);

    return () => clearInterval(timer);
  }, [autoRefreshInterval]);


  /*
   * =======================================================
   * FETCH ALL CURRENT FIRMS OBSERVATIONS
   * =======================================================
   *
   * FIRMS provides the live map stream.
   *
   * These objects begin as PENDING only because FIRMS itself
   * does not contain Gemini classification.
   *
   * refreshData() immediately reconciles them with the
   * backend classified stream.
   */

  const fetchAllCurrentMapHotspots =
    async (): Promise<
      ClassifiedHotspot[]
    > => {
      try {
        const response =
          await fetch(
          `${API_BASE_URL}/api/v1/firms/realtime?country=IND&days=1`,
          {
            cache: 'no-store',
          }
        );


      if (!response.ok) {
        console.warn(
          `Failed to fetch current FIRMS observations (${response.status})`
        );
        return [];
      }

      const geojson =
        await response.json();

      if (
        geojson?.type !==
          'FeatureCollection' ||
        !Array.isArray(
          geojson.features
        )
      ) {
        return [];
      }


      return geojson.features

        .map(
          (
            feature: any,
            index: number
          ) => {

            const props =
              feature?.properties ??
              {};

            const coordinates =
              feature?.geometry
                ?.coordinates ??
              [0, 0];


            const longitude =
              Number(
                coordinates[0]
              );

            const latitude =
              Number(
                coordinates[1]
              );


            if (
              !Number.isFinite(
                longitude
              ) ||
              !Number.isFinite(
                latitude
              )
            ) {

              return null;
            }


            const id =
              String(
                feature?.id ??
                props?.id ??
                `firms-${index}`
              );


            return {

              id,

              hotspot: {

                id:
                  props?.id ??
                  id,

                latitude,

                longitude,

                brightness:
                  props?.brightness ??
                  props?.bright_ti4 ??
                  0,

                scan:
                  props?.scan ??
                  0,

                track:
                  props?.track ??
                  0,

                acq_date:
                  props?.acq_date ??
                  '',

                acq_time:
                  props?.acq_time ??
                  '',

                satellite:
                  props?.satellite ??
                  '',

                instrument:
                  props?.instrument ??
                  '',

                confidence:
                  props?.confidence ??
                  'nominal',

                version:
                  props?.version ??
                  '',

                bright_t31:
                  props?.bright_t31 ??
                  props?.bright_ti5 ??
                  0,

                frp:
                  Number(
                    props?.frp ??
                    0
                  ),

                daynight:
                  props?.daynight ??
                  'D',
              },


              classification: {

                classification:
                  ClassificationType.UNCLASSIFIED,

                confidence_score:
                  0,

                explanation:
                  'Awaiting AI classification.',

                evidence: [],

                risk_score:
                  0,

                risk_level:
                  'LOW',
              },


              context: {

                nearby_facilities:
                  [],

                nearest_facility_distance:
                  null,

                nearest_facility_type:
                  null,

                facility_count_in_radius:
                  0,

                land_use_context:
                  [],

                osm_source:
                  'PENDING',

                queried_at:
                  null,
              },

            } as ClassifiedHotspot;
          }
        )

        .filter(
          (
            hotspot:
              ClassifiedHotspot | null
          ): hotspot is ClassifiedHotspot =>
            hotspot !== null
        );
      } catch (err: any) {
        if (
          err?.name === 'AbortError' ||
          String(err?.message || '').includes('aborted')
        ) {
          return [];
        }
        throw err;
      }
    };


  /*
   * =======================================================
   * REFRESH DATA
   * =======================================================
   */

  const refreshData =
    async () => {

      try {

        setLoading(
          true
        );


        setError(
          null
        );


        /*
         * ---------------------------------------------------
         * 1. Fetch both streams
         * ---------------------------------------------------
         */

        const [
          initialClassifiedData,
          currentMapData,
        ] = await Promise.all([

          fetchClassifiedHotspots(
            'IND',
            1
          ),

          fetchAllCurrentMapHotspots(),

        ]);


        /*
         * ---------------------------------------------------
         * 2. Reconcile live FIRMS with backend state
         * ---------------------------------------------------
         */

        const mergedInitialMapData =
          mergeClassifiedIntoMap(
            currentMapData,
            initialClassifiedData
          );


        /*
         * ---------------------------------------------------
         * 3. Sidebar / classified stream
         * ---------------------------------------------------
         */

        let latestDate = '';
        for (const item of mergedInitialMapData) {
          const d = String(item.hotspot?.acq_date || '').slice(0, 10);
          if (d && d > latestDate) latestDate = d;
        }

        const activeSidebarHotspots = latestDate
          ? initialClassifiedData.filter((h) => {
              const d = String(h.hotspot?.acq_date || '').slice(0, 10);
              return !d || d >= latestDate;
            })
          : initialClassifiedData;

        setHotspots(
          activeSidebarHotspots.length > 0 ? activeSidebarHotspots : initialClassifiedData
        );


        /*
         * ---------------------------------------------------
         * 4. Map stream
         * ---------------------------------------------------
         *
         * IMPORTANT:
         *
         * This is no longer just raw PENDING FIRMS data.
         *
         * It contains the backend classification whenever
         * the corresponding FIRMS observation has one.
         */

        setMapHotspots(
          mergedInitialMapData
        );


        /*
         * ---------------------------------------------------
         * Demo fallback — if both live streams are empty
         * (NASA cold, key invalid, or no satellite pass yet),
         * treat it the same as a network error and load
         * DEMO_HOTSPOTS so the map always shows data.
         * ---------------------------------------------------
         */

        if (
          mergedInitialMapData.length === 0 &&
          initialClassifiedData.length === 0
        ) {
          throw new Error(
            'No live hotspot data available — loading demo cache'
          );
        }


        setIsDemoMode(
          false
        );


        /*
         * ---------------------------------------------------
         * 5. Restore selected hotspot
         * ---------------------------------------------------
         */

        if (
          typeof window !==
          'undefined'
        ) {

          const savedId =
            localStorage.getItem(
              'vtx_selectedHotspot'
            );


          if (savedId) {

            const found =
              mergedInitialMapData.find(
                (
                  hotspot
                ) =>
                  hotspot.id ===
                  savedId
              );


            if (found) {

              setSelectedHotspotState(
                found
              );

            } else {

              const fallback =
                initialClassifiedData.find(
                  (
                    hotspot
                  ) =>
                    hotspot.id ===
                    savedId
                );


              setSelectedHotspotState(
                fallback || null
              );
            }
          }
        }


        /*
         * ---------------------------------------------------
         * 6. Background OSM enrichment
         * ---------------------------------------------------
         *
         * Backend enrichment runs separately so the dashboard
         * doesn't have to wait for every OSM request.
         *
         * When it finishes:
         *
         *   - refetch classified data
         *   - refetch live FIRMS
         *   - merge them again
         *   - update BOTH streams
         */

        void enrichTop50Hotspots(
          initialClassifiedData
        )

          .then(
            async () => {

              const enrichedData =
                await fetchClassifiedHotspots(
                  'IND',
                  1
                );


              /*
               * Refetch current FIRMS so map state remains
               * synchronized with the backend.
               */

              const freshMapData =
                await fetchAllCurrentMapHotspots();


              const mergedEnrichedMapData =
                mergeClassifiedIntoMap(
                  freshMapData,
                  enrichedData
                );

              let latestFreshDate = '';
              for (const item of mergedEnrichedMapData) {
                const d = String(item.hotspot?.acq_date || '').slice(0, 10);
                if (d && d > latestFreshDate) latestFreshDate = d;
              }

              const activeEnrichedSidebar = latestFreshDate
                ? enrichedData.filter((h) => {
                    const d = String(h.hotspot?.acq_date || '').slice(0, 10);
                    return !d || d >= latestFreshDate;
                  })
                : enrichedData;

              setHotspots(
                activeEnrichedSidebar.length > 0 ? activeEnrichedSidebar : enrichedData
              );


              setMapHotspots(
                mergedEnrichedMapData
              );


              /*
               * Keep the selected hotspot synchronized with
               * the newly enriched backend object.
               */

              if (
                typeof window !==
                'undefined'
              ) {

                const savedId =
                  localStorage.getItem(
                    'vtx_selectedHotspot'
                  );


                if (savedId) {

                  const found =
                    mergedEnrichedMapData.find(
                      (
                        hotspot
                      ) =>
                        hotspot.id ===
                        savedId
                    );


                  if (found) {

                    setSelectedHotspotState(
                      found
                    );

                  }
                }
              }

            }
          )

          .catch(
            (
              enrichmentError
            ) => {
              if (
                enrichmentError?.name === 'AbortError' ||
                String(enrichmentError?.message || '').includes('aborted')
              ) {
                return;
              }
              console.warn(
                '[VERTEX] Background OSM enrichment failed:',
                enrichmentError
              );
            }
          );


        /*
         * ---------------------------------------------------
         * 7. Analytics
         * ---------------------------------------------------
         */

        const summary =
          await fetchAnalyticsSummary();


        setAnalyticsSummary(
          summary
        );


        setIsDemoMode(
          false
        );


      } catch (
        err: any
      ) {

        if (
          err?.name === 'AbortError' ||
          String(err?.message || '').includes('aborted')
        ) {
          return;
        }

        console.warn(
          'Database connection failed. Falling back to offline demo cache.',
          err
        );


        setHotspots(
          DEMO_HOTSPOTS
        );


        setMapHotspots(
          DEMO_HOTSPOTS
        );


        setAnalyticsSummary(
          generateDemoSummary(
            DEMO_HOTSPOTS
          )
        );


        setIsDemoMode(
          true
        );


        setError(
          err?.message ||
          'Unable to connect to live backend.'
        );


        /*
         * Restore demo selection.
         */

        if (
          typeof window !==
          'undefined'
        ) {

          const savedId =
            localStorage.getItem(
              'vtx_selectedHotspot'
            );


          if (savedId) {

            const found =
              DEMO_HOTSPOTS.find(
                (
                  hotspot
                ) =>
                  hotspot.id ===
                  savedId
              );


            setSelectedHotspotState(
              found || null
            );
          }
        }

      } finally {

        setLoading(
          false
        );
      }
    };


  /*
   * =======================================================
   * INITIAL LOAD
   * =======================================================
   */

  useEffect(() => {

    // On cold start the backend returns empty immediately and fires classification
    // in the background. We auto-retry once after 40 s so data appears automatically.
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    refreshData().then(() => {
      // If hotspots are still empty after the first load, schedule a retry
      // (captured via closure — state won't be updated yet, so we just always retry once)
      retryTimer = setTimeout(() => {
        refreshData().catch(() => {});
      }, 40_000);
    }).catch(() => {});

    return () => {
      if (retryTimer) clearTimeout(retryTimer);
    };

  }, []);


  /*
   * =======================================================
   * PROVIDER
   * =======================================================
   */

  return (
    <GlobalStateContext.Provider
      value={{

        hotspots,

        mapHotspots,

        analyticsSummary,

        loading,

        error,

        isDemoMode,

        selectedHotspot,

        setSelectedHotspot,

        mapStyle,

        setMapStyle,

        streamFilter,

        setStreamFilter,

        mapCenter,

        setMapCenter,

        mapZoom,

        setMapZoom,

        refreshData,

        autoRefreshInterval,
        setAutoRefreshInterval,
        minConfidenceDisplay,
        setMinConfidenceDisplay,
        strictRiskFiltering,
        setStrictRiskFiltering,
        criticalNotificationsEnabled,
        setCriticalNotificationsEnabled,

      }}
    >

      {children}

    </GlobalStateContext.Provider>
  );
}


/*
 * =========================================================
 * HOOK
 * =========================================================
 */

export function useGlobalState() {

  const context =
    useContext(
      GlobalStateContext
    );


  if (
    context === undefined
  ) {

    throw new Error(
      'useGlobalState must be used within a GlobalStateProvider'
    );
  }


  return context;
}