"use client";

import { useCallback } from "react";

interface TimeSliderProps {
  yearMin: number;
  yearMax: number;
  yearFrom: number;
  yearTo: number;
  onYearFromChange: (year: number) => void;
  onYearToChange: (year: number) => void;
}

export default function TimeSlider({
  yearMin,
  yearMax,
  yearFrom,
  yearTo,
  onYearFromChange,
  onYearToChange,
}: TimeSliderProps) {
  const totalYears = yearMax - yearMin;
  const leftPct = totalYears > 0 ? ((yearFrom - yearMin) / totalYears) * 100 : 0;
  const rightPct = totalYears > 0 ? ((yearTo - yearMin) / totalYears) * 100 : 100;

  const handleFromChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = Number(e.target.value);
      if (val <= yearTo) onYearFromChange(val);
    },
    [yearTo, onYearFromChange]
  );

  const handleToChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = Number(e.target.value);
      if (val >= yearFrom) onYearToChange(val);
    },
    [yearFrom, onYearToChange]
  );

  return (
    <div className="flex items-center gap-3 px-4 py-2">
      <span className="text-xs font-medium text-[--muted-foreground] shrink-0">Time</span>

      <div className="flex flex-1 items-center gap-2 max-w-md">
        <span className="text-xs tabular-nums font-semibold text-[--foreground] w-10 text-center">{yearFrom}</span>

        <div className="relative flex-1 h-6">
          {/* Track background */}
          <div className="absolute top-1/2 left-0 right-0 h-1.5 -translate-y-1/2 rounded-full bg-[--muted]" />
          {/* Active range highlight */}
          <div
            className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full"
            style={{
              left: `${leftPct}%`,
              width: `${rightPct - leftPct}%`,
              backgroundColor: "var(--primary)",
              opacity: 0.6,
            }}
          />
          {/* From slider */}
          <input
            type="range"
            min={yearMin}
            max={yearMax}
            value={yearFrom}
            onChange={handleFromChange}
            className="absolute top-0 left-0 w-full h-6 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[--primary] [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-[--primary] [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:shadow-md [&::-moz-range-thumb]:cursor-pointer"
            style={{ zIndex: yearFrom > yearMin + totalYears / 2 ? 5 : 3 }}
          />
          {/* To slider */}
          <input
            type="range"
            min={yearMin}
            max={yearMax}
            value={yearTo}
            onChange={handleToChange}
            className="absolute top-0 left-0 w-full h-6 appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[--primary] [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-[--primary] [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:shadow-md [&::-moz-range-thumb]:cursor-pointer"
            style={{ zIndex: yearTo < yearMin + totalYears / 2 ? 5 : 4 }}
          />
        </div>

        <span className="text-xs tabular-nums font-semibold text-[--foreground] w-10 text-center">{yearTo}</span>
      </div>
    </div>
  );
}
