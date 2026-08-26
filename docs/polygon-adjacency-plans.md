# Polygon ↔ polygon operations: DE-9IM, the spatial self-join, and what the GiST index actually buys

**Measured 2026-08-15 against the live database. 222 community polygons, PostGIS 3.4 on PostgreSQL 16.**

Every spatial predicate in this project before today took a **point** as the probe —
`ST_Contains(geom, ST_Point(...))`, `ST_DWithin(geom::geography, point, r)`. The polygons were
always the target, never the operand. That is the entry-level spatial query. This document
covers the polygon-algebra ones, and one finding that contradicts the obvious conclusion.

---

## 1. DE-9IM, measured

The Dimensionally Extended 9-Intersection Model describes the relationship between two geometries
as a 3×3 matrix of intersections between their interiors, boundaries and exteriors. The named
predicates are shorthands for patterns in that matrix:

| Predicate | Interiors intersect? | Boundaries meet? | Meaning |
| :--- | :--- | :--- | :--- |
| `ST_Touches` | **no** | yes | they share a border, nothing more |
| `ST_Overlaps` | **yes** | — | interiors intersect, neither contains the other, same dimension |
| `ST_Contains` / `ST_Within` | yes | — | one wholly inside the other |
| `ST_Equals` | yes | yes | identical point sets |
| `ST_Intersects` | — | — | **any** shared point at all — the union of all the above |

Counted across all 24,531 distinct pairs (`a.id < b.id`) of the 222 polygons:

```sql
SELECT
  count(*) FILTER (WHERE ST_Touches(a.geom,b.geom))   AS touches,
  count(*) FILTER (WHERE ST_Overlaps(a.geom,b.geom))  AS overlaps,
  count(*) FILTER (WHERE ST_Contains(a.geom,b.geom)
                      OR ST_Within(a.geom,b.geom))    AS contains_within,
  count(*) FILTER (WHERE ST_Equals(a.geom,b.geom))    AS equals,
  count(*)                                            AS intersects_total
FROM communities a JOIN communities b
  ON a.id < b.id AND ST_Intersects(a.geom,b.geom);
```

```
 touches | overlaps | contains_within | equals | intersects_total
---------+----------+-----------------+--------+------------------
     483 |      131 |               0 |      0 |              614
```

**483 + 131 + 0 + 0 = 614.** The partition is exact, which is the clearest possible demonstration
that `ST_Intersects` is the union of the others and `ST_Touches` is strictly the boundary-only case.

### The 131 "overlapping" pairs are a data-quality finding, not geography

Administrative boundaries should tile the city, not overlap. Ranking the overlaps by real area:

| A | B | overlap |
| :--- | :--- | ---: |
| SAIH AL DAHAL | AL FAGAA | 5,471.89 m² |
| SAIH SHUA'ALAH | SAIH AL DAHAL | 4,944.19 m² |
| AL AWIR SECOND | AL WOHOOSH | 19.49 m² |
| HESSYAN SECOND | HESSYAN FIRST | 13.99 m² |
| MADINAT HIND 4 | AL YALAYIS 3 | 13.02 m² |

The largest is 5,471 m² against a 190 km² polygon — **0.0029%**. These are digitisation slivers,
not real shared territory. Worth knowing before anyone builds a "which community is this in?"
rule that assumes the answer is unique.

---

## 2. The spatial self-join

```sql
SELECT b.id, b.community_name_en,
       ST_Length(ST_Intersection(a.geom, b.geom)::geography) AS shared_m
  FROM communities a
  JOIN communities b
    ON a.id <> b.id
   AND ST_Touches(a.geom, b.geom)
 WHERE a.id = :id
 ORDER BY shared_m DESC;
```

Two details that matter:

- The shared boundary of two touching polygons is a **line**, so the meaningful measure is
  `ST_Length`, not `ST_Area`. Taking the area of a touching pair correctly returns **0**.
- The `::geography` cast is again mandatory. `ST_Length` on geometry in SRID 4326 returns
  **degrees**. Same class of bug as the `<->` KNN ordering fixed earlier in this project.

Result for `AL JAFILIYA` — 10 neighbours, ordered by how much border they share:

```
AL HUDAIBA          1418.87 m
MANKHOOL            1318.51 m
AL KIFAF            1230.25 m
AL SATWA             862.11 m
TRADE CENTER FIRST   380.93 m
...
```

---

## 3. `EXPLAIN ANALYZE`, with and without the GiST index

The join is O(n²) in candidate pairs: 222 polygons = **49,284** ordered pairs, 24,642 after
`a.id < b.id`. The question is whether the index changes that.

### With `idx_communities_geom`

```
Aggregate  (cost=3094.06..3094.07 rows=1) (actual time=49.198..49.221 rows=1 loops=1)
  Buffers: shared hit=2485
  ->  Nested Loop  (cost=0.14..3093.96 rows=41) (actual time=6.230..48.487 rows=483 loops=1)
        ->  Seq Scan on communities a  (actual time=0.083..0.117 rows=222 loops=1)
        ->  Index Scan using idx_communities_geom on communities b
                                                   (actual time=0.113..0.216 rows=2 loops=222)
              Index Cond: (geom && a.geom)
              Filter: ((a.id < id) AND st_touches(a.geom, geom))
              Rows Removed by Filter: 6
Execution Time: 50.852 ms
```

**`Index Cond: (geom && a.geom)`** is the whole story: `&&` is the bounding-box overlap operator,
which is what a GiST index can answer. It reduces 222 candidates per outer row to about 8, and the
exact `ST_Touches` predicate then runs only on those — 2 matches, 6 removed by filter. Two-stage
evaluation, cheap filter first.

### Without it (`enable_indexscan=off, enable_bitmapscan=off`)

```
Aggregate  (cost=616904.36..616904.37 rows=1) (actual time=573.772..573.796 rows=1 loops=1)
  Buffers: shared hit=8974
  ->  Nested Loop  (actual time=524.737..572.992 rows=483 loops=1)
        Join Filter: ((a.id < b.id) AND st_touches(a.geom, b.geom))
        Rows Removed by Join Filter: 48801
        ->  Seq Scan on communities a  (rows=222 loops=1)
        ->  Materialize  (rows=222 loops=222)
JIT:
  Functions: 8
  Timing: Generation 5.907, Inlining 46.105, Optimization 229.451, Emission 243.194,
          Total 524.656 ms
Execution Time: 664.448 ms
```

**`Rows Removed by Join Filter: 48801`**, plus the 483 that matched, is **49,284** — exactly 222².
The plan states the O(n²) in its own output.

### The finding that reverses the obvious conclusion

664 ms → 51 ms looks like a **13× win for the index**. It is not.

Look at the JIT line: **524 ms of that 664 ms was LLVM compilation**, triggered because the
estimated cost (616,904) crossed `jit_above_cost`. Re-run both with `SET jit=off`:

| Configuration | Execution time |
| :--- | ---: |
| With GiST, JIT allowed | **50.85 ms** |
| Without index, JIT allowed | **664.45 ms** |
| With GiST, `jit=off` | **50.75 ms** |
| Without index, `jit=off` | **58.51 ms** |

**With JIT disabled the index is worth 1.15×, not 13×.** At 222 rows, 49,284 bounding-box
comparisons are simply not expensive; the geometries all fit in shared buffers (8,974 pages hit,
zero read). The apparent 13× was the planner reacting to an inflated cost estimate by paying half
a second to compile a query that runs in 58 ms.

Both numbers are true and they answer different questions:

- **"Does the index make the operation faster?"** Barely, at this scale — 1.15×.
- **"Does the index make the system faster in default configuration?"** Yes, 13× — by keeping the
  plan cheap enough that JIT never fires.

The index earns its place for the second reason today, and for the first reason at 10,000
polygons, where 10⁸ candidate pairs stop being free. **Say the 1.15× unprompted** — volunteering
the measurement that undercuts your own index is worth more than the headline.

> This is the second time measuring this project has contradicted the intuition. The first:
> a *single* point-in-polygon lookup got **slower** with the GiST index (2.95 ms vs 2.34 ms),
> because 222 rows fit in a few pages and the index adds a level of indirection. Bulk lookups
> still went 2,082 ms → 654 ms (3.2×). Different question, different answer, both measured.

---

## 4. `ST_Union` — and why the overlap is measured, not subtracted

```sql
WITH picked AS (SELECT id, geom FROM communities WHERE id = ANY(:ids)),
     merged AS (SELECT ST_Union(geom) AS geom FROM picked),
     shared AS (
       SELECT ST_Union(ST_Intersection(a.geom, b.geom)) AS geom
         FROM picked a JOIN picked b
           ON a.id < b.id AND ST_Overlaps(a.geom, b.geom)
     )
SELECT ST_Area(m.geom::geography), ST_Area(s.geom::geography) FROM merged m, shared s;
```

`ST_Union` **dissolves** shared boundaries rather than collecting parts — that is what separates it
from `ST_Collect`. Two touching communities union into `parts = 1`.

The natural way to report the double-counting is `sum_of_parts − total_area`. **It gives a negative
number**, and the reason is worth understanding:

| Measurement | SAIH AL DAHAL ∪ AL FAGAA |
| :--- | ---: |
| sum of the two geography areas | 330,691,456.61 m² |
| geography area of the union | 330,696,402.25 m² |
| naive difference | **−4,945.64 m²** |
| measured pairwise intersection | **+5,471.89 m²** |

In **planar** terms the identity is exact — verified to ten significant figures:

```
planar_sum − planar_union = 4.880516358551912e-07
planar_intersection       = 4.880516359470555e-07
```

The discrepancy is entirely in the **geodesic** area computation. Computing the area of a merged
boundary on the spheroid carries roughly 0.003% error, and on a 330 km² district that is ~10,000 m²
— nearly twice the real 5,471 m² overlap, and enough to flip the sign.

**So the endpoint measures the overlap directly** (`ST_Union` of the pairwise `ST_Intersection`s)
rather than inferring it from the difference of two large numbers. The general lesson is not about
PostGIS: *do not derive a small quantity by subtracting two large ones that were computed by
different code paths.*

Verified in `api/tests/test_communities.py::test_dissolve_measures_overlap_directly_not_by_subtraction`,
which asserts both that the measured value matches the pairwise intersection exactly **and** that
the naive subtraction really does go negative.

---

## 5. Endpoints

| Endpoint | Operator | What it demonstrates |
| :--- | :--- | :--- |
| `GET /communities/{id}/neighbors?predicate=touches\|intersects\|overlaps` | `ST_Touches` etc. | adjacency as a spatial self-join; the DE-9IM choice |
| `GET /communities/overlap?a=&b=` | `ST_Intersection` + `ST_Area(::geography)` | polygon algebra returning a new geometry; real m² |
| `GET /communities/dissolve?ids=1,2,3` | `ST_Union` | aggregation of geometries into a district |

The `predicate` parameter is whitelisted against a dict rather than interpolated, because it
reaches SQL as a function identifier and cannot be a bind parameter. An unknown value is a 422.

**9 tests added, 58 passing.**

---

## 6. The talking points

1. **`ST_Touches` vs `ST_Intersects` vs `ST_Overlaps` is the DE-9IM distinction** — and here it is
   measured: 483 / 131 / 614, partitioning exactly. Most candidates only know `ST_Intersects`.
2. **A polygon self-join is O(n²) and the plan says so** — `Rows Removed by Join Filter: 48801` +
   483 matched = 222². GiST turns it into a two-stage evaluation via the `&&` bounding-box operator.
3. **But measure before claiming the speedup.** 13× was JIT compilation; the index itself is worth
   1.15× at this row count. Second time this project's intuition has been wrong in the same direction.
4. **`geometry` vs `geography`, for the third time.** Area in square degrees, length in degrees, and
   now geodesic area error large enough to flip a sign. Cast deliberately, and know the error bar.
5. **Invalid geometry bites hardest here.** One self-intersecting ring was repaired with
   `ST_MakeValid` at load time. Polygon-polygon predicates are where a bad ring returns wrong
   topology silently rather than raising.
