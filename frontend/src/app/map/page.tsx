"use client";

import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import MapFilters from "@/components/map/MapFilters";

const DeckMap = dynamic(() => import("@/components/map/DeckMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[600px] items-center justify-center rounded-lg border border-gray-200 bg-gray-50">
      <p className="text-gray-500">Loading map...</p>
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

  // Load filter options
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

  // Load map data
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
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">
        Transaction Map
      </h1>
      <p className="mt-1 text-sm text-gray-600">
        Visualize transactions by area. Circle size represents total volume, color represents transaction group.
      </p>

      {filters && (
        <div className="mt-4">
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

      <div className="mt-4">
        {loading ? (
          <div className="flex h-[600px] items-center justify-center rounded-lg border border-gray-200 bg-gray-50">
            <p className="text-gray-500">Loading data...</p>
          </div>
        ) : (
          <DeckMap features={features} />
        )}
      </div>

      <div className="mt-4 text-sm text-gray-500">
        Showing {features.length} area groups on map
      </div>
    </main>
  );
}
