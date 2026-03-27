import { useState, useEffect, useRef, useCallback } from "react";
import { fetchParcelsGeoJSON, type ParcelGeoJSON } from "../api/client";

const ZOOM_THRESHOLD_ALL_PARCELS = 15;

export function useParcelData(
  bbox: [number, number, number, number] | null,
  subdividableOnly: boolean,
  forSaleOnly: boolean = false,
  zoom: number = 12,
) {
  const [data, setData] = useState<ParcelGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const autoSubdividable = zoom < ZOOM_THRESHOLD_ALL_PARCELS;
  const effectiveSubdividable = subdividableOnly || autoSubdividable;

  const fetchData = useCallback(async () => {
    if (!bbox) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    try {
      const result = await fetchParcelsGeoJSON(
        bbox,
        effectiveSubdividable ? true : undefined,
        forSaleOnly ? true : undefined,
        autoSubdividable ? true : undefined
      );
      if (!controller.signal.aborted) {
        setData(result);
      }
    } catch {
      // ignore aborted requests
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [bbox?.[0], bbox?.[1], bbox?.[2], bbox?.[3], effectiveSubdividable, forSaleOnly, autoSubdividable]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(fetchData, 400);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchData]);

  return { data, loading, autoSubdividable };
}
