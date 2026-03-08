"use client";

import { useRef, useEffect, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

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

interface DeckMapProps {
  features: MapFeature[];
}

const GROUP_COLORS: Record<string, string> = {
  Sales: "#3b82f6",
  Mortgage: "#ea580c",
  Gifts: "#10b981",
};
const DEFAULT_COLOR = "#9ca3af";

function featuresToGeoJSON(features: MapFeature[], maxVolume: number) {
  return {
    type: "FeatureCollection" as const,
    features: features.map((f) => ({
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [f.longitude, f.latitude],
      },
      properties: {
        area_name: f.area_name,
        trans_group: f.trans_group,
        transaction_count: f.transaction_count,
        avg_amount: f.avg_amount,
        total_volume: f.total_volume,
        avg_price_sqm: f.avg_price_sqm,
        earliest_date: f.earliest_date,
        latest_date: f.latest_date,
        color: GROUP_COLORS[f.trans_group] || DEFAULT_COLOR,
        // Radius between 6 and 40 based on volume
        radius: Math.max(6, Math.sqrt(f.total_volume / maxVolume) * 40),
      },
    })),
  };
}

export default function DeckMap({ features }: DeckMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [mapReady, setMapReady] = useState(false);

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
      center: [55.22, 25.15],
      zoom: 10.5,
      pitch: 0,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("load", () => {
      map.addSource("transactions", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "transaction-circles",
        type: "circle",
        source: "transactions",
        paint: {
          "circle-radius": ["get", "radius"],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.7,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-opacity": 0.5,
        },
      });

      // Hover popup
      const popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        maxWidth: "280px",
      });
      popupRef.current = popup;

      map.on("mouseenter", "transaction-circles", (e) => {
        map.getCanvas().style.cursor = "pointer";
        if (!e.features?.[0]) return;
        const props = e.features[0].properties;
        const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];

        popup
          .setLngLat(coords)
          .setHTML(
            `<div style="font-family: system-ui, sans-serif;">
              <p style="font-weight:600;margin:0 0 2px">${props.area_name}</p>
              <p style="color:#666;margin:0 0 6px;font-size:13px">${props.trans_group}</p>
              <div style="font-size:12px;color:#888;line-height:1.6">
                <div>Transactions: ${Number(props.transaction_count).toLocaleString()}</div>
                <div>Avg Amount: AED ${Number(props.avg_amount).toLocaleString()}</div>
                <div>Total Volume: AED ${Number(props.total_volume).toLocaleString()}</div>
                ${Number(props.avg_price_sqm) > 0 ? `<div>Avg Price/sqm: AED ${Number(props.avg_price_sqm).toLocaleString()}</div>` : ""}
                ${props.earliest_date && props.latest_date ? `<div>${props.earliest_date} — ${props.latest_date}</div>` : ""}
              </div>
            </div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "transaction-circles", () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });

      setMapReady(true);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update data when features change
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const source = mapRef.current.getSource("transactions") as maplibregl.GeoJSONSource;
    if (!source) return;
    const maxVolume = Math.max(...features.map((f) => f.total_volume), 1);
    source.setData(featuresToGeoJSON(features, maxVolume));
  }, [features, mapReady]);

  return (
    <div className="relative h-[600px] w-full rounded-lg overflow-hidden border border-gray-200">
      <div ref={containerRef} className="h-full w-full" />

      {/* Legend */}
      <div className="absolute bottom-4 left-4 rounded-lg border border-gray-200 bg-white/90 p-3 text-xs backdrop-blur">
        <p className="mb-1.5 font-medium text-gray-700">Transaction Group</p>
        {Object.entries(GROUP_COLORS).map(([name, color]) => (
          <div key={name} className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="text-gray-600">{name}</span>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-3 rounded-full"
            style={{ backgroundColor: DEFAULT_COLOR }}
          />
          <span className="text-gray-600">Other</span>
        </div>
        <p className="mt-2 text-gray-400">Circle size = total volume</p>
      </div>
    </div>
  );
}
