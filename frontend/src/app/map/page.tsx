"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import MapFilters from "@/components/map/MapFilters";

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

export default function MapPage() {
  const [features, setFeatures] = useState<MapFeature[]>([]);
  const [filters, setFilters] = useState<Filters | null>(null);
  const [selectedGroup, setSelectedGroup] = useState("");
  const [selectedType, setSelectedType] = useState("");
  const [yearFrom, setYearFrom] = useState(2000);
  const [yearTo, setYearTo] = useState(2026);
  const [loading, setLoading] = useState(true);

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

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 3.5rem)" }}>
      {/* Compact filter bar */}
      {filters && (
        <div className="shrink-0 border-b border-[--border] bg-[--background] px-4 py-2">
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
        </div>
      )}

      {/* Map fills remaining space */}
      <div className="relative flex-1 min-h-0">
        {loading ? (
          <div className="flex h-full items-center justify-center bg-[--muted]">
            <p className="text-[--muted-foreground]">Loading data...</p>
          </div>
        ) : (
          <DeckMap features={features} />
        )}

        {/* Area count badge */}
        <div className="absolute top-3 right-3 rounded-md bg-[--background]/90 px-2.5 py-1 text-xs text-[--muted-foreground] backdrop-blur-sm border border-[--border]">
          {features.length} areas
        </div>
      </div>
    </div>
  );
}
