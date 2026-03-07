async def test_list_transactions_default(client):
    resp = await client.get("/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "data" in data
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert isinstance(data["data"], list)


async def test_list_transactions_pagination(client):
    resp = await client.get("/transactions?limit=5&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 5
    assert len(data["data"]) <= 5


async def test_list_transactions_filter_area(client):
    resp = await client.get("/transactions?area_name=Marsa+Dubai&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert "marsa dubai" in item["area_name_en"].lower()


async def test_list_transactions_filter_trans_group(client):
    resp = await client.get("/transactions?trans_group=Sales&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert item["trans_group_en"] == "Sales"


async def test_list_transactions_filter_amount_range(client):
    resp = await client.get("/transactions?min_amount=1000000&max_amount=2000000&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert 1000000 <= item["actual_worth"] <= 2000000


async def test_list_transactions_sort_ascending(client):
    resp = await client.get("/transactions?sort_by=actual_worth&sort_order=asc&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    prices = [item["actual_worth"] for item in data["data"] if item["actual_worth"] is not None]
    assert prices == sorted(prices)


async def test_list_transactions_empty_result(client):
    resp = await client.get("/transactions?area_name=NonexistentArea999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["data"] == []
