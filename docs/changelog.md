# Changelog

## v0.6.0 - The area page gets a boundary and a history (2026-08-15)

The area detail page was three stat cards. It now shows the area's own polygon and an
18-year sales history. **27 REST operations · 76 tests.**

### Added
- `GET /areas/{area_name}/history` -- yearly median price per m², median price and sale
  counts, plus rent counts and median rent, with `is_partial` per period.
- `?name=` on `GET /communities/geojson`, so a detail page fetches one polygon instead
  of all 222. A single polygon is ~92 vertices, so it is requested at `simplify=0`:
  simplification exists to shrink the 222-polygon payload and buys nothing for one.
- `AreaPolygonMap` -- the boundary on a basemap, fitted to its own extent.
- `AreaHistoryChart` -- two small multiples (price line, volume bars), no dependency added.

### The chart decisions, and why
- **Two charts, not one dual-axis chart.** Price and volume have different units; two
  y-scales let you manufacture whatever correlation you want by choosing the scales.
- **Median (`PERCENTILE_CONT`), not mean.** One area carries a single AED 6.75 bn
  transaction; a yearly mean charts outliers.
- **The incomplete year is marked, not dropped.** Data stops mid-February, so the current
  year's counts sit far below a full year and read as a crash. It renders with a dashed
  line segment and a pale bar. `is_partial` is computed by comparing the period end against
  the last date actually present, not hardcoded.
- **Rents are deliberately NOT plotted.** Every contract in the export was *registered*
  between 2026-01-01 and 2026-08-14 -- it is a snapshot of active contracts, not a history.
  Plotting counts by `contract_start_date` draws a fake 20x hockey stick (650 in 2019,
  34,123 in 2025, 320,400 in 2026), because early years hold only the few long-running
  contracts still active at export time. The API exposes `rents_are_historical`, computed
  from the number of distinct registration years, so it flips on its own if a future load
  really does span several. There is even a contract with a 1925 start date.
- Palette validated against the actual `#ffffff` card surface rather than assumed.

### Fixed
- **The boundary map rendered as a blank white box.** `maplibre-gl.css` sets
  `.maplibregl-map { position: relative }`, which lands after Tailwind in the cascade and
  silently beats an `absolute` utility class -- the container then had nothing to resolve
  `inset-0` against and collapsed to `height: 0` while its canvas reported 990x300. No
  error anywhere. Fixed with inline positioning styles, which is why `DeckMap.tsx` has
  always done it that way. `map.resize()` on load alone did **not** fix it; the container
  was the problem, not the canvas.
- Chart tooltip no longer covers the caption or the most recent years -- it offsets below
  the title and flips to the side the cursor is not on.

## v0.5.0 - Rents and valuations loaded; the platform becomes cross-dataset (2026-08-15)

`raw_rent_contracts` and `raw_valuations` had been **empty since the project started**, which
meant rental yield -- the headline analytic -- was not computable, 3 of the 4 Spark jobs in
`processing_pipeline` would have produced nothing, and 2 Airflow quality checks failed. The
files were finally exported from the DLD portal. They did not fit.

### The portal export is a different schema wearing the same name
`ingest.py` was built for the DLD **bulk** open-data files. The portal's interactive export is
a different dialect: UPPERCASE abbreviated headers (`AREA_EN` not `area_name_en`, `TRANS_VALUE`
not `actual_worth`), a UTF-8 **BOM** on the first header, no `area_id` anywhere, and -- for
rents -- **no contract identifier at all**. Added `scripts/load_portal_exports.py` rather than
teaching `ingest.py` two dialects and risking the bulk path the suite covers.

### Added
- `scripts/load_portal_exports.py` -- maps the portal dialect onto the existing tables with the
  same `ON CONFLICT DO NOTHING` semantics.
- **358,008 rent contracts** and **3,106 valuations** loaded.

### The synthetic rent key
`raw_rent_contracts` is `(contract_id, line_number)` NOT NULL UNIQUE and the export has neither.
Dropping the constraint was the easy fix and the wrong one -- it is what makes re-ingestion
idempotent. The key is instead **derived**: `md5` over the columns that identify a contract in
the real world, with `line_number` disambiguating genuinely identical rows. Verified: a second
run over the same files inserts **0** rows, all 361,126 absorbed by `ON CONFLICT`. The honest
limitation is that an amended row upstream hashes differently and lands as a new row -- a derived
key cannot track an update it was never given an identifier for.

### Measured
- **Valuations carry 12 duplicate `(procedure_number, instance_date)` pairs**, which is exactly
  the table's unique constraint: 3,118 read, **3,106** inserted, 12 absorbed.
- **`annual_amount` is the CONTRACT total, not the per-property rent**, and one contract can
  cover hundreds of properties -- each getting its own row carrying the full portfolio amount.
  The row counts prove it: `no_of_prop=232` appears exactly **232** times, `no_of_prop=205`
  appears **410** times (2 portfolios), `no_of_prop=408` appears **1,224** (3 portfolios).
  Dividing by `no_of_prop` moved gross yields from an impossible **208%** to a credible
  **7.6-9.9%** (Burj Khalifa 7.78%: AED 2.93M avg sale against AED 227,852 avg rent).
  **Any yield computed off raw `annual_amount` is wrong.**
- Airflow `quality_checks`: **13 pass / 4 warn / 0 fail**, from 13/2/2. The 2 failures are gone;
  the new warn is `cross_dataset_coverage` at 42% (94 shared areas), because the rents export
  covers only **96** areas against the transactions' 221.
- Area vocabulary overlap with the existing transactions: rents **94/96**, valuations **177/184**.
- `/areas` now returns **229** rows -- the FULL OUTER JOIN surfaces areas present only in rents
  or valuations.

### Not loaded, deliberately
`transactions-2026-08-15.csv` (134,150 rows) was **not** ingested. `TRANSACTION_NUMBER` is not
unique (the first two rows share `101-10-2026`), it has no `area_id` and no `meter_sale_price`,
and it uses a different transliteration -- only **76 of its 176** area names appear in the
existing data (`AL BARSHAA SOUTH THIRD` vs `AL BARSHA SOUTH THIRD`). The loaded 200k slice of
the 1.02 GB bulk file is richer and larger; merging this would have degraded it.

## v0.4.0 - The polygons become visible (2026-08-15)

Until now the 222 community polygons did real work in Postgres -- point-in-polygon
containment, radius search, adjacency, overlap, dissolve -- and **nothing rendered them**.
Every endpoint reduced geometry to a derived scalar before it left the database
(`ST_Centroid` for a map pin, `ST_Area` for a number); there was no `ST_AsGeoJSON`
anywhere in the API, and the deck.gl map had only `ScatterplotLayer`, `HeatmapLayer`
and `HexagonLayer`. The map drew dots on top of boundary data it never showed.

### Fixed (data-quality, found by rendering the data)
- **`/areas` emitted duplicate names.** `Mushrif` exists under **two different `area_id`s**
  (404 with 33 transactions, 420 with 1), and the list grouped by `(area_id, area_name_en)` --
  223 rows for 222 distinct names, which React rejected with a duplicate-key error. Both cards
  linked to the same `/areas/Mushrif`, which aggregates by name and already showed the combined
  34, so the list was contradicting the detail page. Now one row per normalised name.
- **Latent fan-out in the same query.** The `FULL OUTER JOIN`s matched on name while the
  subqueries grouped by `(area_id, area_name_en)`. Harmless only because rents and valuations
  are empty; the moment they load, a name with two ids on both sides is a cartesian product.
- **`Al Qusais` and `AL QUSAIS` were two rows for one place** (69 transactions). Normalising the
  group key merges them -- so there are **221 distinct areas, not 222**. The 222 in the
  transaction data counts *spellings*; the 222 in `communities` counts *polygons*. They are
  unrelated numbers that happen to be equal.
- **`/areas/{name}/summary` matched case-sensitively**, returning HTTP 200 with every count
  zeroed for `AL MANARA` while `Al Manara` returned 128 transactions. The map's boundary layer
  clicked through with the polygon's spelling and opened an empty detail panel with no error
  anywhere. Now normalised on both sides, and `/communities/geojson` carries `txn_area_name`
  so a client never has to guess the transaction-side spelling.
- 4 more tests (**68 total**).

### Added
- `GET /communities/geojson` -- the boundaries as a real GeoJSON `FeatureCollection`,
  consumable directly by deck.gl, Leaflet or QGIS. Optional `simplify` tolerance and
  `with_stats` join for choropleth fills. **26 REST operations** (was 25).
- **Boundaries view mode** on the map: a `GeoJsonLayer` choropleth shaded by average
  price per m², with its own legend and hover card.
- `docs/polygon-simplification.md` -- what simplification buys and what it silently breaks.
- 6 new tests (**64 total**, all passing).

### Measured
- Full fidelity: **1,012,960 bytes / 34,326 vertices**; heaviest single polygon 2,247.
- Simplified to 0.0001 deg (~10 m): **193,887 bytes / 4,900 vertices**. Geometry alone
  963,041 -> 144,093 bytes, **6.7x**. All 222 features survive.
- **Simplification breaks shared borders.** Re-running the DE-9IM pair counts: at ~10 m,
  **176 of the 483 touching pairs (36%) migrate from `ST_Touches` to `ST_Overlaps`** --
  each side of a shared edge is decimated independently, so boundaries that met exactly
  now cross. `ST_Intersects` holds at 614, so adjacency is still complete, only mislabelled.
  At 0.0005 deg `ST_Intersects` falls to **606**: 8 neighbour relationships vanish outright.
- Rule adopted: **simplify for display, never for analysis.** Every adjacency, area and
  overlap endpoint reads the unsimplified `geom`, and `area_km2` in the GeoJSON response is
  computed from the original geometry even when the geometry beside it is simplified.
  A test asserts those areas are identical across tolerances.
- Only **106 of the 222** communities match a transaction area name, so they render grey
  rather than as the cheapest bucket. An unmatched polygon is missing data, not a zero.

### Fixed
- **A bind parameter silently disabled simplification.** `CASE WHEN :tol > 0 THEN
  ST_SimplifyPreserveTopology(geom, :tol)` -- Postgres infers a parameter's type from its
  *first* use, so an uncast `:tol > 0` inferred `integer`, `0.0001` arrived as `0`, and
  every request took the `ELSE` branch while the response still echoed
  `simplify_tolerance_deg: 0.0001`. Fixed with explicit `CAST(:tol AS double precision)`
  at both sites. The regression test asserts on the **vertex count**, not the echoed
  tolerance, which was correct the whole time. Same silent-failure shape as Spark's
  `to_date()` returning NULL on a format mismatch and `geom <-> point` ordering in degrees.
- Map legend no longer reports "Transaction Volume / Click hexagon" while in Boundaries mode.

## v0.3.0 - PostGIS geometry and an ORM write path (2026-08-15)

### Added
- **PostGIS 3.4** — image swapped from `postgres:16-alpine` (which has no PostGIS
  available at all) to `postgis/postgis:16-3.4`; `CREATE EXTENSION postgis` in `init.sql`
- `communities` table holding 222 Dubai community polygons, with a GiST index on `geom`
  and a functional GiST index on `(geom::geography)` for metre-accurate KNN ordering
- `scripts/load_communities.py` — loads the DLD `Community.kml` export without requiring
  GDAL; attributes are parsed out of the ArcGIS description CDATA
- Spatial endpoints: `GET /communities`, `/communities/contains` (`ST_Contains`),
  `/communities/nearby` (`ST_DWithin`), `/communities/{id}/transactions`
- ORM write path: `db_models/` with SQLAlchemy 2.0 typed declarative models
  (`AreaNote` → `NoteTag`) and optimistic locking via `version_id_col`
- `GET/POST/PUT/PATCH/DELETE /notes` with `If-Match`/`ETag` concurrency control
- **Alembic** migrations for the ORM-managed tables, with `include_object` so
  autogenerate never touches the tables owned by `init.sql`
- `SQL_ECHO=1` toggle for demonstrating query counts
- 22 new tests (49 total, all passing)
- `docs/postgis-query-plans.md`, `docs/n-plus-one-demo.md`

### Changed
- **Removed the hardcoded `AREA_COORDS` dictionary** — 70 hand-typed approximate
  centroids, two pairs of which collided across distinct areas (Marsa Dubai/Dubai Marina,
  Burj Khalifa/Downtown Dubai). Map coordinates are now derived with `ST_Centroid` over
  real polygons: 70 areas → 299 map features, and 75.8% of transactions (151,602/200,000)
  join to a real geometry.
- `database.py` uses `async_sessionmaker` rather than the 1.4-era
  `sessionmaker(class_=AsyncSession)`

### Fixed
- `MissingGreenlet` on PATCH: `onupdate=func.now()` expires `updated_at` after an UPDATE,
  and serialising the object triggered implicit lazy IO, which async SQLAlchemy forbids.
  Writes now re-select with `populate_existing=True`.
- `/communities/nearby` ordered by the geometry `<->` operator, which sorts by planar
  degrees rather than metres and returned results out of order at Dubai's latitude.
  Both sides of the operator are now cast to `geography`.
- One community polygon had a ring self-intersection; repaired with `ST_MakeValid`
  wrapped in `ST_CollectionExtract(..., 3)`.

## v0.1.0 - Foundation (2026-03-07)

### Added
- Docker Compose with PostgreSQL 16 service, health check, named volume and network
- Database schema for 3 DLD datasets: raw_transactions, raw_rent_contracts, raw_valuations
- Analytics table (area_trends) and ingestion tracking (upload_log)
- Ingestion script with CSV auto-detection, null normalization, and deduplication
- Seed profile container for loading data from raw_source/
- Makefile with docker compose wrappers
- Project documentation: architecture, data model
