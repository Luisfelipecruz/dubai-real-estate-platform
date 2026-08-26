import pytest


async def test_list_areas(client):
    resp = await client.get("/areas")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if len(data) > 0:
        area = data[0]
        assert "area_name_en" in area
        assert "transaction_count" in area
        assert "rent_count" in area
        assert "valuation_count" in area
        assert area["transaction_count"] + area["rent_count"] + area["valuation_count"] > 0


async def test_list_areas_sorted_by_total_count(client):
    resp = await client.get("/areas")
    assert resp.status_code == 200
    data = resp.json()
    totals = [a["transaction_count"] + a["rent_count"] + a["valuation_count"] for a in data]
    assert totals == sorted(totals, reverse=True)


async def test_area_summary(client):
    # First get an area name that exists
    areas_resp = await client.get("/areas")
    areas = areas_resp.json()
    if not areas:
        pytest.skip("No areas in database")

    area_name = areas[0]["area_name_en"]
    resp = await client.get(f"/areas/{area_name}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["area_name_en"] == area_name
    assert "transactions" in data
    assert "rents" in data
    assert "valuations" in data
    for section in ("transactions", "rents", "valuations"):
        assert "count" in data[section]
        assert "avg_price" in data[section]
        assert "min_price" in data[section]
        assert "max_price" in data[section]
        assert "avg_area_sqm" in data[section]


async def test_area_summary_nonexistent(client):
    resp = await client.get("/areas/NonexistentArea999/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["transactions"]["count"] == 0
    assert data["rents"]["count"] == 0
    assert data["valuations"]["count"] == 0


async def test_area_names_are_unique(client):
    """React keys the areas grid on area_name_en, so the API must not emit it twice.

    `Mushrif` exists under two different DLD area_ids (404 with 33 transactions,
    420 with 1). Grouping by (area_id, area_name_en) produced 223 rows for 222
    distinct names and a duplicate-key error in the grid -- while both cards linked
    to the same /areas/Mushrif page, which aggregates by name anyway.
    """
    areas = (await client.get("/areas")).json()
    names = [a["area_name_en"] for a in areas]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate area names: {duplicates}"


async def test_area_list_merges_ids_sharing_a_name(client):
    """The list must agree with the detail page, which aggregates by name."""
    areas = (await client.get("/areas")).json()
    mushrif = [a for a in areas if a["area_name_en"] == "Mushrif"]
    assert len(mushrif) == 1

    summary = (await client.get("/areas/Mushrif/summary")).json()
    assert mushrif[0]["transaction_count"] == summary["transactions"]["count"]


# --- history -----------------------------------------------------------------


async def test_area_history_returns_a_year_series(client):
    data = (await client.get("/areas/Al Barsha South Fourth/history")).json()
    assert data["interval"] == "year"
    periods = [p["period"] for p in data["points"]]
    assert periods == sorted(periods), "series must be chronological"
    assert len(periods) > 10
    assert sum(p["sale_count"] for p in data["points"]) > 0


async def test_area_history_flags_the_incomplete_year(client):
    """The last year is partial -- data stops mid-February. Charting it unmarked
    reads as a market collapse; dropping it hides the most recent data."""
    data = (await client.get("/areas/Al Barsha South Fourth/history")).json()
    partial = [p for p in data["points"] if p["is_partial"]]
    assert len(partial) == 1
    assert partial[0]["period"] == data["points"][-1]["period"]


async def test_area_history_declares_rents_are_not_historical(client):
    """Every rent contract in the portal export was registered inside one window,
    so the rent column is a snapshot. If a future load ever spans several years
    this flips to True on its own -- it is computed, not hardcoded."""
    data = (await client.get("/areas/Al Barsha South Fourth/history")).json()
    assert data["sales_are_historical"] is True
    assert data["rents_are_historical"] is False
    assert data["rent_registered_from"] and data["rent_registered_to"]


async def test_area_history_rent_is_per_property_not_per_contract(client):
    """annual_amount is the CONTRACT total over up to 408 properties. The median
    here divides by no_of_prop, so it must land in a plausible per-unit range and
    far below the raw contract mean the summary endpoint reports."""
    hist = (await client.get("/areas/Al Barsha South Fourth/history")).json()
    rents = [p["median_annual_rent"] for p in hist["points"] if p["median_annual_rent"]]
    assert rents, "expected some rent data"
    assert all(1_000 < r < 2_000_000 for r in rents), rents


async def test_area_history_unknown_area_is_empty_not_an_error(client):
    data = (await client.get("/areas/Nowhere At All/history")).json()
    assert all(p["sale_count"] == 0 for p in data["points"])
