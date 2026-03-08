"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ArrowLeftRight,
  FileText,
  Calculator,
  MapPin,
  Map,
  Upload,
  Building2,
  ChevronLeft,
  ChevronRight,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/transactions", label: "Transactions", icon: ArrowLeftRight, exact: false },
  { href: "/rents", label: "Rents", icon: FileText, exact: false },
  { href: "/valuations", label: "Valuations", icon: Calculator, exact: false },
  { href: "/areas", label: "Areas", icon: MapPin, exact: false },
  { href: "/map", label: "Map", icon: Map, exact: false },
  { href: "/upload", label: "Upload", icon: Upload, exact: false },
];

interface AppSidebarProps {
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export default function AppSidebar({ mobileOpen, onMobileClose }: AppSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  function isActive(item: typeof NAV_ITEMS[0]) {
    return item.exact ? pathname === item.href : pathname.startsWith(item.href);
  }

  const sidebarContent = (
    <div className={cn(
      "flex h-full flex-col bg-[--sidebar] border-r border-[--sidebar-border] transition-all duration-200",
      collapsed ? "w-[60px]" : "w-[240px]"
    )}>
      {/* Logo */}
      <div className={cn(
        "flex items-center gap-2.5 px-4 py-5",
        collapsed && "justify-center px-0"
      )}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-olive-700">
          <Building2 className="h-4 w-4 text-white" />
        </div>
        {!collapsed && (
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-bold text-[--sidebar-foreground]">Dubai RE</span>
            <span className="text-[10px] text-[--muted-foreground] font-medium tracking-wide uppercase">Intelligence</span>
          </div>
        )}
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4">
        <TooltipProvider delayDuration={0}>
          <ul className="flex flex-col gap-0.5 px-2">
            {NAV_ITEMS.map((item) => {
              const active = isActive(item);
              const Icon = item.icon;

              const linkEl = (
                <Link
                  href={item.href}
                  onClick={onMobileClose}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                    collapsed ? "justify-center px-2" : "",
                    active
                      ? "bg-olive-700 text-olive-50"
                      : "text-[--sidebar-foreground] hover:bg-[--sidebar-accent] hover:text-[--sidebar-accent-foreground]"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              );

              return (
                <li key={item.href}>
                  {collapsed ? (
                    <Tooltip>
                      <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
                      <TooltipContent side="right">{item.label}</TooltipContent>
                    </Tooltip>
                  ) : (
                    linkEl
                  )}
                </li>
              );
            })}
          </ul>
        </TooltipProvider>
      </nav>

      <Separator />

      {/* Collapse toggle */}
      <div className={cn("flex py-3 px-2", collapsed ? "justify-center" : "justify-end")}>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[--muted-foreground] hover:bg-[--sidebar-accent] hover:text-[--sidebar-accent-foreground] transition-colors"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:flex h-screen sticky top-0 shrink-0">
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40"
            onClick={onMobileClose}
            aria-hidden="true"
          />
          {/* Drawer */}
          <div className="relative flex h-full">
            {/* Force full width on mobile */}
            <div className="flex h-full flex-col bg-[--sidebar] border-r border-[--sidebar-border] w-[240px]">
              <div className="flex items-center justify-between px-4 py-5">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-olive-700">
                    <Building2 className="h-4 w-4 text-white" />
                  </div>
                  <div className="flex flex-col leading-tight">
                    <span className="text-sm font-bold text-[--sidebar-foreground]">Dubai RE</span>
                    <span className="text-[10px] text-[--muted-foreground] font-medium tracking-wide uppercase">Intelligence</span>
                  </div>
                </div>
                <button
                  onClick={onMobileClose}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[--muted-foreground] hover:bg-[--sidebar-accent] transition-colors"
                  aria-label="Close menu"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <Separator />

              <nav className="flex-1 overflow-y-auto py-4">
                <ul className="flex flex-col gap-0.5 px-2">
                  {NAV_ITEMS.map((item) => {
                    const active = isActive(item);
                    const Icon = item.icon;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          onClick={onMobileClose}
                          className={cn(
                            "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                            active
                              ? "bg-[--primary] text-white"
                              : "text-[--sidebar-foreground] hover:bg-[--sidebar-accent] hover:text-[--sidebar-accent-foreground]"
                          )}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <span>{item.label}</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </nav>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
