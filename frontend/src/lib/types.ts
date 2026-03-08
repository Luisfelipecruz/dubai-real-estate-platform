// ── Query responses ────────────────────────────────────────

export interface PaginatedResponse<T> {
  total: number;
  limit: number;
  offset: number;
  data: T[];
}

export interface Transaction {
  id: number;
  transaction_id: string;
  instance_date: string | null;
  procedure_name_en: string | null;
  trans_group_en: string | null;
  property_type_en: string | null;
  property_sub_type_en: string | null;
  property_usage_en: string | null;
  reg_type_en: string | null;
  area_id: number | null;
  area_name_en: string | null;
  building_name_en: string | null;
  project_name_en: string | null;
  master_project_en: string | null;
  rooms_en: string | null;
  procedure_area: number | null;
  actual_worth: number | null;
  meter_sale_price: number | null;
  meter_rent_price: number | null;
  has_parking: boolean | null;
  nearest_metro_en: string | null;
  nearest_mall_en: string | null;
  nearest_landmark_en: string | null;
}

export interface RentContract {
  id: number;
  contract_id: string;
  line_number: number;
  contract_start_date: string | null;
  contract_end_date: string | null;
  contract_reg_type_en: string | null;
  contract_amount: number | null;
  annual_amount: number | null;
  ejari_property_type_en: string | null;
  ejari_property_sub_type_en: string | null;
  ejari_bus_property_type_en: string | null;
  property_usage_en: string | null;
  tenant_type_en: string | null;
  is_free_hold: boolean | null;
  area_id: number | null;
  area_name_en: string | null;
  project_name_en: string | null;
  master_project_en: string | null;
  no_of_prop: number | null;
  actual_area: number | null;
  nearest_metro_en: string | null;
  nearest_mall_en: string | null;
  nearest_landmark_en: string | null;
}

export interface Valuation {
  id: number;
  procedure_number: number;
  instance_date: string | null;
  procedure_name_en: string | null;
  procedure_year: number | null;
  property_type_en: string | null;
  property_sub_type_en: string | null;
  area_id: number | null;
  area_name_en: string | null;
  procedure_area: number | null;
  actual_area: number | null;
  actual_worth: number | null;
  property_total_value: number | null;
  row_status_code: string | null;
}

export interface AreaOverview {
  area_id: number | null;
  area_name_en: string;
  transaction_count: number;
  rent_count: number;
  valuation_count: number;
  avg_transaction_price: number | null;
  avg_rent_amount: number | null;
}

export interface AreaDatasetStats {
  count: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  avg_area_sqm: number | null;
}

export interface AreaSummary {
  area_name_en: string;
  transactions: AreaDatasetStats;
  rents: AreaDatasetStats;
  valuations: AreaDatasetStats;
}

// ── Upload responses ───────────────────────────────────────

export interface UploadResponse {
  dataset_type: string;
  filename: string;
  rows_received: number;
  rows_inserted: number;
  rows_duplicate: number;
  rows_rejected: number;
  status: string;
  error?: string;
}

export interface UploadLogEntry {
  id: number;
  dataset_type: string;
  filename: string | null;
  uploaded_at: string | null;
  rows_received: number | null;
  rows_inserted: number | null;
  rows_duplicate: number | null;
  rows_rejected: number | null;
  status: string | null;
}
