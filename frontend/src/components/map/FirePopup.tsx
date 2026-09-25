import {
  ClassifiedHotspot,
  CLASSIFICATION_LABELS,
  CLASSIFICATION_COLORS,
  ClassificationType,
} from '@/types';

export function FirePopup({
  hotspot,
}: {
  hotspot: ClassifiedHotspot;
}) {
  const c = hotspot?.classification || ({} as any);
  const f = hotspot?.hotspot || ({} as any);
  const ctx = hotspot?.context || (hotspot as any)?.osm_context || {};

  const type =
    (c?.classification || '') as ClassificationType;

  const color =
    CLASSIFICATION_COLORS[type] ||
    CLASSIFICATION_COLORS.UNKNOWN_UNCERTAIN;

  const label =
    CLASSIFICATION_LABELS[type] ||
    'Unknown / Uncertain';

  return (
    <div className="w-[340px] bg-surface-container-low border border-outline-variant rounded-none overflow-hidden flex flex-col font-body-md shadow-2xl">
      <div
        className="px-4 py-3 border-b border-outline-variant"
        style={{
          borderTop: `3px solid ${color}`,
        }}
      >
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center space-x-2">
            <span className="font-headline-sm text-[10px] uppercase text-secondary tracking-widest">
              AI Classification
            </span>

            <span className="font-mono-data-sm text-[10px] bg-surface-container-highest text-on-surface px-2 py-0.5 rounded-none border border-outline-variant">
              {((Number(c?.confidence_score) || 0) * 100).toFixed(1)}% Confidence
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-2 mt-2">
          {type ===
            ClassificationType.INDUSTRIAL_FIRE ||
          type ===
            ClassificationType.PERSISTENT_INDUSTRIAL_SOURCE ||
          type ===
            ClassificationType.GAS_FLARE ? (
            <span
              className="material-symbols-outlined w-4 h-4 text-[16px]"
              style={{ color }}
            >
              factory
            </span>
          ) : type ===
            ClassificationType.WILDFIRE_FOREST_FIRE ? (
            <span
              className="material-symbols-outlined w-4 h-4 text-[16px]"
              style={{ color }}
            >
              forest
            </span>
          ) : (
            <span
              className="material-symbols-outlined w-4 h-4 text-[16px]"
              style={{ color }}
            >
              local_fire_department
            </span>
          )}

          <h3 className="font-headline-sm text-[14px] text-on-surface tracking-widest uppercase ml-2">
            {label}
          </h3>
        </div>
      </div>

      <div className="p-4 max-h-[300px] overflow-y-auto space-y-4">
        <div>
          <h4 className="font-headline-sm text-[10px] text-secondary uppercase mb-2 tracking-widest">
            Sensor Data (FIRMS)
          </h4>

          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="bg-surface-container p-2 rounded-none border border-outline-variant">
              <span className="text-secondary text-[10px] font-mono block uppercase">
                FRP
              </span>

              <span className="font-mono-data-md text-primary">
                {(Number(f?.frp) || 0).toFixed(1)} MW
              </span>
            </div>

            <div className="bg-surface-container p-2 rounded-none border border-outline-variant">
              <span className="text-secondary text-[10px] font-mono block uppercase">
                Brightness
              </span>

              <span className="font-mono-data-md text-primary">
                {(f.brightness && f.brightness > 0) ? f.brightness.toFixed(1) : 'N/A'} K
              </span>
            </div>

            <div className="bg-surface-container p-2 rounded-none col-span-2 flex justify-between border border-outline-variant">
              <div>
                <span className="text-secondary text-[10px] font-mono block uppercase">
                  Acquisition
                </span>

                <span className="font-mono-data-sm text-on-surface">
                  {f.acq_date} {f.acq_time}
                </span>
              </div>

              <div className="text-right">
                <span className="text-secondary text-[10px] font-mono block uppercase">
                  Satellite
                </span>

                <span className="font-mono-data-sm text-on-surface">
                  {f.satellite}
                </span>
              </div>
            </div>
          </div>
        </div>

        {ctx.nearby_facilities &&
          ctx.nearby_facilities.length > 0 && (
            <div>
              <h4 className="font-headline-sm text-[10px] text-secondary uppercase mb-2 tracking-widest">
                Facility Context
              </h4>

              <div className="bg-surface-container rounded-none p-2 space-y-2 border border-outline-variant">
                {ctx.nearby_facilities
                  .slice(0, 3)
                  .map((fac, i) => {
                    const distance = Math.min(
                      Number(
                        (fac as any).distance_m ??
                          (fac as any).distance_meters ??
                          0
                      ),
                      1000
                    );

                    return (
                      <div
                        key={i}
                        className="flex justify-between items-center text-on-surface border-b border-outline-variant pb-1 last:border-0 last:pb-0 font-mono-data-sm text-[10px]"
                      >
                        <span className="truncate pr-2">
                          {fac.name ||
                            'Unnamed Facility'}
                        </span>

                        <span className="text-secondary">
                          {distance.toFixed(0)}m
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

        <div>
          <h4 className="font-headline-sm text-[10px] text-secondary uppercase mb-2 tracking-widest">
            AI Analysis
          </h4>

          <p className="font-body-sm text-[12px] text-on-surface leading-relaxed mb-3">
            {c.explanation}
          </p>

          {c.evidence &&
            c.evidence.length > 0 && (
              <div className="space-y-1">
                {c.evidence.map(
                  (ev, i) => (
                    <div
                      key={i}
                      className="flex items-start space-x-2 text-[11px] font-body-sm text-secondary"
                    >
                      <div className="w-1.5 h-1.5 rounded-none bg-outline mt-1 flex-shrink-0" />

                      <span>{ev}</span>
                    </div>
                  )
                )}
              </div>
            )}
        </div>
      </div>

      <div className="bg-surface px-4 py-2 flex items-center space-x-2 border-t border-outline-variant">
        <span className="material-symbols-outlined text-[12px] text-secondary">
          info
        </span>

        <span className="font-mono text-[9px] text-secondary uppercase tracking-wider">
          AI-assisted classification. Not definitive
          ground truth.
        </span>
      </div>
    </div>
  );
}