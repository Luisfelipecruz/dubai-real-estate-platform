async def test_list_valuations_default(client):
    resp = await client.get("/valuations")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "data" in data
    assert data["limit"] == 20
    assert data["offset"] == 0


async def test_list_valuations_filter_year(client):
    resp = await client.get("/valuations?procedure_year=2026&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert item["procedure_year"] == 2026


async def test_list_valuations_filter_worth_range(client):
    resp = await client.get("/valuations?min_worth=500000&max_worth=1000000&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert 500000 <= item["actual_worth"] <= 1000000


async def test_list_valuations_empty_result(client):
    resp = await client.get("/valuations?area_name=NonexistentArea999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["data"] == []
