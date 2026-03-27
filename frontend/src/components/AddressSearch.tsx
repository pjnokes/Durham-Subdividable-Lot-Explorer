import { useState, useRef, useEffect, useCallback } from "react";
import {
  searchAddresses,
  type AddressSearchResult,
} from "../api/client";

export interface FlyToTarget {
  lng: number;
  lat: number;
  area_sqft: number | null;
}

interface Props {
  onSelect: (parcelId: number, target: FlyToTarget) => void;
}

export default function AddressSearch({ onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AddressSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const data = await searchAddresses(q, 10);
      setResults(data);
      setOpen(data.length > 0);
      setActiveIdx(-1);
    } catch {
      setResults([]);
      setOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInput = (value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 200);
  };

  const handleSelect = (r: AddressSearchResult) => {
    setQuery(r.address || "");
    setOpen(false);
    setResults([]);
    onSelect(r.id, { lng: r.lng, lat: r.lat, area_sqft: r.area_sqft });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      handleSelect(results[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div ref={containerRef} className="absolute top-3 left-1/2 -translate-x-1/2 z-50 w-[calc(100vw-5rem)] md:w-96 md:max-w-[calc(100vw-8rem)]">
      <div className="relative">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
          </svg>
        </div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search address..."
          className="w-full bg-slate-900/95 backdrop-blur border border-slate-600 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded-xl pl-9 pr-9 py-2.5 text-sm text-white placeholder-slate-400 outline-none shadow-xl"
        />
        {query && (
          <button
            onClick={() => {
              setQuery("");
              setResults([]);
              setOpen(false);
              inputRef.current?.focus();
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        )}
        {loading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-slate-500 border-t-blue-400 rounded-full animate-spin" />
          </div>
        )}
      </div>

      {open && results.length > 0 && (
        <ul className="mt-1 bg-slate-900/95 backdrop-blur border border-slate-700 rounded-xl shadow-2xl overflow-hidden max-h-80 overflow-y-auto">
          {results.map((r, i) => (
            <li
              key={r.id}
              onClick={() => handleSelect(r)}
              onMouseEnter={() => setActiveIdx(i)}
              className={`px-4 py-2.5 cursor-pointer flex items-center gap-3 border-b border-slate-800 last:border-0 transition-colors ${
                i === activeIdx ? "bg-slate-700/60" : "hover:bg-slate-800/60"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">
                  {r.address || "No address"}
                </div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {r.zoning || "?"} &middot;{" "}
                  {r.area_sqft ? `${Math.round(r.area_sqft).toLocaleString()} sf` : "?"}
                  {r.pin ? ` · ${r.pin}` : ""}
                </div>
              </div>
              {r.is_subdividable === true && (
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded">
                  subdiv
                </span>
              )}
              {r.is_subdividable === false && (
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-slate-500 bg-slate-500/10 px-1.5 py-0.5 rounded">
                  no
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
