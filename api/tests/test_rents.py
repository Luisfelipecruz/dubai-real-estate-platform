async def test_list_rents_default(client):
    resp = await client.get("/rents")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "data" in data
    assert data["limit"] == 20
    assert data["offset"] == 0


async def test_list_rents_pagination(client):
    resp = await client.get("/rents?limit=3&offset=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 3
    assert data["offset"] == 10
    assert len(data["data"]) <= 3


async def test_list_rents_filter_contract_type(client):
    resp = await client.get("/rents?contract_reg_type=New&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert item["contract_reg_type_en"] == "New"


async def test_list_rents_filter_area(client):
    resp = await client.get("/rents?area_name=Business+Bay&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["data"]:
        assert "business bay" in item["area_name_en"].lower()


async def test_list_rents_empty_result(client):
    resp = await client.get("/rents?area_name=NonexistentArea999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["data"] == []
