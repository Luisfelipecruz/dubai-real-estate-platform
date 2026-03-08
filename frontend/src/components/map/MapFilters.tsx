"use client";

interface MapFiltersProps {
  transGroups: string[];
  propertyTypes: string[];
  yearMin: number;
  yearMax: number;
  selectedGroup: string;
  selectedType: string;
  yearFrom: number;
  yearTo: number;
  onGroupChange: (v: string) => void;
  onTypeChange: (v: string) => void;
  onYearFromChange: (v: number) => void;
  onYearToChange: (v: number) => void;
}

export default function MapFilters({
  transGroups,
  propertyTypes,
  yearMin,
  yearMax,
  selectedGroup,
  selectedType,
  yearFrom,
  yearTo,
  onGroupChange,
  onTypeChange,
  onYearFromChange,
  onYearToChange,
}: MapFiltersProps) {
  const selectClass =
    "h-8 rounded-md border border-[--input] bg-[--background] px-2.5 text-sm text-[--foreground] focus:outline-none focus:ring-1 focus:ring-[--ring]";
  const inputClass =
    "h-8 w-20 rounded-md border border-[--input] bg-[--background] px-2.5 text-sm text-[--foreground] focus:outline-none focus:ring-1 focus:ring-[--ring]";

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1.5">
        <label className="text-xs font-medium text-[--muted-foreground]">Group</label>
        <select
          value={selectedGroup}
          onChange={(e) => onGroupChange(e.target.value)}
          className={selectClass}
        >
          <option value="">All</option>
          {transGroups.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-1.5">
        <label className="text-xs font-medium text-[--muted-foreground]">Type</label>
        <select
          value={selectedType}
          onChange={(e) => onTypeChange(e.target.value)}
          className={selectClass}
        >
          <option value="">All</option>
          {propertyTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-1.5">
        <label className="text-xs font-medium text-[--muted-foreground]">Year</label>
        <input
          type="number"
          min={yearMin}
          max={yearMax}
          value={yearFrom}
          onChange={(e) => onYearFromChange(Number(e.target.value))}
          className={inputClass}
        />
        <span className="text-xs text-[--muted-foreground]">–</span>
        <input
          type="number"
          min={yearMin}
          max={yearMax}
          value={yearTo}
          onChange={(e) => onYearToChange(Number(e.target.value))}
          className={inputClass}
        />
      </div>
    </div>
  );
}
