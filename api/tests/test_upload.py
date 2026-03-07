async def test_upload_non_csv_rejected(client):
    resp = await client.post(
        "/upload",
        files={"file": ("data.txt", b"some content", "text/plain")},
    )
    assert resp.status_code == 422


async def test_upload_empty_csv_rejected(client):
    resp = await client.post(
        "/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert resp.status_code == 422


async def test_upload_unrecognized_csv_rejected(client):
    csv_content = b"col_a,col_b\n1,2\n3,4\n"
    resp = await client.post(
        "/upload",
        files={"file": ("unknown.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 422
    assert "Unrecognized" in resp.json()["detail"]


async def test_upload_valid_transactions_csv(client):
    csv_content = (
        "transaction_id,instance_date,procedure_name_en,trans_group_en,"
        "property_type_en,property_sub_type_en,property_usage_en,reg_type_en,"
        "area_id,area_name_en,building_name_en,project_name_en,master_project_en,"
        "rooms_en,procedure_area,actual_worth,meter_sale_price,meter_rent_price,"
        "has_parking,nearest_metro_en,nearest_mall_en,nearest_landmark_en,"
        "no_of_parties_role_1,no_of_parties_role_2,no_of_parties_role_3,load_timestamp\n"
        "TEST-UPLOAD-001,2026-01-15,Sell,Sales,Unit,Flat,Residential,Existing Properties,"
        "330,Marsa Dubai,TEST TOWER,TEST PROJECT,Dubai Marina,"
        "1 B/R,75.5,1500000,19867.55,null,"
        "1,Dubai Marina Metro,Marina Mall,JBR Walk,"
        "1,1,0,2026-01-15 10:00:00\n"
    )
    resp = await client.post(
        "/upload",
        files={"file": ("test_transactions.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataset_type"] == "transactions"
    assert data["rows_received"] == 1
    assert data["status"] == "success"
    assert data["rows_inserted"] + data["rows_duplicate"] == 1


async def test_uploads_list(client):
    resp = await client.get("/uploads")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if len(data) > 0:
        entry = data[0]
        assert "dataset_type" in entry
        assert "filename" in entry
        assert "rows_received" in entry
