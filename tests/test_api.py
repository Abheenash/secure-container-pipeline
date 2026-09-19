"""API tests against a moto-mocked DynamoDB — no AWS account, runs in the pipeline as gate #4."""
import os
import sys

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ["NOTES_TABLE"] = "notes-test"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import main  # noqa: E402


@pytest.fixture
def client():
    with mock_aws():
        main._ddb = None  # force a fresh resource inside the mock
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(TableName="notes-test", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                         BillingMode="PAY_PER_REQUEST")
        yield TestClient(main.app)
        main._ddb = None


def test_health_needs_no_aws():
    main._ddb = None
    r = TestClient(main.app).get("/health")  # no mock active: must still be 200
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_reports_table_reachable(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_ready_is_503_when_the_table_is_missing():
    with mock_aws():
        main._ddb = None
        r = TestClient(main.app).get("/ready")
        assert r.status_code == 503 and r.json()["status"] == "not ready"
    main._ddb = None


def test_create_get_delete_roundtrip(client):
    r = client.post("/notes", json={"text": "hello"})
    assert r.status_code == 201
    note = r.json()
    assert note["text"] == "hello" and "id" in note and note["createdAt"] > 0
    assert client.get(f"/notes/{note['id']}").json() == note
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.get(f"/notes/{note['id']}").status_code == 404
    assert client.delete(f"/notes/{note['id']}").status_code == 404


def test_validation(client):
    assert client.post("/notes", json={"text": ""}).status_code == 422
    assert client.post("/notes", json={"text": "x" * 4001}).status_code == 422
    assert client.post("/notes", json={}).status_code == 422
    assert client.post("/notes", data="not json").status_code == 422
    assert client.post("/notes", json={"text": "x" * 4000}).status_code == 201


def test_list_is_paginated_and_bounded(client):
    for i in range(7):
        client.post("/notes", json={"text": f"n{i}"})
    page1 = client.get("/notes?limit=3").json()
    assert len(page1["items"]) == 3 and page1["next"]
    page2 = client.get(f"/notes?limit=3&cursor={page1['next']}").json()
    assert len(page2["items"]) == 3
    seen = {n["id"] for n in page1["items"]} | {n["id"] for n in page2["items"]}
    assert len(seen) == 6
    assert client.get("/notes?limit=0").status_code == 422
    assert client.get("/notes?limit=101").status_code == 422


def test_security_headers_and_request_id(client):
    r = client.get("/health", headers={"X-Amzn-Trace-Id": "Root=1-abc"})
    assert r.headers["X-Request-Id"] == "Root=1-abc"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
    r2 = client.get("/health")
    assert r2.headers["X-Request-Id"]  # generated when the ALB didn't supply one


def test_docs_are_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_every_request_is_logged_as_json(client):
    import io, json, logging
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    main._log.addHandler(h)
    try:
        client.post("/notes", json={"text": "log me"})
    finally:
        main._log.removeHandler(h)
    lines = [l for l in buf.getvalue().splitlines() if l.startswith("{")]
    assert lines
    rec = json.loads(lines[-1])
    assert rec["method"] == "POST" and rec["path"] == "/notes" and rec["status"] == 201 and "ms" in rec
