"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { AreaOverview } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Search, MapPin } from "lucide-react";

export default function AreasPage() {
  const [areas, setAreas] = useState<AreaOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    apiFetch<AreaOverview[]>("/areas")
      .then(setAreas)
      .catch(() => setAreas([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = search
    ? areas.filter((a) =>
        a.area_name_en.toLowerCase().includes(search.toLowerCase())
      )
    : areas;

  return (
    <div className="px-4 py-6 md:px-8 max-w-6xl mx-auto space-y-5">
      {/* Search + count */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[--muted-foreground]" />
          <input
            type="text"
            placeholder="Search areas..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 rounded-lg border border-[--border] bg-[--background] pl-9 pr-3 text-sm text-[--foreground] placeholder:text-[--muted-foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30"
          />
        </div>
        {!loading && (
          <span className="text-xs text-[--muted-foreground]">
            {filtered.length} of {areas.length} areas
          </span>
        )}
      </div>

      {/* Grid */}
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <Skeleton key={i} className="h-[140px] w-full rounded-xl" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-[--border] bg-[--background] px-4 py-10 text-center">
          <MapPin className="mx-auto h-8 w-8 text-[--muted-foreground] mb-2" />
          <p className="text-sm text-[--muted-foreground]">
            {search
              ? `No areas matching "${search}"`
              : "No area data available."}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((area) => (
            <Link
              key={area.area_name_en}
              href={`/areas/${encodeURIComponent(area.area_name_en)}`}
              className="group block"
            >
              <Card className="h-full p-5 transition-all hover:shadow-md hover:border-[--primary]/40">
                <h3 className="font-semibold text-[--foreground]">
                  {area.area_name_en}
                </h3>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                  <div>
                    <p className="text-lg font-semibold text-[--foreground] tabular-nums">
                      {area.transaction_count.toLocaleString()}
                    </p>
                    <p className="text-[--muted-foreground]">Transactions</p>
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-[--foreground] tabular-nums">
                      {area.rent_count.toLocaleString()}
                    </p>
                    <p className="text-[--muted-foreground]">Rents</p>
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-[--foreground] tabular-nums">
                      {area.valuation_count.toLocaleString()}
                    </p>
                    <p className="text-[--muted-foreground]">Valuations</p>
                  </div>
                </div>
                {area.avg_transaction_price != null && (
                  <p className="mt-3 text-xs text-[--muted-foreground]">
                    Avg transaction:{" "}
                    <span className="font-medium text-[--foreground]">
                      {area.avg_transaction_price.toLocaleString("en-US", {
                        maximumFractionDigits: 0,
                      })}{" "}
                      AED
                    </span>
                  </p>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
