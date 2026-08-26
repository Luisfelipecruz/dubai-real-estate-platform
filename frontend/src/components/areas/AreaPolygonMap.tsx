"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer } from "@deck.gl/layers";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * The area's own boundary, fetched by name at FULL fidelity.
 *
 * `simplify=0` here on purpose. The map page simplifies to ~10 m because it draws
 * all 222 polygons and 963 KB of geometry is worth reducing; a single polygon is
 * ~92 vertices, so simplification buys nothing and only introduces error.
 */
export function AreaPolygonMap({ areaName }: { areaName: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [meta, setMeta] = useState<{ area_km2: number; vertices: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [55.22, 25.15],
      zoom: 9.5,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    mapRef.current = map;

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay as unknown as maplibregl.IControl);

    map.on("load", async () => {
      // Without this the canvas can size itself to a container that had not been
      // laid out when the map was constructed, and every tile renders into a 0x0
      // buffer -- a blank white box with no error anywhere.
      map.resize();
      try {
        const res = await fetch(
          `${API_URL}/communities/geojson?simplify=0&with_stats=false&name=${encodeURIComponent(areaName)}`
        );
        if (!res.ok) throw new Error(String(res.status));
        const fc = await res.json();
        if (cancelled) return;
        if (!fc.features?.length) {
          setState("missing");
          return;
        }

        const f = fc.features[0];
        setMeta({ area_km2: f.properties.area_km2, vertices: f.properties.vertices });

        overlay.setProps({
          layers: [
            new GeoJsonLayer({
              id: "area-polygon",
              data: fc,
              filled: true,
              stroked: true,
              getFillColor: [42, 120, 214, 90],
              getLineColor: [120, 175, 240, 230],
              lineWidthMinPixels: 2,
            }),
          ],
        });

        // fit to the polygon's own extent rather than guessing a zoom
        const b = new maplibregl.LngLatBounds();
        const walk = (c: unknown) => {
          if (typeof (c as number[])[0] === "number") {
            b.extend(c as [number, number]);
          } else {
            (c as unknown[]).forEach(walk);
          }
        };
        walk(f.geometry.coordinates);
        map.fitBounds(b, { padding: 36, duration: 0, maxZoom: 14 });
        setState("ready");
      } catch {
        if (!cancelled) setState("missing");
      }
    });

    return () => {
      cancelled = true;
      overlay.finalize();
      map.remove();
      mapRef.current = null;
    };
  }, [areaName]);

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <div className="flex items-baseline justify-between px-5 pt-4">
        <h2 className="text-sm font-semibold text-gray-900">Boundary</h2>
        {meta && (
          <p className="text-xs text-gray-500" style={{ fontVariantNumeric: "tabular-nums" }}>
            {meta.area_km2.toLocaleString()} km² · {meta.vertices} vertices
          </p>
        )}
      </div>
      <div className="relative mt-3 h-[320px] w-full">
        {/* Inline styles, not `absolute inset-0`: maplibre-gl.css sets
            `.maplibregl-map { position: relative }`, which lands after Tailwind in
            the cascade and silently beats the utility class -- the element then has
            nothing to resolve `inset-0` against and collapses to height 0, giving a
            blank white box with no error. DeckMap.tsx positions its container the
            same way for the same reason. */}
        <div
          ref={containerRef}
          style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
        />
        {state !== "ready" && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-white/85 px-6 text-center">
            <p className="text-sm text-gray-500">
              {state === "loading"
                ? "Loading boundary…"
                : "No community polygon matches this area name. 106 of the 221 transaction areas have one — the DLD community boundaries and the transaction area names are different vocabularies."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
