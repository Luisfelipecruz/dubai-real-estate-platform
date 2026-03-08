"use client";

import { useState } from "react";
import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

interface QualityCheck {
  check_name: string;
  category: string;
  dataset: string | null;
  status: "pass" | "fail" | "warn";
  message: string;
  value: number | null;
  threshold: number | null;
  checked_at: string | null;
}

interface QualityChecksPanelProps {
  checks: QualityCheck[];
}

function StatusIcon({ status }: { status: "pass" | "fail" | "warn" }) {
  if (status === "pass")
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />;
  if (status === "fail")
    return <XCircle className="h-3.5 w-3.5 text-red-600 shrink-0" />;
  return <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />;
}

export default function QualityChecksPanel({ checks }: QualityChecksPanelProps) {
  const passing = checks.filter((c) => c.status === "pass");
  const issues = checks.filter((c) => c.status !== "pass");

  type Tab = "issues" | "passing";
  const [activeTab, setActiveTab] = useState<Tab>(issues.length > 0 ? "issues" : "passing");

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "issues", label: "Issues", count: issues.length },
    { key: "passing", label: "Passing", count: passing.length },
  ];

  return (
    <div>
      {/* Tab bar */}
      <div
        className="flex border-b"
        style={{ borderColor: "var(--border)" }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className="relative px-4 py-2.5 text-xs font-semibold transition-colors"
            style={{
              color:
                activeTab === tab.key
                  ? "var(--foreground)"
                  : "var(--muted-foreground)",
            }}
          >
            <span className="flex items-center gap-1.5">
              {tab.label}
              <span
                className="inline-flex items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
                style={{
                  backgroundColor:
                    activeTab === tab.key
                      ? tab.key === "issues" && tab.count > 0
                        ? "#fcd34d"
                        : "var(--primary)"
                      : "var(--muted)",
                  color:
                    activeTab === tab.key
                      ? tab.key === "issues" && tab.count > 0
                        ? "#78350f"
                        : "var(--primary-foreground)"
                      : "var(--muted-foreground)",
                }}
              >
                {tab.count}
              </span>
            </span>
            {/* Active indicator */}
            {activeTab === tab.key && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5"
                style={{ backgroundColor: "var(--primary)" }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div className="max-h-[280px] overflow-y-auto">
        {activeTab === "issues" && (
          <>
            {issues.length === 0 ? (
              <div
                className="flex items-center gap-3 px-4 py-8 justify-center"
                style={{ color: "var(--muted-foreground)" }}
              >
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <span className="text-sm">No issues found</span>
              </div>
            ) : (
              <div className="divide-y" style={{ borderColor: "var(--border)" }}>
                {issues.map((check) => (
                  <div
                    key={check.check_name}
                    className="flex items-start gap-3 px-4 py-3"
                    style={{
                      backgroundColor:
                        check.status === "fail"
                          ? "rgba(254,242,242,0.5)"
                          : "rgba(255,251,235,0.5)",
                    }}
                  >
                    <StatusIcon status={check.status} />
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-xs font-mono font-semibold"
                        style={{
                          color:
                            check.status === "fail" ? "#991b1b" : "#78350f",
                        }}
                      >
                        {check.check_name}
                      </p>
                      <p
                        className="text-xs mt-0.5"
                        style={{
                          color:
                            check.status === "fail" ? "#b91c1c" : "#92400e",
                        }}
                      >
                        {check.message}
                      </p>
                    </div>
                    {check.dataset && (
                      <span
                        className="text-xs shrink-0"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        {check.dataset}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {activeTab === "passing" && (
          <>
            {passing.length === 0 ? (
              <div
                className="flex items-center justify-center px-4 py-8"
                style={{ color: "var(--muted-foreground)" }}
              >
                <span className="text-sm">No passing checks yet</span>
              </div>
            ) : (
              <div className="divide-y" style={{ borderColor: "var(--border)" }}>
                {passing.map((check) => (
                  <div
                    key={check.check_name}
                    className="flex items-center gap-3 px-4 py-2.5"
                  >
                    <StatusIcon status="pass" />
                    <span
                      className="text-xs font-mono flex-1 min-w-0"
                      style={{ color: "var(--foreground)" }}
                    >
                      {check.check_name}
                    </span>
                    {check.dataset && (
                      <span
                        className="text-xs shrink-0"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        {check.dataset}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
