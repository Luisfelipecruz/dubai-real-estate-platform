"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { Circle, Flame, Hexagon } from "lucide-react";
import MapFilters from "@/components/map/MapFilters";
import TimeSlider from "@/components/map/TimeSlider";
import MapDetailPanel from "@/components/map/MapDetailPanel";

const DeckMap = dynamic(() => import("@/components/map/DeckMap"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center bg-[--muted]">
      <p className="text-[--muted-foreground]">Loading map...</p>
    </div>
  ),
});

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

interface Filters {
  trans_groups: string[];
  property_types: string[];
  year_min: number | null;
  year_max: number | null;
}

type ViewMode = "circles" | "heatmap" | "hexagon";

export default function MapPage() {
  const [features, setFeatures] = useState<MapFeature[]>([]);
  const [filters, setFilters] = useState<Filters | null>(null);
  const [selectedGroup, setSelectedGroup] = useState("");
  const [selectedType, setSelectedType] = useState("");
  const [yearFrom, setYearFrom] = useState(2000);
  const [yearTo, setYearTo] = useState(2026);
  const [loading, setLoading] = useState(true);
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>("circles");
  const [selectedArea, setSelectedArea] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/map/filters`)
      .then((r) => r.json())
      .then((data: Filters) => {
        setFilters(data);
        if (data.year_min) setYearFrom(data.year_min);
        if (data.year_max) setYearTo(data.year_max);
      })
      .catch(console.error);
  }, []);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (selectedGroup) params.set("trans_group", selectedGroup);
    if (selectedType) params.set("property_type", selectedType);
    if (yearFrom) params.set("year_from", String(yearFrom));
    if (yearTo) params.set("year_to", String(yearTo));

    fetch(`${API_URL}/map/transactions?${params}`)
      .then((r) => r.json())
      .then((data) => {
        setFeatures(data.features);
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setLoading(false);
      });
  }, [selectedGroup, selectedType, yearFrom, yearTo]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function handleToggleGroup(group: string) {
    setHiddenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }

  // Compute summary stats from visible features
  const visibleFeatures = features.filter((f) => !hiddenGroups.has(f.trans_group));
  const totalTransactions = visibleFeatures.reduce((s, f) => s + f.transaction_count, 0);
  const totalVolume = visibleFeatures.reduce((s, f) => s + f.total_volume, 0);
  const uniqueAreas = new Set(visibleFeatures.map((f) => f.area_name)).size;

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 3.5rem)" }}>
      {/* Top bar: filters + view toggle + stats */}
      <div className="shrink-0 border-b border-[--border] bg-[--background]">
        {filters && (
          <div className="flex flex-wrap items-center gap-4 px-4 py-2">
            <MapFilters
              transGroups={filters.trans_groups}
              propertyTypes={filters.property_types}
              yearMin={filters.year_min || 2000}
              yearMax={filters.year_max || 2026}
              selectedGroup={selectedGroup}
              selectedType={selectedType}
              yearFrom={yearFrom}
              yearTo={yearTo}
              onGroupChange={setSelectedGroup}
              onTypeChange={setSelectedType}
              onYearFromChange={setYearFrom}
              onYearToChange={setYearTo}
            />

            {/* Separator */}
            <div className="h-6 w-px bg-[--border] hidden sm:block" />

            {/* View toggle */}
            <div className="flex items-center gap-0.5 rounded-lg border border-[--border] bg-[--muted]/50 p-0.5">
              <button
                onClick={() => setViewMode("circles")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                  viewMode === "circles"
                    ? "bg-[--background] text-[--foreground] shadow-sm border border-[--border]"
                    : "text-[--muted-foreground] hover:text-[--foreground]"
                }`}
              >
                <Circle className="h-3.5 w-3.5" />
                Circles
              </button>
              <button
                onClick={() => setViewMode("heatmap")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                  viewMode === "heatmap"
                    ? "bg-[--background] text-[--foreground] shadow-sm border border-[--border]"
                    : "text-[--muted-foreground] hover:text-[--foreground]"
                }`}
              >
                <Flame className="h-3.5 w-3.5" />
                Heatmap
              </button>
              <button
                onClick={() => setViewMode("hexagon")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                  viewMode === "hexagon"
                    ? "bg-[--background] text-[--foreground] shadow-sm border border-[--border]"
                    : "text-[--muted-foreground] hover:text-[--foreground]"
                }`}
              >
                <Hexagon className="h-3.5 w-3.5" />
                3D Hexagon
              </button>
            </div>
          </div>
        )}

        {/* Time slider */}
        {filters && filters.year_min && filters.year_max && (
          <div className="border-t border-[--border]">
            <TimeSlider
              yearMin={filters.year_min}
              yearMax={filters.year_max}
              yearFrom={yearFrom}
              yearTo={yearTo}
              onYearFromChange={setYearFrom}
              onYearToChange={setYearTo}
            />
          </div>
        )}
      </div>

      {/* Map fills remaining space */}
      <div className="relative flex-1 min-h-0">
        {loading ? (
          <div className="flex h-full items-center justify-center bg-[--muted]">
            <p className="text-[--muted-foreground]">Loading data...</p>
          </div>
        ) : (
          <DeckMap
            features={features}
            hiddenGroups={hiddenGroups}
            viewMode={viewMode}
            onToggleGroup={handleToggleGroup}
            onAreaClick={setSelectedArea}
          />
        )}

        {/* Summary stats bar */}
        <div className="absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-4 rounded-lg bg-black/70 px-4 py-2 text-xs backdrop-blur-md border border-white/10 shadow-lg">
          <div className="text-center">
            <div className="font-semibold tabular-nums text-white">{uniqueAreas}</div>
            <div className="text-white/50">Areas</div>
          </div>
          <div className="h-6 w-px bg-white/15" />
          <div className="text-center">
            <div className="font-semibold tabular-nums text-white">
              {totalTransactions.toLocaleString()}
            </div>
            <div className="text-white/50">Transactions</div>
          </div>
          <div className="h-6 w-px bg-white/15" />
          <div className="text-center">
            <div className="font-semibold tabular-nums text-white">
              AED {totalVolume >= 1e9
                ? `${(totalVolume / 1e9).toFixed(1)}B`
                : totalVolume >= 1e6
                  ? `${(totalVolume / 1e6).toFixed(1)}M`
                  : totalVolume.toLocaleString()}
            </div>
            <div className="text-white/50">Volume</div>
          </div>
        </div>

        {/* Detail panel (slides in from right) */}
        {selectedArea && (
          <MapDetailPanel
            areaName={selectedArea}
            onClose={() => setSelectedArea(null)}
          />
        )}
      </div>
    </div>
  );
}
