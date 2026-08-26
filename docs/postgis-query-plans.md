# PostGIS query plans — what the GiST index actually buys

Captured 2026-08-15 · PostGIS 3.4 / PostgreSQL 16 · 222 Dubai community polygons
loaded from the DLD `Community.kml` export.

Two experiments, because the first one is the one people quote and the second one
is the one that is actually true.

---

## Experiment 1 — a single point-in-polygon lookup

`SELECT community_name_en FROM communities WHERE ST_Contains(geom, ST_Point(55.2744, 25.1972))`

**Result: the index does not help.** Sequential scan 2.34 ms, index scan 2.95 ms.
The planner's *estimate* drops 137× (cost 2832.22 → 20.66), but 222 rows live in a
handful of pages, so reading all of them costs nothing. The index scan is marginally
*slower* because of the extra index descent.

This is worth saying out loud in an interview: an index is not free, and on a small
table it loses. What changes the answer is volume.

### With the GiST index

```
                                                             QUERY PLAN                                                             
------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_communities_geom on communities  (cost=0.14..20.66 rows=1 width=14) (actual time=2.571..2.591 rows=1 loops=1)
   Index Cond: (geom ~ '0101000020E6100000DE02098A1FA34B406DC5FEB27B323940'::geometry)
   Filter: st_contains(geom, '0101000020E6100000DE02098A1FA34B406DC5FEB27B323940'::geometry)
   Rows Removed by Filter: 1
   Buffers: shared hit=26 read=1
 Planning:
   Buffers: shared hit=215
 Planning Time: 26.527 ms
 Execution Time: 3.701 ms
(9 rows)

```

### Without the GiST index

```
                                               QUERY PLAN                                                
---------------------------------------------------------------------------------------------------------
 Seq Scan on communities  (cost=0.00..2832.22 rows=1 width=14) (actual time=1.205..1.294 rows=1 loops=1)
   Filter: st_contains(geom, '0101000020E6100000DE02098A1FA34B406DC5FEB27B323940'::geometry)
   Rows Removed by Filter: 221
   Buffers: shared hit=119
 Planning:
   Buffers: shared hit=182
 Planning Time: 23.331 ms
 Execution Time: 2.037 ms
(8 rows)

```

---

## Experiment 2 — 20,000 point-in-polygon lookups (the realistic workload)

This is what geocoding a batch of transactions against community boundaries looks
like: many points, each needing the polygon that contains it.

**Result: 654 ms with the index vs 2,082 ms without — 3.2× faster.**

Without the index the plan is a nested loop with a `Seq Scan on communities` on the
inner side: 20,000 iterations × 222 polygons ≈ 4.4 million `ST_Contains` tests.
With the index, each point does a GiST descent on the bounding-box operator (`geom ~ point`)
and only the surviving candidates get the exact `ST_Contains` check — that two-stage
filter-then-refine is the whole point of a spatial index.

### With the GiST index

```
                                                                                                  QUERY PLAN                                                                                                   
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 GroupAggregate  (cost=256892.99..256928.51 rows=222 width=22) (actual time=495.505..498.757 rows=176 loops=1)
   Group Key: c.community_name_en
   Buffers: shared hit=73374 read=1
   ->  Sort  (cost=256892.99..256904.09 rows=4440 width=14) (actual time=494.535..495.084 rows=15116 loops=1)
         Sort Key: c.community_name_en
         Sort Method: quicksort  Memory: 775kB
         Buffers: shared hit=70102 read=1
         ->  Nested Loop  (cost=0.14..256624.00 rows=4440 width=14) (actual time=156.151..479.083 rows=15116 loops=1)
               Buffers: shared hit=55523 read=1
               ->  Function Scan on generate_series  (cost=0.00..3050.00 rows=20000 width=32) (actual time=153.170..157.153 rows=20000 loops=1)
               ->  Index Scan using idx_communities_geom on communities c  (cost=0.14..12.67 rows=1 width=2535) (actual time=0.015..0.016 rows=1 loops=20000)
                     Index Cond: (geom ~ (st_setsrid(st_point(('55'::double precision + (random() * '0.5'::double precision)), ('25'::double precision + (random() * '0.3'::double precision))), 4326)))
                     Filter: st_contains(geom, (st_setsrid(st_point(('55'::double precision + (random() * '0.5'::double precision)), ('25'::double precision + (random() * '0.3'::double precision))), 4326)))
                     Rows Removed by Filter: 1
                     Buffers: shared hit=55523 read=1
 Planning:
   Buffers: shared hit=243
 Planning Time: 30.941 ms
 JIT:
   Functions: 14
   Options: Inlining false, Optimization false, Expressions true, Deforming true
   Timing: Generation 7.658 ms, Inlining 0.000 ms, Optimization 12.723 ms, Emission 138.268 ms, Total 158.649 ms
 Execution Time: 620.937 ms
(23 rows)

```

### Without the GiST index

```
                                                                                                   QUERY PLAN                                                                                                   
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 GroupAggregate  (cost=55558876.76..55558912.28 rows=222 width=22) (actual time=1935.988..1939.065 rows=178 loops=1)
   Group Key: c.community_name_en
   Buffers: shared hit=817628
   ->  Sort  (cost=55558876.76..55558887.86 rows=4440 width=14) (actual time=1935.088..1935.631 rows=15034 loops=1)
         Sort Key: c.community_name_en
         Sort Method: quicksort  Memory: 773kB
         Buffers: shared hit=814384
         ->  Nested Loop  (cost=0.00..55558607.78 rows=4440 width=14) (actual time=667.964..1919.980 rows=15034 loops=1)
               Join Filter: st_contains(c.geom, (st_setsrid(st_point(('55'::double precision + (random() * '0.5'::double precision)), ('25'::double precision + (random() * '0.3'::double precision))), 4326)))
               Rows Removed by Join Filter: 4424966
               Buffers: shared hit=800079
               ->  Function Scan on generate_series  (cost=0.00..3050.00 rows=20000 width=32) (actual time=666.258..670.996 rows=20000 loops=1)
               ->  Materialize  (cost=0.00..58.33 rows=222 width=2535) (actual time=0.000..0.009 rows=222 loops=20000)
                     Buffers: shared hit=55
                     ->  Seq Scan on communities c  (cost=0.00..57.22 rows=222 width=2535) (actual time=0.082..0.141 rows=222 loops=1)
                           Buffers: shared hit=55
 Planning:
   Buffers: shared hit=213
 Planning Time: 29.282 ms
 JIT:
   Functions: 13
   Options: Inlining true, Optimization true, Expressions true, Deforming true
   Timing: Generation 7.454 ms, Inlining 66.524 ms, Optimization 290.146 ms, Emission 307.479 ms, Total 671.603 ms
 Execution Time: 2045.340 ms
(24 rows)

```
