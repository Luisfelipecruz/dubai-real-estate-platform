# Polygon simplification: what it buys, and what it silently breaks

Measured on the 222 Dubai community boundaries loaded from `Community.kml`, all
`MULTIPOLYGON`, all valid, SRID 4326.

This exists because the boundaries needed to be *served* to a browser, not just
queried in the database. Serving them raises a question the query path never had
to answer: how much geometry does the client actually need?

---

## 1. The motivation — the polygons were invisible

For three build phases the 222 polygons did real work in Postgres — point-in-polygon
containment, radius search, adjacency, overlap, dissolve — and **nothing rendered them**.
Every endpoint reduced geometry to a derived scalar before it left the database:
`ST_Centroid` for a map pin, `ST_Area` for a number. There was no `ST_AsGeoJSON`
anywhere in the API, and the deck.gl map had `ScatterplotLayer`, `HeatmapLayer` and
`HexagonLayer` — no `GeoJsonLayer`.

So the map drew dots on top of boundary data it never showed. `GET /communities/geojson`
is the endpoint that returns the shape.

---

## 2. What simplification buys

`ST_SimplifyPreserveTopology(geom, tolerance)` — Douglas-Peucker with a guard that
stops a polygon self-intersecting or collapsing to nothing. Tolerance is in **degrees**,
because the geometry is in 4326. At Dubai's latitude 0.0001° ≈ **10 m**.

| Tolerance | Response bytes | Vertices | Features |
|---|---|---|---|
| `0` (full fidelity) | 1,012,960 | 34,326 | 222 |
| `0.0001` (~10 m) | **193,887** | **4,900** | 222 |
| `0.001` (~100 m) | 117,966 | 2,170 | 222 |

Geometry alone, excluding the JSON properties: **963,041 → 144,093 bytes, 6.7×**.
The heaviest single polygon carries **2,247 vertices** on its own.

All 222 features survive at every tolerance — that is `PreserveTopology` doing its job.
A plain `ST_Simplify` gives no such guarantee and will happily return `NULL` for a
polygon smaller than the tolerance.

**10 m of boundary error is less than the width of the roads these boundaries run
along.** For rendering, it is free.

---

## 3. What simplification silently breaks

`PreserveTopology` preserves the topology of **each geometry individually**. It says
nothing about the topology *between* neighbours. Two polygons that share a border are
simplified independently, so the shared edge gets decimated twice, differently, and
pulls apart.

Re-running the DE-9IM pair counts at each tolerance:

| Tolerance | `ST_Touches` | `ST_Overlaps` | `ST_Intersects` |
|---|---|---|---|
| `0` (full) | **483** | **131** | 614 |
| `0.0001` | 307 | 307 | **614** |
| `0.0005` | 288 | 318 | 606 |
| `0.001` | 284 | 308 | 592 |

Read it in two steps.

**At 0.0001, adjacency is still complete but mislabelled.** `intersects` holds at 614,
so every neighbour pair is still detected. But **176 of the 483 shared borders — 36% —
migrate from `touches` to `overlaps`**. Those polygons went from *boundaries meet,
interiors do not* to *interiors cross*, purely as an artifact of decimating each side
of a shared edge separately. The DE-9IM partition that was exact on the source data
(483 + 131 = 614, 0 contains, 0 equals) is destroyed.

**At 0.0005 and beyond, adjacency is lost outright.** `intersects` falls to 606 —
**8 neighbour relationships disappear**, the polygons having pulled far enough apart to
be genuinely disjoint. At 0.001, 22 are gone. A "who borders this community" query would
return quietly incomplete answers with no error anywhere.

---

## 4. The rule

**Simplify for display. Never for analysis.**

The API is built this way on purpose:

- `GET /communities/geojson` — simplified by default, for rendering only.
- `/communities/{id}/neighbors`, `/communities/overlap`, `/communities/dissolve`,
  `/communities/contains`, `/communities/nearby` — all read the **unsimplified**
  `communities.geom`.
- `area_km2` in the GeoJSON response is computed from the **original** geometry, even
  when the geometry in the same response is simplified. Simplification moves vertices;
  reporting the area of a shape you decimated for display would make an analytical
  number depend on a rendering setting. A test asserts these areas are identical
  across tolerances.

If shared borders genuinely had to survive simplification, Douglas-Peucker per polygon
is the wrong tool — it needs topology-aware simplification, where the shared edge is
simplified **once** as a shared arc and both polygons reference the result (PostGIS
Topology, or mapshaper's `-simplify`). That is a different data model, not a different
parameter.

---

## 5. A bind-parameter bug worth keeping

The first working version of this endpoint returned full-fidelity geometry while
reporting `simplify_tolerance_deg: 0.0001` in the response body. The SQL was:

```sql
CASE WHEN :tol > 0
     THEN ST_SimplifyPreserveTopology(c.geom, :tol)
     ELSE c.geom
END
```

Postgres infers a bind parameter's type from its **first** use. `$1 > 0` infers
`integer`, so `0.0001` arrived as `0`, `0 > 0` was false, and every request took the
`ELSE` branch. Nothing errored. The fix is an explicit cast at both sites:

```sql
CASE WHEN CAST(:tol AS double precision) > 0
     THEN ST_SimplifyPreserveTopology(c.geom, CAST(:tol AS double precision))
     ELSE c.geom
END
```

Same shape as this project's other silent-failure bugs — Spark's `to_date()` returning
`NULL` on a format mismatch, and `geom <-> point` ordering by degrees instead of metres.
All three return a plausible answer rather than an error. The test that catches it
asserts on the **vertex count**, not on the echoed tolerance, because the echoed
tolerance was correct the whole time.

---

## 6. Reproducing

```bash
# payload and vertex counts
for t in 0 0.0001 0.001; do
  curl -s "http://localhost:8000/communities/geojson?simplify=$t" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(t, d['vertices'], d['total'])"
done
```

```sql
-- adjacency preservation across tolerances
WITH tol(t) AS (VALUES (0.0001::float8),(0.0005::float8),(0.001::float8)),
s AS (
  SELECT t.t AS tolv, c.id, ST_SimplifyPreserveTopology(c.geom, t.t) AS g
    FROM communities c CROSS JOIN tol t
  UNION ALL
  SELECT 0.0::float8, c.id, c.geom FROM communities c
)
SELECT a.tolv AS tolerance_deg,
       COUNT(*) FILTER (WHERE ST_Touches(a.g,b.g))    AS touches,
       COUNT(*) FILTER (WHERE ST_Overlaps(a.g,b.g))   AS overlaps,
       COUNT(*) FILTER (WHERE ST_Intersects(a.g,b.g)) AS intersects
  FROM s a JOIN s b ON a.tolv = b.tolv AND a.id < b.id
 GROUP BY a.tolv ORDER BY a.tolv;
```
