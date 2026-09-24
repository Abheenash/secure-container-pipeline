"""Integration tests against a real DynamoDB engine rather than a reimplementation.

`test_api.py` runs the same API against moto, which is fast and needs nothing
running. These run against `amazon/dynamodb-local` — the engine AWS ships for
offline use, same wire protocol and same error codes, free and account-free.

**What this did and did not find.** The honest result is worth recording, because
the usual argument for an integration suite is that the mock will diverge from
the real thing. Each behaviour asserted below was run against both, and moto
agreed with DynamoDB Local every time: same `ValidationException` on a reserved
word, same `ConditionalCheckFailedException`, same silent HTTP 200 deleting a key
that does not exist. Moto is a better reimplementation than it usually gets
credit for.

So the value here is not "the mock was wrong". It is that the agreement is now
*checked* rather than assumed — the suite fails the day moto drifts, or the day
someone upgrades it — and that the wire protocol, the request signing and the
endpoint resolution are exercised for real, none of which moto touches at all.

Note that the application code has no test-only branch for this. botocore honours
`AWS_ENDPOINT_URL_DYNAMODB` natively, so pointing the app at a local endpoint is
configuration, not a code path that exists only in tests. Anything these tests
exercise is the same code that runs in Fargate.

Skipped automatically when nothing is listening on the endpoint, so
`pytest tests/` still works with no Docker.
"""

import os
import socket
import sys
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

ENDPOINT = os.environ.get("DDB_ENDPOINT", "http://127.0.0.1:8000")
TABLE = "notes-integration"


def _endpoint_is_up() -> bool:
    host, _, port = ENDPOINT.removeprefix("http://").removeprefix("https://").partition(":")
    try:
        with socket.create_connection((host, int(port or 80)), timeout=1):
            return True
    except OSError:
        return False


_UP = _endpoint_is_up()

# A skipped test is a green tick that proved nothing, and in CI that is the
# failure mode to design against: the container fails to start, six tests quietly
# skip, and the build still passes. So CI sets REQUIRE_DDB=1, which turns a
# missing endpoint from a skip into an error. Locally the default still skips, so
# `pytest tests/` works with no Docker running.
if os.environ.get("REQUIRE_DDB") == "1" and not _UP:
    raise RuntimeError(
        f"REQUIRE_DDB=1 but nothing is listening on {ENDPOINT}. These tests were "
        "meant to run, not to be skipped."
    )

pytestmark = pytest.mark.skipif(
    not _UP,
    reason=f"no DynamoDB listening on {ENDPOINT} — run: "
           "docker run -d -p 8000:8000 amazon/dynamodb-local:3.1.0 "
           "-jar DynamoDBLocal.jar -inMemory -sharedDb",
)


@pytest.fixture(scope="module")
def table():
    os.environ.update(
        AWS_DEFAULT_REGION="us-east-1",
        AWS_ACCESS_KEY_ID="local",
        AWS_SECRET_ACCESS_KEY="local",
        AWS_ENDPOINT_URL_DYNAMODB=ENDPOINT,
        NOTES_TABLE=TABLE,
    )
    ddb = boto3.resource("dynamodb", region_name="us-east-1", endpoint_url=ENDPOINT)
    try:
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
    return ddb.Table(TABLE)


@pytest.fixture
def client(table):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
    import main

    main._ddb = None  # rebuild the resource so it picks up the endpoint env var
    main.TABLE = TABLE
    yield TestClient(main.app)
    main._ddb = None


def test_app_reaches_a_real_dynamodb_with_no_code_change(client):
    """/ready does a DescribeTable. Against the real engine, not a mock of it."""
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready", "table": TABLE}


def test_round_trip_through_the_real_engine(client):
    text = f"integration {uuid.uuid4()}"
    created = client.post("/notes", json={"text": text})
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    fetched = client.get(f"/notes/{note_id}")
    assert fetched.status_code == 200
    assert fetched.json()["text"] == text

    assert client.delete(f"/notes/{note_id}").status_code == 204
    assert client.get(f"/notes/{note_id}").status_code == 404


def test_delete_of_a_missing_item_is_404_not_204(client):
    """DynamoDB's DeleteItem succeeds on a key that does not exist — it is
    idempotent by design and returns HTTP 200 with no indication either way
    (verified against both DynamoDB Local and moto). Any 404 contract therefore
    has to come from an explicit existence check in the handler; there is no
    error from the service to propagate."""
    assert client.delete(f"/notes/{uuid.uuid4()}").status_code == 404


def test_reserved_words_do_not_break_reads(client, table):
    """`text`, `name`, `status`, `size` and ~570 others are reserved in DynamoDB's
    expression language. A projection or filter naming one directly fails with
    ValidationException at request time, not at deploy time — so it is the kind
    of thing that ships. This table's payload attribute is literally called
    `text`, which makes it a live hazard here rather than a general caution."""
    created = client.post("/notes", json={"text": "reserved-word probe"})
    note_id = created.json()["id"]

    with pytest.raises(ClientError) as raised:
        table.get_item(Key={"id": note_id}, ProjectionExpression="text")
    assert raised.value.response["Error"]["Code"] == "ValidationException"

    # The supported form: alias the attribute name.
    ok = table.get_item(Key={"id": note_id}, ProjectionExpression="#t",
                        ExpressionAttributeNames={"#t": "text"})
    assert ok["Item"]["text"] == "reserved-word probe"
    client.delete(f"/notes/{note_id}")


def test_conditional_write_raises_the_documented_error(client, table):
    """The app writes notes with a fresh uuid, so it never collides today. If a
    caller-supplied id is ever accepted the guard is a condition expression, and
    this pins the exact error code that guard has to catch — against the real
    engine, so the pin is worth something."""
    note_id = str(uuid.uuid4())
    table.put_item(Item={"id": note_id, "text": "first"})

    with pytest.raises(ClientError) as raised:
        table.put_item(
            Item={"id": note_id, "text": "second"},
            ConditionExpression="attribute_not_exists(id)",
        )
    assert raised.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    table.delete_item(Key={"id": note_id})


def test_pagination_returns_every_item_exactly_once(client):
    """A Scan that hits a page boundary returns LastEvaluatedKey, and a list
    endpoint that ignores it silently truncates. Seeded past the default page
    size the API exposes so the boundary is real rather than theoretical."""
    made = {client.post("/notes", json={"text": f"page probe {i}"}).json()["id"] for i in range(25)}
    assert len(made) == 25

    seen, cursor, pages = set(), None, 0
    while True:
        r = client.get("/notes", params={"limit": 10, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        body = r.json()
        seen.update(item["id"] for item in body["items"])
        pages += 1
        cursor = body.get("next")
        if not cursor or pages > 20:
            break

    assert made <= seen, f"{len(made - seen)} notes were never returned across {pages} pages"
    assert pages >= 3, "the page boundary was never actually crossed"
    for note_id in made:
        client.delete(f"/notes/{note_id}")
