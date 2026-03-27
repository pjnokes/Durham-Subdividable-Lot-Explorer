import { useState, useCallback } from "react";
import MapView from "./components/Map";
import StatsBar from "./components/StatsBar";
import FilterPanel from "./components/FilterPanel";
import ParcelDetailPanel from "./components/ParcelDetail";
import AddressSearch, { type FlyToTarget } from "./components/AddressSearch";
import ForSalePanel from "./components/ForSalePanel";
import NotificationBell from "./components/NotificationBell";
import { useIsMobile } from "./hooks/useIsMobile";

export interface FlyToState {
  lng: number;
  lat: number;
  zoom: number;
  key: number;
}

function zoomForArea(areaSqft: number | null): number {
  if (!areaSqft || areaSqft <= 0) return 17;
  if (areaSqft < 8_000) return 18;
  if (areaSqft < 25_000) return 17.5;
  if (areaSqft < 80_000) return 17;
  if (areaSqft < 200_000) return 16;
  return 15;
}

export default function App() {
  const isMobile = useIsMobile();
  const [filterOpen, setFilterOpen] = useState(false);
  const [subdividableOnly, setSubdividableOnly] = useState(false);
  const [cornerOnly, setCornerOnly] = useState(false);
  const [forSaleOnly, setForSaleOnly] = useState(false);
  const [zoningFilter, setZoningFilter] = useState("");
  const [minLots, setMinLots] = useState(0);
  const [selectedParcelId, setSelectedParcelId] = useState<number | null>(null);
  const [flyTo, setFlyTo] = useState<FlyToState | null>(null);
  const [forSaleOpen, setForSaleOpen] = useState(false);
  const [utilityLayers, setUtilityLayers] = useState<Record<string, boolean>>({
    "fire-hydrants": true,
    "stormwater-pipes": true,
    "stormwater-structures": true,
  });

  const handleUtilityLayerToggle = (layerId: string, enabled: boolean) => {
    setUtilityLayers((prev) => ({ ...prev, [layerId]: enabled }));
  };

  const handleParcelClick = useCallback(
    (id: number | null) => {
      setSelectedParcelId(id);
      if (id && isMobile) setFilterOpen(false);
    },
    [isMobile]
  );

  const handleSearchSelect = useCallback(
    (parcelId: number, target: FlyToTarget) => {
      setSelectedParcelId(parcelId);
      if (isMobile) setFilterOpen(false);
      setFlyTo({
        lng: target.lng,
        lat: target.lat,
        zoom: zoomForArea(target.area_sqft),
        key: Date.now(),
      });
    },
    [isMobile]
  );

  const handleForSaleSelect = useCallback(
    (parcelId: number, lng: number, lat: number, areaSqft: number | null) => {
      setSelectedParcelId(parcelId);
      setFlyTo({
        lng,
        lat,
        zoom: zoomForArea(areaSqft),
        key: Date.now(),
      });
    },
    []
  );

  return (
    <div className="w-full h-full flex flex-col">
      <StatsBar
        onForSaleClick={() => {
          setForSaleOpen((p) => {
            const next = !p;
            if (next) setForSaleOnly(true);
            return next;
          });
        }}
        forSaleOpen={forSaleOpen}
      />

      <div className="relative flex-1">
        <MapView
          subdividableOnly={subdividableOnly}
          cornerOnly={cornerOnly}
          forSaleOnly={forSaleOnly}
          zoningFilter={zoningFilter}
          minLots={minLots}
          selectedParcelId={selectedParcelId}
          onParcelClick={handleParcelClick}
          utilityLayers={utilityLayers}
          flyTo={flyTo}
        />

        <AddressSearch onSelect={handleSearchSelect} />

        {/* Notification bell — top-right, overlays the map */}
        <div className="absolute top-3 right-3 z-40">
          <NotificationBell />
        </div>

        <FilterPanel
          open={filterOpen}
          onToggle={() => setFilterOpen((p) => !p)}
          subdividableOnly={subdividableOnly}
          onSubdividableChange={setSubdividableOnly}
          cornerOnly={cornerOnly}
          onCornerOnlyChange={setCornerOnly}
          forSaleOnly={forSaleOnly}
          onForSaleChange={setForSaleOnly}
          zoningFilter={zoningFilter}
          onZoningChange={setZoningFilter}
          minLots={minLots}
          onMinLotsChange={setMinLots}
          utilityLayers={utilityLayers}
          onUtilityLayerToggle={handleUtilityLayerToggle}
        />

        <ForSalePanel
          open={forSaleOpen}
          onClose={() => setForSaleOpen(false)}
          onSelectParcel={handleForSaleSelect}
          selectedParcelId={selectedParcelId}
        />

        <ParcelDetailPanel
          parcelId={selectedParcelId}
          onClose={() => setSelectedParcelId(null)}
        />
      </div>
    </div>
  );
}
