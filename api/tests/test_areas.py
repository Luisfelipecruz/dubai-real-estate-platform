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
