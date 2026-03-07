async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_stats(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert "rents" in data
    assert "valuations" in data
    assert "uploads" in data
    for key in ("transactions", "rents", "valuations"):
        assert isinstance(data[key], int)
        assert data[key] >= 0
