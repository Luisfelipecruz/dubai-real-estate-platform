"""Notes endpoint tests — the PUT/PATCH semantics are the point.

The behaviour these lock down is exactly what gets asked in interviews:
PUT replaces (omitted fields reset), PATCH merges (omitted fields survive), and
an explicitly null field is distinguishable from an omitted one.
"""

import pytest


@pytest.fixture
async def note(client):
    """Create a note and clean it up afterwards."""
    resp = await client.post(
        "/notes",
        json={
            "area_name": "Test Area",
            "title": "Original title",
            "body": "Original body",
            "author": "tester",
            "tags": ["alpha", "beta"],
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    yield created
    await client.delete(f"/notes/{created['id']}")


async def test_create_returns_201_and_etag(client):
    resp = await client.post(
        "/notes",
        json={"area_name": "Area A", "title": "T", "tags": ["x"]},
    )
    assert resp.status_code == 201
    assert resp.headers["etag"] == 'W/"1"'
    data = resp.json()
    assert data["version"] == 1
    assert data["author"] == "anonymous"  # schema default applied
    await client.delete(f"/notes/{data['id']}")


async def test_create_normalises_and_dedupes_tags(client):
    resp = await client.post(
        "/notes",
        json={"area_name": "A", "title": "T", "tags": ["Yield", "  YIELD  ", "watch"]},
    )
    assert resp.status_code == 201
    labels = [t["label"] for t in resp.json()["tags"]]
    assert labels == ["yield", "watch"]
    await client.delete(f"/notes/{resp.json()['id']}")


async def test_create_rejects_blank_title(client):
    resp = await client.post("/notes", json={"area_name": "A", "title": "   "})
    assert resp.status_code == 422


async def test_patch_leaves_omitted_fields_alone(client, note):
    """PATCH is a merge: body and author must survive a title-only patch."""
    resp = await client.patch(f"/notes/{note['id']}", json={"title": "Patched title"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Patched title"
    assert data["body"] == "Original body"
    assert data["author"] == "tester"
    assert data["version"] == note["version"] + 1


async def test_put_resets_omitted_fields(client, note):
    """PUT is a replacement: omitted fields go back to their defaults."""
    resp = await client.put(
        f"/notes/{note['id']}",
        json={"area_name": "Test Area", "title": "Replaced title"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Replaced title"
    assert data["body"] is None            # cleared, not preserved
    assert data["author"] == "anonymous"   # back to the default
    assert data["tags"] == []


async def test_put_is_idempotent(client, note):
    payload = {"area_name": "Test Area", "title": "Same", "body": "Same body"}
    first = (await client.put(f"/notes/{note['id']}", json=payload)).json()
    second = (await client.put(f"/notes/{note['id']}", json=payload)).json()

    # Same request twice -> same resource state (version advances, content does not).
    for field in ("area_name", "title", "body", "author"):
        assert first[field] == second[field]


async def test_patch_explicit_null_clears_field(client, note):
    """{"body": null} must clear the body — and be distinguishable from omitting it."""
    resp = await client.patch(f"/notes/{note['id']}", json={"body": None})
    assert resp.status_code == 200
    assert resp.json()["body"] is None


async def test_patch_empty_body_rejected(client, note):
    resp = await client.patch(f"/notes/{note['id']}", json={})
    assert resp.status_code == 422


async def test_stale_if_match_returns_412(client, note):
    await client.patch(f"/notes/{note['id']}", json={"title": "bumped"})
    resp = await client.patch(
        f"/notes/{note['id']}",
        json={"title": "should fail"},
        headers={"If-Match": 'W/"1"'},
    )
    assert resp.status_code == 412


async def test_current_if_match_succeeds(client, note):
    current = (await client.get(f"/notes/{note['id']}")).headers["etag"]
    resp = await client.patch(
        f"/notes/{note['id']}",
        json={"title": "accepted"},
        headers={"If-Match": current},
    )
    assert resp.status_code == 200


async def test_get_missing_note_returns_404(client):
    assert (await client.get("/notes/99999999")).status_code == 404


async def test_delete_returns_204_then_404(client):
    created = (
        await client.post("/notes", json={"area_name": "A", "title": "to delete"})
    ).json()
    assert (await client.delete(f"/notes/{created['id']}")).status_code == 204
    assert (await client.get(f"/notes/{created['id']}")).status_code == 404


async def test_list_filters_by_area(client, note):
    resp = await client.get("/notes?area_name=Test+Area")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for item in data["data"]:
        assert item["area_name"] == "Test Area"
