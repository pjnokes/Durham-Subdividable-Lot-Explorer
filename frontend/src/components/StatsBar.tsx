import { useEffect, useState } from "react";
import { fetchStats, type AnalysisStats } from "../api/client";

interface Props {
  onForSaleClick: () => void;
  forSaleOpen: boolean;
}

export default function StatsBar({ onForSaleClick, forSaleOpen }: Props) {
  const [stats, setStats] = useState<AnalysisStats | null>(null);

  useEffect(() => {
    fetchStats().then(setStats).catch(console.error);
  }, []);

  if (!stats) {
    return (
      <div className="h-10 bg-slate-900/90 backdrop-blur border-b border-slate-700 flex items-center px-4">
        <div className="h-4 w-48 bg-slate-700 rounded animate-pulse" />
      </div>
    );
  }

  return (
    <div className="h-10 bg-slate-900/90 backdrop-blur border-b border-slate-700 flex items-center px-3 md:px-4 gap-3 md:gap-6 text-sm z-50 overflow-x-auto scrollbar-none">
      <span className="font-semibold text-white tracking-wide shrink-0">
        Durham Lot Finder
      </span>
      <span className="text-slate-400 hidden md:inline">|</span>
      <span className="shrink-0">
        <span className="text-slate-400 hidden md:inline">Parcels: </span>
        <span className="font-medium text-white">
          {stats.total_parcels.toLocaleString()}
        </span>
      </span>
      <span className="shrink-0">
        <span className="text-slate-400 hidden md:inline">Subdividable: </span>
        <span className="font-medium text-green-400">
          {stats.total_subdividable.toLocaleString()}
        </span>
        <span className="text-green-400 md:hidden text-xs"> sub</span>
      </span>
      <span className="shrink-0 hidden md:inline">
        <span className="text-slate-400">Small Lot: </span>
        <span className="text-teal-400">
          {(stats.by_subdivision_type?.small_lot || 0).toLocaleString()}
        </span>
      </span>
      <span className="shrink-0 hidden md:inline">
        <span className="text-slate-400">Standard: </span>
        <span className="text-green-300">
          {(stats.by_subdivision_type?.standard || 0).toLocaleString()}
        </span>
      </span>
      <span className="shrink-0 hidden md:inline">
        <span className="text-slate-400">Flag: </span>
        <span className="text-yellow-400">
          {(stats.by_subdivision_type?.flag_lot || 0).toLocaleString()}
        </span>
      </span>

      {/* Push right-side items */}
      <div className="flex-1 min-w-2" />

      <button
        onClick={onForSaleClick}
        className={`shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
          forSaleOpen
            ? "bg-red-500/20 text-red-400 border border-red-500/40"
            : "bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-600"
        }`}
      >
        <span className="hidden sm:inline">🏠</span>
        For Sale
      </button>
    </div>
  );
}
