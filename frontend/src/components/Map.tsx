import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { Map as MapGL, type ViewStateChangeEvent } from "react-map-gl/maplibre";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import { useParcelData } from "../hooks/useParcelData";
import { useUtilityLayers, UTILITY_LAYERS } from "../hooks/useUtilityLayers";
import type { ParcelGeoJSON } from "../api/client";

function escapeHtml(str: unknown): string {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function safeImgUrl(url: unknown): string {
  if (typeof url !== "string") return "";
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") return url;
  } catch { /* invalid URL */ }
  return "";
}

const INITIAL_VIEW = {
  longitude: -78.8986,
  latitude: 35.994,
  zoom: 12,
  pitch: 0,
  bearing: 0,
};

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

const SUBDIVIDABLE_FILL: Record<string, [number, number, number, number]> = {
  small_lot: [45, 212, 191, 160],
  standard: [74, 222, 128, 150],
  flag_lot: [59, 130, 246, 140],
};
const DEFAULT_SUBDIVIDABLE_FILL: [number, number, number, number] = [34, 197, 94, 160];
const NOT_SUBDIVIDABLE_FILL: [number, number, number, number] = [50, 60, 75, 60];

const FOR_SALE_SUBDIVIDABLE_FILL: [number, number, number, number] = [251, 191, 36, 190];
const FOR_SALE_SUBDIVIDABLE_LINE: [number, number, number, number] = [251, 191, 36, 255];
const FOR_SALE_OTHER_FILL: [number, number, number, number] = [239, 68, 68, 110];
const FOR_SALE_OTHER_LINE: [number, number, number, number] = [239, 68, 68, 220];

const PROPOSED_LOT_COLORS: [number, number, number, number][] = [
  [59, 130, 246, 140],   // blue
  [168, 85, 247, 140],   // purple
  [236, 72, 153, 140],   // pink
  [34, 197, 94, 140],    // green
  [251, 146, 60, 140],   // orange
  [14, 165, 233, 140],   // sky
];

const LEGEND_ITEMS = [
  { color: "bg-green-500", label: "Subdividable (standard)" },
  { color: "bg-teal-400", label: "Subdividable (small lot)" },
  { color: "bg-blue-500", label: "Subdividable (flag lot)" },
  { color: "bg-amber-400", label: "Subdividable + For Sale" },
  { color: "bg-red-500/70", label: "For Sale (not subdividable)" },
  { color: "bg-slate-600/30", label: "Not subdividable" },
];

interface FlyToState {
  lng: number;
  lat: number;
  zoom: number;
  key: number;
}

interface Props {
  subdividableOnly: boolean;
  cornerOnly: boolean;
  forSaleOnly: boolean;
  zoningFilter: string;
  minLots: number;
  selectedParcelId: number | null;
  onParcelClick: (id: number | null) => void;
  utilityLayers?: Record<string, boolean>;
  flyTo?: FlyToState | null;
}

function MapLegend({
  utilityLayerVisibility,
  utilityErrors,
}: {
  utilityLayerVisibility: Record<string, boolean>;
  utilityErrors: Record<string, boolean>;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const activeUtilityLayers = UTILITY_LAYERS.filter((l) => utilityLayerVisibility[l.id]);

  return (
    <div className="absolute bottom-4 right-3 z-20">
      {/* Collapsed state: just a small button (mobile default) */}
      {collapsed ? (
        <button
          onClick={() => setCollapsed(false)}
          className="bg-slate-900/90 backdrop-blur rounded-lg border border-slate-700 px-2.5 py-1.5 text-[10px] text-slate-300 hover:text-white transition-colors"
        >
          Legend ▲
        </button>
      ) : (
        <div className="bg-slate-900/90 backdrop-blur rounded-lg border border-slate-700 px-3 py-2.5 space-y-1.5">
          <button
            onClick={() => setCollapsed(true)}
            className="md:hidden text-[10px] text-slate-400 hover:text-white w-full text-right transition-colors leading-none mb-1"
          >
            ▼ hide
          </button>
          {LEGEND_ITEMS.map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              <span
                className={`inline-block w-3 h-3 rounded-sm ${item.color} border border-white/20`}
              />
              <span className="text-[10px] text-slate-300">{item.label}</span>
            </div>
          ))}
          {activeUtilityLayers.map((layer) => (
            <div key={layer.id} className="flex items-center gap-2">
              {layer.pointRadius > 0 ? (
                <span
                  className="inline-block rounded-full"
                  style={{
                    width: Math.max(layer.pointRadius * 2, 6),
                    height: Math.max(layer.pointRadius * 2, 6),
                    backgroundColor: `rgba(${layer.color[0]},${layer.color[1]},${layer.color[2]},${layer.color[3] / 255})`,
                  }}
                />
              ) : (
                <span
                  className="inline-block w-3"
                  style={{
                    backgroundColor: `rgba(${layer.color[0]},${layer.color[1]},${layer.color[2]},${layer.color[3] / 255})`,
                    height: Math.max(layer.lineWidth, 2),
                  }}
                />
              )}
              <span className="text-[10px] text-slate-300">
                {layer.label}
                {utilityErrors[layer.id] && " (unavailable)"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MapView({
  subdividableOnly,
  cornerOnly,
  forSaleOnly,
  zoningFilter,
  minLots,
  selectedParcelId,
  onParcelClick,
  utilityLayers: utilityLayerVisibility = {},
  flyTo,
}: Props) {
  const [viewState, setViewState] = useState(INITIAL_VIEW);
  const [bbox, setBbox] = useState<[number, number, number, number] | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const bboxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, loading } = useParcelData(bbox, subdividableOnly, forSaleOnly, viewState.zoom);
  const { layerData: utilityData, loading: utilityLoading, errors: utilityErrors } = useUtilityLayers(
    bbox,
    viewState.zoom,
    utilityLayerVisibility
  );

  const computeBbox = useCallback((vs: typeof INITIAL_VIEW) => {
    const { longitude, latitude, zoom } = vs;
    const span = 360 / Math.pow(2, zoom) / 2;
    const aspect = typeof window !== "undefined" ? window.innerWidth / window.innerHeight : 1.5;
    setBbox([
      longitude - span * aspect,
      latitude - span,
      longitude + span * aspect,
      latitude + span,
    ]);
  }, []);

  const handleViewStateChange = useCallback(
    (e: ViewStateChangeEvent) => {
      const vs = e.viewState as typeof INITIAL_VIEW;
      setViewState(vs);
      if (bboxTimerRef.current) clearTimeout(bboxTimerRef.current);
      bboxTimerRef.current = setTimeout(() => computeBbox(vs), 300);
    },
    [computeBbox]
  );

  useEffect(() => {
    return () => { if (bboxTimerRef.current) clearTimeout(bboxTimerRef.current); };
  }, []);

  const flyToKeyRef = useRef<number>(0);
  useEffect(() => {
    if (!flyTo || flyTo.key === flyToKeyRef.current) return;
    flyToKeyRef.current = flyTo.key;

    const target = {
      ...viewState,
      longitude: flyTo.lng,
      latitude: flyTo.lat,
      zoom: flyTo.zoom,
    };

    const steps = 40;
    const duration = 800;
    const startVs = { ...viewState };
    let frame = 0;

    const ease = (t: number) => t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

    const animate = () => {
      frame++;
      const t = ease(Math.min(frame / steps, 1));
      const vs = {
        ...startVs,
        longitude: startVs.longitude + (target.longitude - startVs.longitude) * t,
        latitude: startVs.latitude + (target.latitude - startVs.latitude) * t,
        zoom: startVs.zoom + (target.zoom - startVs.zoom) * t,
      };
      setViewState(vs);
      if (frame < steps) {
        setTimeout(animate, duration / steps);
      } else {
        computeBbox(vs);
      }
    };
    animate();
  }, [flyTo]); // eslint-disable-line react-hooks/exhaustive-deps

  const filteredData = useMemo(() => {
    if (!data) return null;
    let features = data.features;
    if (zoningFilter) {
      features = features.filter(
        (f) => f.properties.zoning === zoningFilter
      );
    }
    if (minLots > 0) {
      features = features.filter(
        (f) => (f.properties.num_possible_lots || 0) >= minLots
      );
    }
    if (cornerOnly) {
      features = features.filter(
        (f) => f.properties.is_corner_lot === true
      );
    }
    return { ...data, features } as ParcelGeoJSON;
  }, [data, zoningFilter, minLots, cornerOnly]);

  const selectedFeature = useMemo(() => {
    if (!selectedParcelId || !data) return null;
    return data.features.find((f) => f.properties.id === selectedParcelId) || null;
  }, [selectedParcelId, data]);

  const layers = useMemo(() => {
    const result: any[] = [];

    if (filteredData) {
      result.push(
        new GeoJsonLayer({
          id: "parcels",
          data: filteredData as any,
          filled: true,
          stroked: true,
          pickable: true,
          getFillColor: (f: any) => {
            const p = f.properties;
            if (p?.id === selectedParcelId) {
              if (p?.proposed_lots) return [30, 41, 59, 120];
              return [59, 130, 246, 200];
            }
            if (p?.id === hoveredId) return [147, 197, 253, 180];
            if (p?.for_sale && p?.is_subdividable) return FOR_SALE_SUBDIVIDABLE_FILL;
            if (p?.for_sale) return FOR_SALE_OTHER_FILL;
            if (p?.is_subdividable) {
              const stype = p?.subdivision_type || "";
              return SUBDIVIDABLE_FILL[stype] || DEFAULT_SUBDIVIDABLE_FILL;
            }
            return NOT_SUBDIVIDABLE_FILL;
          },
          getLineColor: (f: any) => {
            const p = f.properties;
            if (p?.id === selectedParcelId) return [59, 130, 246, 255];
            if (p?.id === hoveredId) return [147, 197, 253, 255];
            if (p?.for_sale && p?.is_subdividable) return FOR_SALE_SUBDIVIDABLE_LINE;
            if (p?.for_sale) return FOR_SALE_OTHER_LINE;
            if (p?.is_subdividable) return [100, 200, 140, 160];
            return [100, 116, 139, 100];
          },
          getLineWidth: (f: any) => {
            const p = f.properties;
            if (p?.id === selectedParcelId) return 3;
            if (p?.id === hoveredId) return 2;
            if (p?.for_sale && p?.is_subdividable) return 3;
            if (p?.for_sale) return 2;
            return 1;
          },
          lineWidthUnits: "pixels",
          lineWidthMinPixels: 1,
          updateTriggers: {
            getFillColor: [selectedParcelId, hoveredId],
            getLineColor: [selectedParcelId, hoveredId],
            getLineWidth: [selectedParcelId, hoveredId],
          },
        })
      );
    }

    // Outer glow ring for subdividable + for-sale parcels
    if (filteredData) {
      const forSaleSubdiv = {
        type: "FeatureCollection" as const,
        features: filteredData.features.filter(
          (f) => f.properties.for_sale && f.properties.is_subdividable
        ),
      };
      if (forSaleSubdiv.features.length > 0) {
        result.push(
          new GeoJsonLayer({
            id: "for-sale-glow",
            data: forSaleSubdiv as any,
            filled: false,
            stroked: true,
            pickable: false,
            getLineColor: [251, 191, 36, 100],
            getLineWidth: 8,
            lineWidthUnits: "pixels",
            lineWidthMinPixels: 4,
          })
        );
      }
    }

    // Utility infrastructure overlays
    for (const layerConfig of UTILITY_LAYERS) {
      const geoData = utilityData[layerConfig.id];
      if (utilityLayerVisibility[layerConfig.id] && geoData && geoData.features.length > 0) {
        const isPointLayer = layerConfig.pointRadius > 0;
        result.push(
          new GeoJsonLayer({
            id: `utility-${layerConfig.id}`,
            data: geoData as any,
            filled: isPointLayer,
            stroked: true,
            pickable: true,
            getFillColor: layerConfig.color as any,
            getLineColor: layerConfig.color as any,
            getLineWidth: layerConfig.lineWidth || 1,
            lineWidthUnits: "pixels",
            lineWidthMinPixels: 1,
            pointRadiusMinPixels: layerConfig.pointRadius,
            pointRadiusMaxPixels: layerConfig.pointRadius + 2,
            getPointRadius: layerConfig.pointRadius,
            pointRadiusUnits: "pixels" as const,
            parameters: { depthTest: false },
          })
        );
      }
    }

    // Original parcel outline when viewing subdivision
    if (selectedFeature?.properties?.proposed_lots) {
      result.push(
        new GeoJsonLayer({
          id: "original-parcel-outline",
          data: { type: "FeatureCollection", features: [selectedFeature] } as any,
          filled: false,
          stroked: true,
          pickable: false,
          getLineColor: [255, 255, 255, 200],
          getLineWidth: 2,
          lineWidthUnits: "pixels",
          lineWidthMinPixels: 2,
          parameters: { depthTest: false },
        })
      );
    }

    // Proposed lots for selected parcel — explode MultiPolygon into
    // individual features so each lot gets a distinct color
    if (selectedFeature?.properties?.proposed_lots) {
      const lotsGeom = selectedFeature.properties.proposed_lots;
      if (lotsGeom && typeof lotsGeom === "object" && lotsGeom.type) {
        let lotFeatures: any[] = [];
        if (lotsGeom.type === "MultiPolygon" && lotsGeom.coordinates) {
          lotFeatures = lotsGeom.coordinates.map(
            (coords: any, i: number) => ({
              type: "Feature" as const,
              geometry: { type: "Polygon" as const, coordinates: coords },
              properties: { lotIndex: i },
            })
          );
        } else {
          lotFeatures = [
            { type: "Feature" as const, geometry: lotsGeom, properties: { lotIndex: 0 } },
          ];
        }

        const proposedLotsGeoJSON = {
          type: "FeatureCollection" as const,
          features: lotFeatures,
        };
        result.push(
          new GeoJsonLayer({
            id: "proposed-lots",
            data: proposedLotsGeoJSON as any,
            filled: true,
            stroked: true,
            getFillColor: (f: any) => {
              const idx = f.properties?.lotIndex ?? 0;
              return PROPOSED_LOT_COLORS[idx % PROPOSED_LOT_COLORS.length];
            },
            getLineColor: (f: any) => {
              const base = PROPOSED_LOT_COLORS[
                (f.properties?.lotIndex ?? 0) % PROPOSED_LOT_COLORS.length
              ];
              return [base[0], base[1], base[2], 255];
            },
            getLineWidth: 3,
            lineWidthUnits: "pixels",
            lineWidthMinPixels: 2,
          })
        );
      }
    }

    // Proposed structures for selected parcel (only new builds, not existing)
    if (selectedFeature?.properties?.proposed_structures) {
      const structGeom = selectedFeature.properties.proposed_structures;
      if (structGeom && typeof structGeom === "object" && structGeom.type) {
        const proposedStructsGeoJSON = {
          type: "FeatureCollection" as const,
          features: [
            {
              type: "Feature" as const,
              geometry: structGeom,
              properties: {},
            },
          ],
        };
        result.push(
          new GeoJsonLayer({
            id: "proposed-structures",
            data: proposedStructsGeoJSON as any,
            filled: true,
            stroked: true,
            getFillColor: [249, 115, 22, 120],
            getLineColor: [249, 115, 22, 255],
            getLineWidth: 2,
            lineWidthUnits: "pixels",
            lineWidthMinPixels: 2,
          })
        );
      }
    }

    return result;
  }, [filteredData, selectedParcelId, hoveredId, selectedFeature, utilityData, utilityLayerVisibility]);

  const handleClick = useCallback(
    (info: PickingInfo) => {
      if (info.object) {
        onParcelClick(info.object.properties?.id || null);
      } else {
        onParcelClick(null);
      }
    },
    [onParcelClick]
  );

  const handleHover = useCallback((info: PickingInfo) => {
    setHoveredId(info.object?.properties?.id || null);
  }, []);

  return (
    <div className="relative w-full h-full">
      <DeckGL
        viewState={viewState}
        onViewStateChange={handleViewStateChange as any}
        controller={true}
        layers={layers}
        onClick={handleClick}
        onHover={handleHover}
        getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
        getTooltip={({ object, layer }: PickingInfo) => {
          if (!object?.properties) return null;

          // Utility layer tooltip
          if (layer?.id?.startsWith("utility-")) {
            const p = object.properties;
            const layerId = layer.id.replace("utility-", "");
            const config = UTILITY_LAYERS.find((l) => l.id === layerId);
            const label = config?.label || "Utility";
            const parts = [`<b>${escapeHtml(label)}</b>`];
            if (p.diameter) parts.push(`${escapeHtml(p.diameter)}" diameter`);
            if (p.material) parts.push(escapeHtml(p.material));
            if (p.owner) parts.push(`Owner: ${escapeHtml(p.owner)}`);
            if (p.facility_id) parts.push(`<span style="color:#94a3b8">${escapeHtml(p.facility_id)}</span>`);
            return {
              html: `<div style="font-size:12px;padding:6px 10px;background:#1e293b;color:white;border-radius:6px;border:1px solid #334155;max-width:240px;">
                ${parts.join("<br/>")}
              </div>`,
              style: { background: "transparent", border: "none", padding: "0" },
            };
          }

          const p = object.properties;
          const addr = escapeHtml(p.address || "No address");
          const area = Math.round(p.area_sqft).toLocaleString();
          const acres = p.acreage ? ` (${Number(p.acreage).toFixed(2)} ac)` : "";
          const value = p.total_prop_value
            ? `$${Math.round(p.total_prop_value).toLocaleString()}`
            : "";
          const zoning = escapeHtml(p.zoning);

          // Enhanced tooltip for for-sale parcels
          if (p.for_sale) {
            const color = p.is_subdividable ? "#fbbf24" : "#ef4444";
            const tag = p.is_subdividable ? "FOR SALE &middot; SUBDIVIDABLE" : "FOR SALE";
            const photoSrc = safeImgUrl(p.photo_url);
            const photoHtml = photoSrc
              ? `<img src="${escapeHtml(photoSrc)}" style="width:100%;height:130px;object-fit:cover;display:block" />`
              : "";
            const priceLine = p.list_price
              ? `<span style="font-size:16px;font-weight:700;color:white">$${Math.round(p.list_price).toLocaleString()}</span>`
              : "";
            const domLine = p.days_on_market != null
              ? `<span style="color:#94a3b8;font-size:11px"> &middot; ${escapeHtml(p.days_on_market)} days</span>`
              : "";

            let statusLine = "";
            if (p.is_subdividable) {
              statusLine = `<div style="margin-top:4px"><span style="color:#4ade80;font-size:11px;font-weight:600">&#10003; ${escapeHtml(p.num_possible_lots || "?")} lots (${escapeHtml((p.subdivision_type || "?").replace("_", " "))})</span></div>`;
            }

            return {
              html: `<div style="font-size:12px;padding:0;background:#1e293b;color:white;border-radius:8px;border:1px solid ${color}40;max-width:300px;overflow:hidden;">
                ${photoHtml}
                <div style="padding:8px 12px;">
                  <div style="color:${color};font-weight:700;font-size:10px;letter-spacing:0.5px;margin-bottom:4px">${tag}</div>
                  <b>${addr}</b><br/>
                  ${priceLine}${domLine}<br/>
                  <span style="color:#94a3b8;font-size:11px">${zoning} &middot; ${area} sf${acres}</span>
                  ${statusLine}
                </div>
              </div>`,
              style: { background: "transparent", border: "none", padding: "0" },
            };
          }

          const forSaleColor = p.for_sale && p.is_subdividable ? "#fbbf24" : "#ef4444";
          const forSaleLabel = p.for_sale && p.is_subdividable ? "FOR SALE &middot; SUBDIVIDABLE" : "FOR SALE";
          const forSaleLine = p.for_sale
            ? `<span style="color:${forSaleColor};font-weight:700;font-size:11px;letter-spacing:0.5px">${forSaleLabel}</span><br/>${p.list_price ? `<span style="color:${forSaleColor};font-weight:600">$${Math.round(p.list_price).toLocaleString()}</span>${p.days_on_market != null ? ` <span style="color:#94a3b8">&middot; ${escapeHtml(p.days_on_market)} days</span>` : ""}<br/>` : ""}`
            : "";
          let statusLine: string;
          if (p.is_subdividable) {
            statusLine = `<span style="color:#4ade80">&#10003; ${escapeHtml(p.num_possible_lots || "?")} lots (${escapeHtml((p.subdivision_type || "?").replace("_", " "))})</span>`;
            if (p.is_corner_lot) statusLine += ' <span style="color:#60a5fa">&#9670; Corner</span>';
            else if (p.num_street_frontages === 1) statusLine += ' <span style="color:#fbbf24">Interior</span>';
          } else {
            const cls = escapeHtml((p.quick_filter_result || "").replace(/_/g, " "));
            statusLine = `<span style="color:#94a3b8">${cls}</span>`;
          }
          return {
            html: `<div style="font-size:12px;padding:6px 10px;background:#1e293b;color:white;border-radius:6px;border:1px solid #334155;max-width:280px;">
              <b>${addr}</b><br/>
              ${forSaleLine}${zoning} &middot; ${area} sf${acres}<br/>
              ${value ? `<span style="color:#94a3b8">${value}</span><br/>` : ""}
              ${statusLine}
            </div>`,
            style: { background: "transparent", border: "none", padding: "0" },
          };
        }}
      >
        <MapGL
          mapStyle={MAP_STYLE}
          onLoad={() => computeBbox(viewState)}
        />
      </DeckGL>

      <MapLegend utilityLayerVisibility={utilityLayerVisibility} utilityErrors={utilityErrors} />

      {loading && (
        <div className="absolute bottom-4 md:bottom-4 left-1/2 -translate-x-1/2 bg-slate-800/90 backdrop-blur text-white text-xs px-3 py-1.5 rounded-full border border-slate-600 z-10">
          Loading parcels...
        </div>
      )}

      {Object.values(utilityLoading).some(Boolean) && (
        <div className="absolute bottom-12 md:bottom-12 left-1/2 -translate-x-1/2 bg-slate-800/90 backdrop-blur text-white text-xs px-3 py-1.5 rounded-full border border-slate-600 z-10">
          Loading utility layers...
        </div>
      )}

      {UTILITY_LAYERS.some(
        (l) => utilityLayerVisibility[l.id] && viewState.zoom < l.minZoom
      ) && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 bg-slate-800/90 backdrop-blur text-amber-400 text-xs px-3 py-1.5 rounded-full border border-slate-600 z-10">
          Zoom in to see utility layers
        </div>
      )}
    </div>
  );
}
