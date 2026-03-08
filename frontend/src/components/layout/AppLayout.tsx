"use client";

import React, { useState } from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import AppSidebar from "./AppSidebar";
import { cn } from "@/lib/utils";

const PAGE_TITLES: Record<string, { title: string; description: string }> = {
  "/": { title: "Dashboard", description: "Overview of Dubai Land Department data" },
  "/transactions": { title: "Transactions", description: "Browse DLD property transactions" },
  "/rents": { title: "Rent Contracts", description: "Browse Ejari rent contract registrations" },
  "/valuations": { title: "Valuations", description: "Browse DLD property valuations" },
  "/areas": { title: "Areas", description: "Explore Dubai real estate areas" },
  "/map": { title: "Map", description: "Geospatial view of transactions" },
  "/upload": { title: "Upload CSV", description: "Import DLD data files" },
};

function getPageMeta(pathname: string) {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname];
  const prefix = Object.keys(PAGE_TITLES).find(
    (key) => key !== "/" && pathname.startsWith(key)
  );
  return prefix ? PAGE_TITLES[prefix] : { title: "Dubai RE", description: "" };
}

interface AppLayoutProps {
  children: React.ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const meta = getPageMeta(pathname);
  const isFullPage = pathname === "/map";

  return (
    <div className="flex h-screen overflow-hidden bg-[--background]">
      <AppSidebar
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />

      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* Top header bar */}
        <header className={cn(
          "shrink-0 flex h-14 items-center gap-4 border-b border-[--border] bg-[--background]/95 backdrop-blur-sm px-4 md:px-6"
        )}>
          <button
            onClick={() => setMobileOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[--muted-foreground] hover:bg-[--accent] transition-colors md:hidden"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="flex flex-col justify-center">
            <h1 className="text-sm font-semibold text-[--foreground] leading-none">
              {meta.title}
            </h1>
            {meta.description && (
              <p className="text-xs text-[--muted-foreground] mt-0.5 hidden sm:block">
                {meta.description}
              </p>
            )}
          </div>
        </header>

        {/* Main content — full-page mode for map, scrollable for others */}
        <main className={cn(
          "flex-1 min-h-0",
          isFullPage ? "overflow-hidden" : "overflow-y-auto"
        )}>
          {children}
        </main>
      </div>
    </div>
  );
}
