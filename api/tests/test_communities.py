"""Spatial endpoint tests over the 222 community polygons loaded from Community.kml."""


async def test_list_communities(client):
    resp = await client.get("/communities?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    assert len(data["data"]) <= 5
    for item in data["data"]:
        # Every centroid must land inside Dubai's rough bounding box.
        assert 24.0 < item["latitude"] < 26.5
        assert 54.0 < item["longitude"] < 56.5
        assert item["area_km2"] > 0


async def test_list_communities_name_filter(client):
    resp = await client.get("/communities?name=burj")
    assert resp.status_code == 200
    for item in resp.json()["data"]:
        assert "burj" in item["community_name_en"].lower()


async def test_point_in_polygon_resolves_containing_community(client):
    """The Burj Khalifa coordinate must resolve to the Burj Khalifa community."""
    resp = await client.get("/communities/contains?lat=25.1972&lng=55.2744")
    assert resp.status_code == 200
    assert resp.json()["community_name_en"].upper() == "BURJ KHALIFA"


async def test_point_outside_coverage_returns_404(client):
    # Middle of the Atlantic.
    resp = await client.get("/communities/contains?lat=0.0&lng=-30.0")
    assert resp.status_code == 404


async def test_point_in_polygon_validates_coordinates(client):
    assert (await client.get("/communities/contains?lat=200&lng=55")).status_code == 422


async def test_nearby_orders_by_distance(client):
    resp = await client.get("/communities/nearby?lat=25.1972&lng=55.2744&radius_km=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0

    distances = [item["distance_m"] for item in data["data"]]
    assert distances == sorted(distances)
    # The containing polygon is zero metres away.
    assert distances[0] == 0
    # Everything returned is inside the requested radius.
    assert all(d <= 3000 for d in distances)


async def test_nearby_rejects_absurd_radius(client):
    assert (
        await client.get("/communities/nearby?lat=25.2&lng=55.3&radius_km=5000")
    ).status_code == 422


async def test_community_transaction_summary(client):
    community_id = (await client.get("/communities?name=burj&limit=1")).json()["data"][0]["id"]
    resp = await client.get(f"/communities/{community_id}/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["transaction_count"] >= 0
    assert data["total_volume"] >= 0


async def test_map_transactions_have_derived_coordinates(client):
    """Coordinates come from ST_Centroid now, not the old AREA_COORDS dict."""
    resp = await client.get("/map/transactions")
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert len(features) > 0
    for f in features[:50]:
        assert 24.0 < f["latitude"] < 26.5
        assert 54.0 < f["longitude"] < 56.5


# ── polygon ↔ polygon operations (P7) ─────────────────────────────────────
# Everything above probes the polygons with a point. These exercise the
# predicates that take a polygon as the operand.


async def _id_for(client, name: str) -> int:
    data = (await client.get(f"/communities?name={name}&limit=1")).json()["data"]
    assert data, f"no community matching {name!r}"
    return data[0]["id"]


async def test_neighbors_returns_adjacent_polygons(client):
    """ST_Touches self-join: AL JAFILIYA borders 10 communities."""
    cid = await _id_for(client, "jafiliya")
    resp = await client.get(f"/communities/{cid}/neighbors")
    assert resp.status_code == 200
    data = resp.json()

    assert data["predicate"] == "touches"
    assert data["total"] == 10
    assert data["total"] == len(data["data"])
    # A community is never its own neighbour.
    assert all(n["id"] != cid for n in data["data"])
    # Ordered by shared boundary length, descending.
    lengths = [n["shared_boundary_m"] for n in data["data"]]
    assert lengths == sorted(lengths, reverse=True)
    # Touching means a shared boundary of real, non-zero length.
    assert lengths[0] > 0


async def test_neighbors_predicate_widens_from_touches_to_intersects(client):
    """DE-9IM: intersects is the loosest predicate, so it can only add rows."""
    cid = await _id_for(client, "jafiliya")
    touches = (await client.get(f"/communities/{cid}/neighbors?predicate=touches")).json()
    intersects = (
        await client.get(f"/communities/{cid}/neighbors?predicate=intersects")
    ).json()
    assert intersects["total"] >= touches["total"]

    touch_ids = {n["id"] for n in touches["data"]}
    intersect_ids = {n["id"] for n in intersects["data"]}
    assert touch_ids <= intersect_ids


async def test_neighbors_rejects_unknown_predicate(client):
    cid = await _id_for(client, "jafiliya")
    assert (
        await client.get(f"/communities/{cid}/neighbors?predicate=st_drop_table")
    ).status_code == 422


async def test_neighbors_unknown_community_is_404(client):
    assert (await client.get("/communities/999999/neighbors")).status_code == 404


async def test_overlap_reports_real_square_metres(client):
    """SAIH AL DAHAL and AL FAGAA overlap by a 5,471 m² sliver."""
    a = await _id_for(client, "saih al dahal")
    b = await _id_for(client, "al fagaa")
    resp = await client.get(f"/communities/overlap?a={a}&b={b}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["relationship"] == "overlaps"
    # Real m², not square degrees — a degree² here would be ~1e-7.
    assert 5000 < data["overlap_m2"] < 6000
    # A sliver: a rounding artefact of digitisation, not a real shared region.
    assert data["overlap_pct_of_a"] < 0.01
    assert data["overlap_m2"] < data["a_area_m2"]
    assert data["overlap_m2"] < data["b_area_m2"]


async def test_overlap_of_touching_polygons_has_zero_area(client):
    """Touching polygons share a boundary line, which has length but no area."""
    a = await _id_for(client, "jafiliya")
    neighbors = (await client.get(f"/communities/{a}/neighbors")).json()["data"]
    b = neighbors[0]["id"]

    data = (await client.get(f"/communities/overlap?a={a}&b={b}")).json()
    assert data["relationship"] == "touches"
    assert data["overlap_m2"] == 0


async def test_dissolve_merges_touching_polygons_into_one_part(client):
    """ST_Union dissolves the shared boundary rather than collecting the parts."""
    a = await _id_for(client, "jafiliya")
    b = (await client.get(f"/communities/{a}/neighbors")).json()["data"][0]["id"]

    resp = await client.get(f"/communities/dissolve?ids={a},{b}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["resolved"] == 2
    assert data["parts"] == 1  # dissolved, not collected
    assert data["overlap_area_m2"] == 0
    # No overlap means summing the parts was already correct.
    assert data["total_area_m2"] == data["sum_of_parts_m2"]


async def test_dissolve_measures_overlap_directly_not_by_subtraction(client):
    """The overlap is measured, not inferred from two large geodesic areas.

    sum_of_parts - total_area would give a *negative* number here: geodesic area
    of the merged boundary carries ~0.003% error, which on a 330 km² district is
    ~10,000 m² — larger than the real 5,471 m² overlap.
    """
    a = await _id_for(client, "saih al dahal")
    b = await _id_for(client, "al fagaa")

    dissolve = (await client.get(f"/communities/dissolve?ids={a},{b}")).json()
    pairwise = (await client.get(f"/communities/overlap?a={a}&b={b}")).json()

    assert dissolve["overlap_area_m2"] > 0
    # Measured directly, so it agrees with the pairwise intersection exactly.
    assert dissolve["overlap_area_m2"] == pairwise["overlap_m2"]
    # And the naive subtraction really does go the wrong way.
    assert dissolve["sum_of_parts_m2"] - dissolve["total_area_m2"] < 0


async def test_dissolve_rejects_bad_input(client):
    assert (await client.get("/communities/dissolve?ids=nope")).status_code == 422
    assert (await client.get("/communities/dissolve?ids=")).status_code == 422
    assert (await client.get("/communities/dissolve?ids=999999")).status_code == 404


# --- GeoJSON boundary layer -------------------------------------------------
# The polygons existed in Postgres for three phases before anything served them:
# every endpoint reduced geometry to ST_Centroid or ST_Area, so the map drew dots.
# These guard the one endpoint that returns the shape itself.


async def test_geojson_is_a_valid_feature_collection(client):
    resp = await client.get("/communities/geojson")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["total"] == len(data["features"]) == 222
    for feature in data["features"][:10]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert feature["geometry"]["coordinates"]
        assert feature["properties"]["area_km2"] > 0


async def test_geojson_simplification_actually_reduces_vertices(client):
    """Regression test for a silent no-op.

    `CASE WHEN :tol > 0 THEN ST_SimplifyPreserveTopology(geom, :tol)` infers the
    bind parameter's type from its FIRST use, so an uncast `:tol > 0` makes it an
    integer, 0.0001 arrives as 0, and the ELSE branch returns full-fidelity
    geometry -- while the response still echoes simplify_tolerance_deg = 0.0001.
    Asserting only on the echoed tolerance would not have caught it; this asserts
    on the vertex count, which is the thing that actually changed.
    """
    full = (await client.get("/communities/geojson?simplify=0")).json()
    simplified = (await client.get("/communities/geojson?simplify=0.0001")).json()

    assert full["vertices"] > 30_000
    assert simplified["vertices"] < full["vertices"] / 5
    # PreserveTopology must not drop a polygon entirely, however coarse the tolerance
    assert simplified["total"] == full["total"] == 222


async def test_geojson_reports_area_from_unsimplified_geometry(client):
    """Simplification moves vertices. Area must not follow it, or every number
    downstream silently depends on a display setting."""
    full = (await client.get("/communities/geojson?simplify=0")).json()
    coarse = (await client.get("/communities/geojson?simplify=0.001")).json()

    areas_full = {f["id"]: f["properties"]["area_km2"] for f in full["features"]}
    areas_coarse = {f["id"]: f["properties"]["area_km2"] for f in coarse["features"]}
    assert areas_full == areas_coarse


async def test_geojson_stats_are_null_for_unmatched_communities(client):
    """Only ~106 of the 222 community names match a transaction area name. The
    unmatched ones must be null, not 0 -- a choropleth that paints missing data
    as the cheapest bucket is a lie."""
    data = (await client.get("/communities/geojson?with_stats=true")).json()
    matched = [f for f in data["features"] if f["properties"]["transaction_count"] is not None]
    assert 50 < len(matched) < 222
    for feature in data["features"]:
        count = feature["properties"]["transaction_count"]
        assert count is None or count > 0


async def test_geojson_without_stats_omits_transaction_fields(client):
    data = (await client.get("/communities/geojson?with_stats=false")).json()
    assert data["total"] == 222
    assert all(f["properties"]["transaction_count"] is None for f in data["features"])


async def test_geojson_rejects_out_of_range_tolerance(client):
    assert (await client.get("/communities/geojson?simplify=-1")).status_code == 422
    assert (await client.get("/communities/geojson?simplify=5")).status_code == 422


async def test_geojson_carries_the_transaction_side_area_name(client):
    """The KML spells it 'AL MANARA'; the DLD transaction CSV spells it 'Al Manara'.

    The map's click-through queries the transaction tables, so the feature has to
    carry the transaction-side spelling. Handing over the polygon's own name made
    /areas/{name}/summary return HTTP 200 with every count zeroed -- a populated
    area rendering as an empty detail panel, with no error anywhere.
    """
    data = (await client.get("/communities/geojson")).json()
    matched = [f for f in data["features"] if f["properties"]["transaction_count"]]
    assert matched, "expected at least one community joined to transactions"
    for feature in matched:
        props = feature["properties"]
        assert props["txn_area_name"]
        # same place, normalised -- but not necessarily the same string
        assert props["txn_area_name"].upper().strip() == props["community_name_en"].upper().strip()

    # and null where nothing matched, rather than echoing the polygon's own name
    for feature in data["features"]:
        if feature["properties"]["transaction_count"] is None:
            assert feature["properties"]["txn_area_name"] is None


async def test_area_summary_is_case_insensitive(client):
    """A case variant must not silently return zeros."""
    upper = (await client.get("/areas/AL MANARA/summary")).json()
    title = (await client.get("/areas/Al Manara/summary")).json()
    assert title["transactions"]["count"] > 0
    assert upper["transactions"]["count"] == title["transactions"]["count"]
    assert upper["transactions"]["avg_price"] == title["transactions"]["avg_price"]


async def test_geojson_name_filter_returns_one_polygon(client):
    data = (await client.get("/communities/geojson?name=Al Barsha South Fourth")).json()
    assert data["total"] == 1
    assert data["features"][0]["properties"]["community_name_en"].upper() == "AL BARSHA SOUTH FOURTH"


async def test_geojson_name_filter_is_case_insensitive(client):
    lower = (await client.get("/communities/geojson?name=al barsha south fourth")).json()
    upper = (await client.get("/communities/geojson?name=AL BARSHA SOUTH FOURTH")).json()
    assert lower["total"] == upper["total"] == 1


async def test_geojson_name_filter_unknown_returns_empty_collection(client):
    """Empty FeatureCollection, not 404 -- 'this area has no polygon' is a normal
    state for 115 of the 221 areas, and the detail page renders an explanation."""
    data = (await client.get("/communities/geojson?name=Nowhere At All")).json()
    assert data["type"] == "FeatureCollection"
    assert data["total"] == 0
    assert data["features"] == []
