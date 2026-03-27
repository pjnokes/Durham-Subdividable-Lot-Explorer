import { useState, useEffect, useRef, useCallback } from "react";
import { fetchUtilityGeoJSON, type UtilityGeoJSON } from "../api/client";

export interface UtilityLayerConfig {
  id: string;
  label: string;
  layerType: string;
  color: [number, number, number, number];
  lineWidth: number;
  pointRadius: number;
  minZoom: number;
}

export const UTILITY_LAYERS: UtilityLayerConfig[] = [
  {
    id: "fire-hydrants",
    label: "Fire Hydrants",
    layerType: "fire_hydrant",
    color: [59, 130, 246, 220],
    lineWidth: 0,
    pointRadius: 4,
    minZoom: 15,
  },
  {
    id: "stormwater-pipes",
    label: "Stormwater Pipes",
    layerType: "stormwater_pipe",
    color: [34, 211, 238, 180],
    lineWidth: 2,
    pointRadius: 0,
    minZoom: 15,
  },
  {
    id: "stormwater-structures",
    label: "Stormwater Structures",
    layerType: "stormwater_structure",
    color: [34, 211, 238, 160],
    lineWidth: 0,
    pointRadius: 3,
    minZoom: 16,
  },
];

export function useUtilityLayers(
  bbox: [number, number, number, number] | null,
  zoom: number,
  enabledLayers: Record<string, boolean>
) {
  const [layerData, setLayerData] = useState<Record<string, UtilityGeoJSON>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeLayers = UTILITY_LAYERS.filter(
    (l) => enabledLayers[l.id] && zoom >= l.minZoom
  );
  const activeKey = activeLayers.map((l) => l.id).join(",");

  const fetchData = useCallback(async () => {
    if (!bbox || activeLayers.length === 0) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading((prev) => {
      const next = { ...prev };
      activeLayers.forEach((l) => (next[l.id] = true));
      return next;
    });

    const results = await Promise.allSettled(
      activeLayers.map(async (layer) => {
        const data = await fetchUtilityGeoJSON(bbox, layer.layerType);
        return { id: layer.id, data };
      })
    );

    if (controller.signal.aborted) return;

    const newData: Record<string, UtilityGeoJSON> = {};
    const newErrors: Record<string, boolean> = {};

    results.forEach((result, i) => {
      const layerId = activeLayers[i].id;
      if (result.status === "fulfilled" && result.value.data) {
        newData[layerId] = result.value.data;
        newErrors[layerId] = false;
      } else {
        newErrors[layerId] = true;
      }
    });

    setLayerData((prev) => ({ ...prev, ...newData }));
    setErrors((prev) => ({ ...prev, ...newErrors }));
    setLoading((prev) => {
      const next = { ...prev };
      activeLayers.forEach((l) => (next[l.id] = false));
      return next;
    });
  }, [bbox?.[0], bbox?.[1], bbox?.[2], bbox?.[3], activeKey]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!bbox || activeLayers.length === 0) return;
    timerRef.current = setTimeout(fetchData, 500);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchData]);

  useEffect(() => {
    setLayerData((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const layer of UTILITY_LAYERS) {
        if (!enabledLayers[layer.id] && next[layer.id]) {
          delete next[layer.id];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [...UTILITY_LAYERS.map((l) => enabledLayers[l.id])]);

  return { layerData, loading, errors };
}
