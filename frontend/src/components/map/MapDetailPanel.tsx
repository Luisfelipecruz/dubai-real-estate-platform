"use client";

import { useEffect, useState } from "react";
import { X, TrendingUp, Home, FileText } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface DatasetStats {
  count: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  avg_area_sqm: number | null;
}

interface AreaSummary {
  area_name_en: string;
  transactions: DatasetStats;
  rents: DatasetStats;
  valuations: DatasetStats;
}

interface MapDetailPanelProps {
  areaName: string;
  onClose: () => void;
}

function formatAED(val: number | null): string {
  if (val == null) return "—";
  if (val >= 1e9) return `AED ${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6) return `AED ${(val / 1e6).toFixed(1)}M`;
  return `AED ${val.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1">
      <span className="text-white/50">{label}</span>
      <span className="font-medium tabular-nums text-white/90">{value}</span>
    </div>
  );
}

function SectionHeader({
  icon,
  iconColor,
  title,
  count,
}: {
  icon: React.ReactNode;
  iconColor: string;
  title: string;
  count: number;
}) {
  return (
    <div className="flex items-center gap-1.5 mb-2">
      <span style={{ color: iconColor }}>{icon}</span>
      <span className="font-semibold text-white/90">{title}</span>
      <span className="ml-auto text-white/40">{count.toLocaleString()}</span>
    </div>
  );
}

export default function MapDetailPanel({ areaName, onClose }: MapDetailPanelProps) {
  const [data, setData] = useState<AreaSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(false);
    fetch(`${API_URL}/areas/${encodeURIComponent(areaName)}/summary`)
      .then((r) => {
        if (!r.ok) throw new Error("Not found");
        return r.json();
      })
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, [areaName]);

  return (
    <div className="absolute top-0 right-0 bottom-0 w-80 bg-[#1a1a2e]/95 backdrop-blur-xl border-l border-white/10 shadow-2xl overflow-y-auto z-10 animate-slide-in">
      <style jsx>{`
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        .animate-slide-in {
          animation: slideIn 0.25s ease-out;
        }
      `}</style>

      {/* Header */}
      <div className="sticky top-0 flex items-center justify-between border-b border-white/10 bg-[#1a1a2e]/95 backdrop-blur-xl px-4 py-3 z-10">
        <h3 className="text-sm font-semibold text-white truncate pr-2">{areaName}</h3>
        <button
          onClick={onClose}
          className="rounded-md p-1 hover:bg-white/10 transition-colors shrink-0"
        >
          <X className="h-4 w-4 text-white/50" />
        </button>
      </div>

      <div className="p-4 space-y-5 text-xs">
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-lg bg-white/5 animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <p className="text-white/40 text-center py-6">
            No data available for this area.
          </p>
        ) : data ? (
          <>
            {/* Transactions */}
            <div>
              <SectionHeader
                icon={<TrendingUp className="h-3.5 w-3.5" />}
                iconColor="#3b82f6"
                title="Transactions"
                count={data.transactions.count}
              />
              <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 space-y-0.5">
                <StatRow label="Average" value={formatAED(data.transactions.avg_price)} />
                <StatRow label="Min" value={formatAED(data.transactions.min_price)} />
                <StatRow label="Max" value={formatAED(data.transactions.max_price)} />
                {data.transactions.avg_area_sqm != null && (
                  <StatRow label="Avg Area" value={`${data.transactions.avg_area_sqm.toLocaleString()} sqm`} />
                )}
              </div>
            </div>

            {/* Rents */}
            <div>
              <SectionHeader
                icon={<Home className="h-3.5 w-3.5" />}
                iconColor="#ea580c"
                title="Rent Contracts"
                count={data.rents.count}
              />
              <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 space-y-0.5">
                <StatRow label="Avg Annual" value={formatAED(data.rents.avg_price)} />
                <StatRow label="Min Annual" value={formatAED(data.rents.min_price)} />
                <StatRow label="Max Annual" value={formatAED(data.rents.max_price)} />
                {data.rents.avg_area_sqm != null && (
                  <StatRow label="Avg Area" value={`${data.rents.avg_area_sqm.toLocaleString()} sqm`} />
                )}
              </div>
            </div>

            {/* Valuations */}
            <div>
              <SectionHeader
                icon={<FileText className="h-3.5 w-3.5" />}
                iconColor="#10b981"
                title="Valuations"
                count={data.valuations.count}
              />
              <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 space-y-0.5">
                <StatRow label="Average" value={formatAED(data.valuations.avg_price)} />
                <StatRow label="Min" value={formatAED(data.valuations.min_price)} />
                <StatRow label="Max" value={formatAED(data.valuations.max_price)} />
                {data.valuations.avg_area_sqm != null && (
                  <StatRow label="Avg Area" value={`${data.valuations.avg_area_sqm.toLocaleString()} sqm`} />
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
