"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { HeatmapLayer, HexagonLayer } from "@deck.gl/aggregation-layers";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CommunityProperties {
  id: number;
  community_name_en: string;
  community_number: string | null;
  area_km2: number;
  vertices: number;
  /** the transaction table's own spelling -- 'Al Manara', not the KML's 'AL MANARA' */
  txn_area_name: string | null;
  transaction_count: number | null;
  avg_amount: number | null;
  avg_price_sqm: number | null;
}

interface MapFeature {
  area_name: string;
  area_id: number;
  trans_group: string;
  transaction_count: number;
  avg_amount: number;
  total_volume: number;
  avg_price_sqm: number;
  earliest_date: string | null;
  latest_date: string | null;
  latitude: number;
  longitude: number;
}

export type ViewMode = "circles" | "heatmap" | "hexagon" | "boundaries";

interface DeckMapProps {
  features: MapFeature[];
  hiddenGroups: Set<string>;
  viewMode: ViewMode;
  onToggleGroup: (group: string) => void;
  onAreaClick: (areaName: string) => void;
}

const GROUP_COLORS: Record<string, [number, number, number]> = {
  Sales: [59, 130, 246],
  Mortgage: [234, 88, 12],
  Gifts: [16, 185, 129],
};
const DEFAULT_COLOR: [number, number, number] = [156, 163, 175];

const GROUP_HEX: Record<string, string> = {
  Sales: "#3b82f6",
  Mortgage: "#ea580c",
  Gifts: "#10b981",
};
const DEFAULT_HEX = "#9ca3af";

const HEATMAP_COLOR_RANGE: [number, number, number, number][] = [
  [1, 152, 189, 255],
  [73, 227, 206, 255],
  [216, 254, 181, 255],
  [254, 237, 177, 255],
  [254, 173, 84, 255],
  [209, 55, 78, 255],
];

interface TooltipInfo {
  x: number;
  y: number;
  html: string;
}

export default function DeckMap({
  features,
  hiddenGroups,
  viewMode,
  onToggleGroup,
  onAreaClick,
}: DeckMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const [boundaries, setBoundaries] = useState<GeoJSON.FeatureCollection | null>(null);

  // Fetched lazily and kept, because the boundaries are static reference data —
  // they do not respond to the transaction filters the way /map/transactions does.
  // Simplified server-side to ~10 m: 963 KB and 34,326 vertices at full fidelity
  // becomes 144 KB and 4,900. See GET /communities/geojson.
  useEffect(() => {
    if (viewMode !== "boundaries" || boundaries) return;
    let cancelled = false;
    fetch(`${API_URL}/communities/geojson?simplify=0.0001`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        if (!cancelled) setBoundaries(d as GeoJSON.FeatureCollection);
      })
      .catch(() => {
        if (!cancelled) setBoundaries(null);
      });
    return () => {
      cancelled = true;
    };
  }, [viewMode, boundaries]);

  const visibleFeatures = features.filter(
    (f) => !hiddenGroups.has(f.trans_group)
  );

  // Ref for visible features so spatial lookup works in callbacks
  const visibleFeaturesRef = useRef(visibleFeatures);
  visibleFeaturesRef.current = visibleFeatures;

  const onAreaClickRef = useRef(onAreaClick);
  onAreaClickRef.current = onAreaClick;

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [55.22, 25.15],
      zoom: 10.5,
      pitch: 40,
      bearing: -10,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
    });
    map.addControl(overlay as unknown as maplibregl.IControl);
    overlayRef.current = overlay;

    map.on("load", () => {
      map.resize();
      setMapReady(true);
    });

    mapRef.current = map;

    return () => {
      overlay.finalize();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Spatial lookup for hexagon bins
  const findNearbyFeatures = useCallback(
    (lng: number, lat: number): MapFeature[] => {
      const R = 0.015; // ~1.5km
      return visibleFeaturesRef.current.filter(
        (f) =>
          Math.abs(f.longitude - lng) < R && Math.abs(f.latitude - lat) < R
      );
    },
    []
  );

  // Build tooltip HTML for a feature
  function featureTooltipHTML(d: MapFeature): string {
    return `<p style="font-weight:600;margin:0 0 2px">${d.area_name}</p>
      <p style="color:#aaa;margin:0 0 6px;font-size:13px">${d.trans_group}</p>
      <div style="font-size:12px;color:#999;line-height:1.6">
        <div>Transactions: ${d.transaction_count.toLocaleString()}</div>
        <div>Avg: AED ${d.avg_amount.toLocaleString()}</div>
        <div>Volume: AED ${d.total_volume.toLocaleString()}</div>
        ${d.avg_price_sqm > 0 ? `<div>Price/sqm: AED ${d.avg_price_sqm.toLocaleString()}</div>` : ""}
      </div>
      <p style="font-size:11px;color:#666;margin:4px 0 0">Click for details</p>`;
  }

  // Update deck.gl layers
  useEffect(() => {
    if (!mapReady || !overlayRef.current || !mapRef.current) return;

    const map = mapRef.current;
    const overlay = overlayRef.current;

    const maxVolume = Math.max(
      ...visibleFeatures.map((f) => f.total_volume),
      1
    );

    const layers: any[] = [];

    if (viewMode === "circles") {
      layers.push(
        new ScatterplotLayer({
          id: "scatterplot",
          data: visibleFeatures,
          getPosition: (d: MapFeature) => [d.longitude, d.latitude],
          getRadius: (d: MapFeature) =>
            Math.max(300, Math.sqrt(d.total_volume / maxVolume) * 3000),
          getFillColor: (d: MapFeature) => [
            ...(GROUP_COLORS[d.trans_group] || DEFAULT_COLOR),
            180,
          ] as [number, number, number, number],
          getLineColor: [255, 255, 255, 120],
          lineWidthMinPixels: 1,
          stroked: true,
          pickable: true,
          radiusMinPixels: 5,
          radiusMaxPixels: 60,
          onHover: (info: any) => {
            if (!info.object) {
              map.getCanvas().style.cursor = "";
              setTooltip(null);
              return;
            }
            map.getCanvas().style.cursor = "pointer";
            const d = info.object as MapFeature;
            setTooltip({ x: info.x, y: info.y, html: featureTooltipHTML(d) });
          },
          onClick: (info: any) => {
            if (info.object) {
              setTooltip(null);
              onAreaClickRef.current((info.object as MapFeature).area_name);
            }
          },
        })
      );
    } else if (viewMode === "heatmap") {
      layers.push(
        new HeatmapLayer({
          id: "heatmap",
          data: visibleFeatures,
          getPosition: (d: MapFeature) => [d.longitude, d.latitude],
          getWeight: (d: MapFeature) => d.total_volume,
          radiusPixels: 60,
          intensity: 1.5,
          threshold: 0.03,
          colorRange: HEATMAP_COLOR_RANGE,
          aggregation: "SUM",
        })
      );
      // Transparent scatterplot on top for interaction
      layers.push(
        new ScatterplotLayer({
          id: "heatmap-interaction",
          data: visibleFeatures,
          getPosition: (d: MapFeature) => [d.longitude, d.latitude],
          getRadius: 800,
          getFillColor: [0, 0, 0, 0],
          pickable: true,
          onHover: (info: any) => {
            if (!info.object) {
              map.getCanvas().style.cursor = "";
              setTooltip(null);
              return;
            }
            map.getCanvas().style.cursor = "pointer";
            const d = info.object as MapFeature;
            setTooltip({
              x: info.x,
              y: info.y,
              html: `<p style="font-weight:600;margin:0 0 2px">${d.area_name}</p>
                <p style="color:#aaa;margin:0 0 4px;font-size:13px">${d.trans_group} · AED ${d.total_volume.toLocaleString()}</p>
                <p style="font-size:11px;color:#666;margin:2px 0 0">Click for details</p>`,
            });
          },
          onClick: (info: any) => {
            if (info.object) {
              setTooltip(null);
              onAreaClickRef.current((info.object as MapFeature).area_name);
            }
          },
        })
      );
    } else if (viewMode === "hexagon") {
      layers.push(
        new HexagonLayer({
          id: "hexagon",
          data: visibleFeatures,
          getPosition: (d: MapFeature) => [d.longitude, d.latitude],
          getElevationWeight: (d: MapFeature) =>
            Math.log10(d.total_volume + 1),
          getColorWeight: (d: MapFeature) => d.total_volume,
          colorRange: HEATMAP_COLOR_RANGE,
          elevationRange: [0, 1500],
          elevationScale: 30,
          extruded: true,
          radius: 1000,
          coverage: 0.85,
          upperPercentile: 95,
          pickable: true,
          onHover: ((info: any) => {
            if (!info.object) {
              map.getCanvas().style.cursor = "";
              setTooltip(null);
              return true;
            }
            map.getCanvas().style.cursor = "pointer";
            // Use info.coordinate (screen→world), fallback to object.position
            const coord = info.coordinate ?? info.object?.position;
            if (!coord) { setTooltip(null); return true; }
            const nearby = findNearbyFeatures(coord[0], coord[1]);
            const areaNames = [...new Set(nearby.map((f) => f.area_name))];
            const totalVol = nearby.reduce((s, f) => s + f.total_volume, 0);
            const totalTx = nearby.reduce((s, f) => s + f.transaction_count, 0);
            const areaList =
              areaNames.length > 0
                ? areaNames.length <= 4
                  ? areaNames.join(", ")
                  : `${areaNames.slice(0, 3).join(", ")} +${areaNames.length - 3} more`
                : `${info.object.count ?? 0} data points`;
            setTooltip({
              x: info.x,
              y: info.y,
              html: `<p style="font-weight:600;margin:0 0 4px">${areaList}</p>
                <div style="font-size:12px;color:#999;line-height:1.6">
                  <div>Transactions: ${(totalTx || info.object.count || 0).toLocaleString()}</div>
                  <div>Volume: AED ${(totalVol || info.object.colorValue || 0).toLocaleString()}</div>
                </div>
                ${areaNames.length >= 1 ? '<p style="font-size:11px;color:#666;margin:4px 0 0">Click for details</p>' : ""}`,
            });
            return true;
          }) as any,
          onClick: ((info: any) => {
            if (!info.object) return true;
            const coord = info.coordinate ?? info.object?.position;
            if (!coord) return true;
            const nearby = findNearbyFeatures(coord[0], coord[1]);
            const areaNames = [...new Set(nearby.map((f) => f.area_name))];
            if (areaNames.length >= 1) {
              setTooltip(null);
              // Use setTimeout to ensure state update propagates
              setTimeout(() => onAreaClickRef.current(areaNames[0]), 0);
            }
            return true;
          }) as any,
        })
      );
    } else if (viewMode === "boundaries" && boundaries) {
      // Choropleth over the real community polygons. 116 of the 222 have no
      // transaction data at all -- only 106 community names match a transaction
      // area name -- so those render grey rather than being coloured as if they
      // were the cheapest. An unmatched polygon is missing data, not a zero.
      const priced = boundaries.features
        .map((f) => (f.properties as CommunityProperties)?.avg_price_sqm)
        .filter((v): v is number => typeof v === "number" && v > 0)
        .sort((a, b) => a - b);
      // Percentile clamp, not min/max: a handful of areas have price/sqm two
      // orders of magnitude above the median and would otherwise flatten the
      // entire ramp into its first colour.
      const lo = priced.length ? priced[Math.floor(priced.length * 0.05)] : 0;
      const hi = priced.length ? priced[Math.floor(priced.length * 0.95)] : 1;

      layers.push(
        new GeoJsonLayer({
          id: "community-boundaries",
          data: boundaries,
          filled: true,
          stroked: true,
          getFillColor: (f: any) => {
            const p = f.properties as CommunityProperties;
            // Deliberately light enough to read as a *filled* polygon over the dark
            // basemap. At a lower alpha these looked like holes in the map, which
            // reads as "no polygon here" rather than "polygon with no data" -- the
            // opposite of the point.
            if (!p.avg_price_sqm || p.avg_price_sqm <= 0) return [125, 133, 148, 120];
            const t = Math.max(0, Math.min(1, (p.avg_price_sqm - lo) / Math.max(1, hi - lo)));
            const idx = Math.min(
              HEATMAP_COLOR_RANGE.length - 1,
              Math.floor(t * HEATMAP_COLOR_RANGE.length)
            );
            const [r, g, b] = HEATMAP_COLOR_RANGE[idx];
            return [r, g, b, 165];
          },
          getLineColor: [255, 255, 255, 140],
          lineWidthMinPixels: 1,
          pickable: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 60],
          onHover: (info: any) => {
            if (!info.object) {
              map.getCanvas().style.cursor = "";
              setTooltip(null);
              return;
            }
            map.getCanvas().style.cursor = "pointer";
            const p = info.object.properties as CommunityProperties;
            setTooltip({
              x: info.x,
              y: info.y,
              html: `<p style="font-weight:600;margin:0 0 2px">${p.community_name_en}</p>
                <p style="color:#aaa;margin:0 0 6px;font-size:13px">${p.area_km2.toLocaleString()} km²</p>
                <div style="font-size:12px;color:#999;line-height:1.6">
                  ${
                    p.transaction_count
                      ? `<div>Transactions: ${p.transaction_count.toLocaleString()}</div>
                         <div>Avg: AED ${Math.round(p.avg_amount ?? 0).toLocaleString()}</div>
                         ${p.avg_price_sqm ? `<div>Price/sqm: AED ${Math.round(p.avg_price_sqm).toLocaleString()}</div>` : ""}`
                      : `<div style="color:#777">No transactions matched to this polygon</div>`
                  }
                </div>
                ${p.transaction_count ? '<p style="font-size:11px;color:#666;margin:4px 0 0">Click for details</p>' : ""}`,
            });
          },
          onClick: (info: any) => {
            const p = info.object?.properties as CommunityProperties | undefined;
            // Drill through on the TRANSACTION-side name, not the polygon's. The
            // KML says 'AL MANARA' and the DLD CSV says 'Al Manara', and the detail
            // panel queries the transaction tables -- handing it the polygon's
            // spelling returned 200 with every count zeroed and an empty panel.
            const name = p?.txn_area_name ?? p?.community_name_en;
            if (p?.transaction_count && name) {
              setTooltip(null);
              onAreaClickRef.current(name);
            }
          },
        })
      );
    }

    overlay.setProps({ layers });
  }, [visibleFeatures, viewMode, mapReady, findNearbyFeatures, boundaries]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      />

      {/* Custom tooltip rendered on top of everything */}
      {tooltip && (
        <div
          className="pointer-events-none absolute z-50 max-w-[280px] rounded-lg border border-white/15 bg-[#1a1a2e]/95 px-3 py-2.5 text-sm text-white shadow-xl backdrop-blur-md"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 12,
            fontFamily: "system-ui, sans-serif",
          }}
          dangerouslySetInnerHTML={{ __html: tooltip.html }}
        />
      )}

      {/* Legend — different content per view mode */}
      <div className="absolute bottom-4 left-4 rounded-lg border border-white/10 bg-black/70 p-3 text-xs backdrop-blur-md z-10">
        {viewMode === "circles" ? (
          <>
            <p className="mb-1.5 font-medium text-white/80">Transaction Group</p>
            {Object.entries(GROUP_HEX).map(([name, color]) => {
              const hidden = hiddenGroups.has(name);
              return (
                <button
                  key={name}
                  onClick={() => onToggleGroup(name)}
                  className="flex w-full items-center gap-2 rounded px-1 py-0.5 transition-colors hover:bg-white/10"
                  style={{ opacity: hidden ? 0.35 : 1 }}
                >
                  <span
                    className="inline-block h-3 w-3 rounded-full shrink-0"
                    style={{ backgroundColor: hidden ? "#555" : color }}
                  />
                  <span
                    className="text-white/70"
                    style={{ textDecoration: hidden ? "line-through" : "none" }}
                  >
                    {name}
                  </span>
                </button>
              );
            })}
            <button
              onClick={() => onToggleGroup("Other")}
              className="flex w-full items-center gap-2 rounded px-1 py-0.5 transition-colors hover:bg-white/10"
              style={{ opacity: hiddenGroups.has("Other") ? 0.35 : 1 }}
            >
              <span
                className="inline-block h-3 w-3 rounded-full shrink-0"
                style={{ backgroundColor: hiddenGroups.has("Other") ? "#555" : DEFAULT_HEX }}
              />
              <span
                className="text-white/70"
                style={{ textDecoration: hiddenGroups.has("Other") ? "line-through" : "none" }}
              >
                Other
              </span>
            </button>
            <p className="mt-2 text-white/40">Circle size = total volume</p>
          </>
        ) : viewMode === "boundaries" ? (
          <>
            <p className="mb-1.5 font-medium text-white/80">Avg price / m²</p>
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-white/40">Low</span>
              <div
                className="h-2.5 flex-1 rounded-full"
                style={{
                  background:
                    "linear-gradient(to right, rgb(1,152,189), rgb(73,227,206), rgb(216,254,181), rgb(254,237,177), rgb(254,173,84), rgb(209,55,78))",
                }}
              />
              <span className="text-white/40">High</span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 rounded-sm shrink-0 border border-white/20"
                style={{ backgroundColor: "rgba(125,133,148,0.75)" }}
              />
              <span className="text-white/40">No transactions matched</span>
            </div>
            <p className="mt-1.5 text-white/40">222 community polygons · ~10 m simplified</p>
          </>
        ) : (
          <>
            <p className="mb-1.5 font-medium text-white/80">Transaction Volume</p>
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-white/40">Low</span>
              <div
                className="h-2.5 flex-1 rounded-full"
                style={{
                  background: "linear-gradient(to right, rgb(1,152,189), rgb(73,227,206), rgb(216,254,181), rgb(254,237,177), rgb(254,173,84), rgb(209,55,78))",
                }}
              />
              <span className="text-white/40">High</span>
            </div>
            <p className="mt-1.5 text-white/40">
              {viewMode === "heatmap"
                ? "Density = aggregated volume"
                : "Height & color = aggregated volume"}
            </p>
            <p className="mt-1 text-white/40">
              Click {viewMode === "heatmap" ? "area" : "hexagon"} for details
            </p>
          </>
        )}
      </div>
    </div>
  );
}
