import { getExportCSVUrl } from "../api/client";
import { UTILITY_LAYERS } from "../hooks/useUtilityLayers";

interface Props {
  open: boolean;
  onToggle: () => void;
  subdividableOnly: boolean;
  onSubdividableChange: (v: boolean) => void;
  cornerOnly: boolean;
  onCornerOnlyChange: (v: boolean) => void;
  forSaleOnly: boolean;
  onForSaleChange: (v: boolean) => void;
  zoningFilter: string;
  onZoningChange: (v: string) => void;
  minLots: number;
  onMinLotsChange: (v: number) => void;
  utilityLayers: Record<string, boolean>;
  onUtilityLayerToggle: (layerId: string, enabled: boolean) => void;
}

const ZONING_OPTIONS = [
  "",
  "RS-20",
  "RS-10",
  "RS-8",
  "RS-M",
  "RU-5",
  "RU-5(2)",
  "RU-M",
];

const LAYER_COLORS: Record<string, string> = {
  "fire-hydrants": "peer-checked:bg-blue-500",
  "stormwater-pipes": "peer-checked:bg-cyan-400",
  "stormwater-structures": "peer-checked:bg-cyan-500",
};

const LAYER_ICONS: Record<string, string> = {
  "fire-hydrants": "🔵",
  "stormwater-pipes": "🔷",
  "stormwater-structures": "🔹",
};

const LAYER_DESCRIPTIONS: Record<string, string> = {
  "fire-hydrants":
    "Hydrants sit on water mains — nearby hydrants indicate city water hookup is available",
  "stormwater-pipes":
    "City storm drainage lines — required for runoff management on new lots",
  "stormwater-structures":
    "Catch basins and manholes — access points for the storm drainage system",
};

export default function FilterPanel({
  open,
  onToggle,
  subdividableOnly,
  onSubdividableChange,
  cornerOnly,
  onCornerOnlyChange,
  forSaleOnly,
  onForSaleChange,
  zoningFilter,
  onZoningChange,
  minLots,
  onMinLotsChange,
  utilityLayers,
  onUtilityLayerToggle,
}: Props) {
  return (
    <>
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="absolute top-14 left-3 z-40 bg-slate-800/90 backdrop-blur hover:bg-slate-700 text-white px-3 py-2 rounded-lg shadow-lg transition-colors text-sm font-medium border border-slate-600"
      >
        {open ? "✕ Close" : "☰ Filters"}
      </button>

      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onToggle}
        />
      )}

      {/* Panel: full-screen drawer on mobile, floating card on desktop */}
      <div
        className={`
          fixed inset-x-0 bottom-0 z-50 max-h-[85vh] bg-slate-900/[0.98] backdrop-blur-lg rounded-t-2xl shadow-2xl border-t border-slate-700 transition-transform duration-300
          md:absolute md:top-14 md:left-3 md:bottom-auto md:right-auto md:inset-x-auto md:w-72 md:max-h-none md:rounded-xl md:border md:border-slate-700 md:shadow-2xl md:transition-all md:duration-300
          ${
            open
              ? "translate-y-0 md:opacity-100 md:translate-y-12 md:pointer-events-auto"
              : "translate-y-full md:opacity-0 md:-translate-y-2 md:pointer-events-none"
          }
        `}
      >
        {/* Mobile drag handle */}
        <div className="flex justify-center pt-3 pb-1 md:hidden">
          <div className="w-10 h-1 bg-slate-600 rounded-full" />
        </div>

        {/* Mobile header */}
        <div className="flex items-center justify-between px-5 py-2 md:hidden">
          <h3 className="text-base font-semibold text-white">Filters</h3>
          <button
            onClick={onToggle}
            className="text-slate-400 hover:text-white text-lg leading-none transition-colors p-1"
          >
            ✕
          </button>
        </div>

        <div className="p-5 pt-2 md:pt-5 space-y-5 overflow-y-auto max-h-[calc(85vh-4rem)] md:max-h-none">
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider hidden md:block">
            Filters
          </h3>

          {/* Subdividable toggle */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <div className="relative">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={subdividableOnly}
                onChange={(e) => onSubdividableChange(e.target.checked)}
              />
              <div className="w-10 h-5 bg-slate-600 rounded-full peer-checked:bg-green-500 transition-colors" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-5" />
            </div>
            <span className="text-sm text-slate-300 group-hover:text-white transition-colors">
              Subdividable only
            </span>
          </label>

          {/* Corner lots only */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <div className="relative">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={cornerOnly}
                onChange={(e) => onCornerOnlyChange(e.target.checked)}
              />
              <div className="w-10 h-5 bg-slate-600 rounded-full peer-checked:bg-blue-500 transition-colors" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-5" />
            </div>
            <span className="text-sm text-slate-300 group-hover:text-white transition-colors">
              Corner lots only
            </span>
          </label>

          {/* For sale only */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <div className="relative">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={forSaleOnly}
                onChange={(e) => onForSaleChange(e.target.checked)}
              />
              <div className="w-10 h-5 bg-slate-600 rounded-full peer-checked:bg-red-500 transition-colors" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-5" />
            </div>
            <span className="text-sm text-slate-300 group-hover:text-white transition-colors">
              For sale only
            </span>
          </label>

          {/* Zoning dropdown */}
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Zoning District
            </label>
            <select
              value={zoningFilter}
              onChange={(e) => onZoningChange(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            >
              <option value="">All Districts</option>
              {ZONING_OPTIONS.filter(Boolean).map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </div>

          {/* Min lots */}
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Min Possible Lots: {minLots === 0 ? "Any" : `${minLots}+`}
            </label>
            <input
              type="range"
              min={0}
              max={10}
              value={minLots}
              onChange={(e) => onMinLotsChange(Number(e.target.value))}
              className="w-full accent-green-500"
            />
          </div>

          <hr className="border-slate-700" />

          {/* Map Layers */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Map Layers
            </h3>
            <p className="text-[10px] text-slate-500 -mt-1">
              City utility infrastructure — zoom to z15+ to see
            </p>
            {UTILITY_LAYERS.map((layer) => (
              <div key={layer.id} className="space-y-1">
                <label className="flex items-center gap-3 cursor-pointer group">
                  <div className="relative">
                    <input
                      type="checkbox"
                      className="sr-only peer"
                      checked={utilityLayers[layer.id] || false}
                      onChange={(e) =>
                        onUtilityLayerToggle(layer.id, e.target.checked)
                      }
                    />
                    <div
                      className={`w-10 h-5 bg-slate-600 rounded-full ${LAYER_COLORS[layer.id] || "peer-checked:bg-cyan-500"} transition-colors`}
                    />
                    <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-5" />
                  </div>
                  <span className="text-sm text-slate-300 group-hover:text-white transition-colors flex items-center gap-1.5">
                    <span className="text-xs">{LAYER_ICONS[layer.id]}</span>
                    {layer.label}
                  </span>
                </label>
                {LAYER_DESCRIPTIONS[layer.id] && (
                  <p className="text-[10px] text-slate-500 leading-tight ml-[52px]">
                    {LAYER_DESCRIPTIONS[layer.id]}
                  </p>
                )}
              </div>
            ))}
          </div>

          <hr className="border-slate-700" />

          {/* Export */}
          <a
            href={getExportCSVUrl(subdividableOnly || undefined)}
            download
            className="block w-full text-center bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            Export CSV
          </a>

          {/* Bottom safe area padding on mobile */}
          <div className="h-4 md:h-0" />
        </div>
      </div>
    </>
  );
}
