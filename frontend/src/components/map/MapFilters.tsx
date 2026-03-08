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
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Transaction Group
        </label>
        <select
          value={selectedGroup}
          onChange={(e) => onGroupChange(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        >
          <option value="">All Groups</option>
          {transGroups.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Property Type
        </label>
        <select
          value={selectedType}
          onChange={(e) => onTypeChange(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        >
          <option value="">All Types</option>
          {propertyTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Year From
        </label>
        <input
          type="number"
          min={yearMin}
          max={yearMax}
          value={yearFrom}
          onChange={(e) => onYearFromChange(Number(e.target.value))}
          className="w-24 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">
          Year To
        </label>
        <input
          type="number"
          min={yearMin}
          max={yearMax}
          value={yearTo}
          onChange={(e) => onYearToChange(Number(e.target.value))}
          className="w-24 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </div>
    </div>
  );
}
