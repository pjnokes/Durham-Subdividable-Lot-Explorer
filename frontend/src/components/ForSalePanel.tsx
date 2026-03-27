import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { fetchForSaleListings, type ForSaleListing } from "../api/client";

function sanitizeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") return url;
  } catch { /* invalid URL */ }
  return null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSelectParcel: (
    parcelId: number,
    lng: number,
    lat: number,
    areaSqft: number | null
  ) => void;
  selectedParcelId: number | null;
}

export default function ForSalePanel({
  open,
  onClose,
  onSelectParcel,
  selectedParcelId,
}: Props) {
  const [listings, setListings] = useState<ForSaleListing[]>([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"all" | "subdividable">("all");
  const [activeIndex, setActiveIndex] = useState(0);
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetchForSaleListings()
      .then((data) => {
        setListings(data.items);
        setActiveIndex(0);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [open]);

  const filtered = useMemo(() => {
    if (tab === "subdividable")
      return listings.filter((l) => l.is_subdividable);
    return listings;
  }, [listings, tab]);

  const subdividableCount = useMemo(
    () => listings.filter((l) => l.is_subdividable).length,
    [listings]
  );

  const handleSelect = useCallback(
    (index: number) => {
      setActiveIndex(index);
      const item = filtered[index];
      if (item) {
        onSelectParcel(item.id, item.lng, item.lat, item.area_sqft);
      }
    },
    [filtered, onSelectParcel]
  );

  const handlePrev = useCallback(() => {
    handleSelect(Math.max(0, activeIndex - 1));
  }, [activeIndex, handleSelect]);

  const handleNext = useCallback(() => {
    handleSelect(Math.min(filtered.length - 1, activeIndex + 1));
  }, [activeIndex, filtered.length, handleSelect]);

  useEffect(() => {
    const card = cardRefs.current.get(activeIndex);
    card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeIndex]);

  useEffect(() => {
    if (selectedParcelId == null) return;
    const idx = filtered.findIndex((l) => l.id === selectedParcelId);
    if (idx >= 0 && idx !== activeIndex) {
      setActiveIndex(idx);
    }
  }, [selectedParcelId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40 md:hidden"
        onClick={onClose}
      />

      <div className="fixed left-0 right-0 bottom-0 z-50 max-h-[90vh] bg-slate-900/[0.98] backdrop-blur-lg border-t border-slate-700 shadow-2xl rounded-t-2xl flex flex-col md:absolute md:top-0 md:right-auto md:w-[380px] md:max-h-none md:rounded-none md:border-t-0 md:border-r md:z-30">
        {/* Mobile drag handle */}
        <div className="flex justify-center pt-3 pb-1 md:hidden">
          <div className="w-10 h-1 bg-slate-600 rounded-full" />
        </div>

        {/* Header */}
        <div className="px-5 py-3 border-b border-slate-700 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🏠</span>
              <h2 className="font-bold text-white text-base">For Sale Now</h2>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white text-lg leading-none transition-colors p-1"
            >
              ✕
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            {loading
              ? "Loading listings..."
              : `${listings.length} active listing${listings.length !== 1 ? "s" : ""} · ${subdividableCount} subdividable`}
          </p>
        </div>

        {/* Tabs */}
        <div className="flex px-5 py-2 gap-2 border-b border-slate-700/60 shrink-0">
          <button
            onClick={() => {
              setTab("all");
              setActiveIndex(0);
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === "all"
                ? "bg-slate-700 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            All ({listings.length})
          </button>
          <button
            onClick={() => {
              setTab("subdividable");
              setActiveIndex(0);
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === "subdividable"
                ? "bg-amber-500/20 text-amber-400"
                : "text-slate-400 hover:text-amber-400 hover:bg-amber-500/10"
            }`}
          >
            Subdividable ({subdividableCount})
          </button>
        </div>

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div
                  key={i}
                  className="h-24 bg-slate-800/60 rounded-lg animate-pulse"
                />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center text-slate-400 text-sm">
              No {tab === "subdividable" ? "subdividable " : ""}listings found
            </div>
          ) : (
            <div className="p-3 space-y-2">
              {filtered.map((item, i) => (
                <div
                  key={item.id}
                  ref={(el) => {
                    if (el) cardRefs.current.set(i, el);
                  }}
                  onClick={() => handleSelect(i)}
                  className={`rounded-lg border cursor-pointer transition-all duration-150 overflow-hidden ${
                    i === activeIndex
                      ? "bg-blue-500/10 border-blue-500/50 ring-1 ring-blue-500/30"
                      : "bg-slate-800/40 border-slate-700/50 hover:bg-slate-800/70 hover:border-slate-600"
                  }`}
                >
                  {/* Listing photo */}
                  {sanitizeUrl(item.photo_url) && (
                    <img
                      src={sanitizeUrl(item.photo_url)!}
                      alt={item.address || "Listing"}
                      className="w-full h-32 object-cover"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                  )}

                  <div className="p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-white truncate">
                          {item.address || "No address"}
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          {item.list_price != null && (
                            <span className="text-base font-bold text-white">
                              $
                              {Math.round(item.list_price).toLocaleString()}
                            </span>
                          )}
                          {item.days_on_market != null && (
                            <span
                              className={`text-[10px] ${item.days_on_market > 30 ? "text-amber-400" : "text-slate-400"}`}
                            >
                              {item.days_on_market}d
                            </span>
                          )}
                        </div>
                      </div>
                      {item.is_subdividable && (
                        <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded mt-0.5">
                          {item.num_possible_lots || "?"} lots
                        </span>
                      )}
                    </div>

                    {/* Stats row */}
                    <div className="flex items-center gap-2 mt-1.5 text-[11px] text-slate-400 flex-wrap">
                      {item.beds != null && <span>{item.beds}bd</span>}
                      {item.baths != null && <span>{item.baths}ba</span>}
                      {item.sqft != null && (
                        <span>{item.sqft.toLocaleString()}sf</span>
                      )}
                      <span className="text-slate-600">·</span>
                      <span>{item.zoning || "?"}</span>
                      {item.area_sqft != null && (
                        <>
                          <span className="text-slate-600">·</span>
                          <span>
                            {Math.round(item.area_sqft).toLocaleString()}sf lot
                          </span>
                        </>
                      )}
                    </div>

                    {/* Subdivision info */}
                    {item.is_subdividable && (
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <span className="text-green-400 text-[10px] font-semibold">
                          ✓ Subdividable
                        </span>
                        {item.subdivision_type && (
                          <span className="text-blue-400 text-[10px]">
                            ({item.subdivision_type.replace("_", " ")})
                          </span>
                        )}
                      </div>
                    )}

                    {/* Redfin link */}
                    {sanitizeUrl(item.redfin_url) && (
                      <a
                        href={sanitizeUrl(item.redfin_url)!}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 mt-2 text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        View on Redfin
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z" />
                          <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z" />
                        </svg>
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Navigation footer */}
        {filtered.length > 0 && !loading && (
          <div className="px-5 py-3 border-t border-slate-700 flex items-center justify-between shrink-0">
            <button
              onClick={handlePrev}
              disabled={activeIndex <= 0}
              className="flex items-center gap-1 text-sm text-slate-300 hover:text-white disabled:text-slate-600 disabled:cursor-not-allowed transition-colors"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
              Prev
            </button>
            <span className="text-xs text-slate-400">
              {activeIndex + 1} of {filtered.length}
            </span>
            <button
              onClick={handleNext}
              disabled={activeIndex >= filtered.length - 1}
              className="flex items-center gap-1 text-sm text-slate-300 hover:text-white disabled:text-slate-600 disabled:cursor-not-allowed transition-colors"
            >
              Next
              <svg
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        )}
      </div>
    </>
  );
}
