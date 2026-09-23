"""Minimal notes API — the vehicle for the DevSecOps pipeline, not the point.

GET  /health          liveness: the process is up (no AWS calls — never fails because a
                      dependency is down, which is what a liveness probe must not do)
GET  /ready           readiness: the DynamoDB table is reachable (this is what the ALB
                      should gate traffic on)
POST /notes           create a note
GET  /notes/{id}      fetch one
GET  /notes           list (paginated with a cursor, bounded page size)
DELETE /notes/{id}    delete one

Every request gets a request id (from the ALB's X-Amzn-Trace-Id when present) and one
structured JSON log line; responses carry conservative security headers.
"""

import json
import logging
import os
import sys
import time
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

TABLE = os.environ.get("NOTES_TABLE", "secure-container-pipeline-notes")
REGION = os.environ.get("AWS_REGION", "us-east-1")
MAX_TEXT = int(os.environ.get("MAX_TEXT", "4000"))
# Drill switch (deploy/bad-release-drill.md): a release with FAIL_READY=1 reports not-ready
# while staying alive — the shape of a dependency outage — so the rollback can be seen to fire.
FAIL_READY = os.environ.get("FAIL_READY", "") == "1"

app = FastAPI(title="secure-container-pipeline notes API", docs_url=None, redoc_url=None, openapi_url=None)

_log = logging.getLogger("notes")
_log.setLevel(logging.INFO)
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter("%(message)s"))
_log.handlers = [_h]
_log.propagate = False

_ddb = None


def _table():
    """Resolved lazily so the module imports (and /health answers) without AWS."""
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=REGION)
    return _ddb.Table(TABLE)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


@app.middleware("http")
async def request_context(request: Request, call_next):
    t0 = time.time()
    rid = request.headers.get("x-amzn-trace-id") or request.headers.get("x-request-id") or str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        _log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path,
                              "status": 500, "ms": round((time.time() - t0) * 1000, 1)}))
        raise
    response.headers["X-Request-Id"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    _log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path,
                          "status": response.status_code, "ms": round((time.time() - t0) * 1000, 1)}))
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response):
    if FAIL_READY:
        response.status_code = 503
        return {"status": "not ready", "reason": "FAIL_READY drill flag"}
    try:
        _table().load()  # DescribeTable through the VPC endpoint: cheap, and proves the path
        return {"status": "ready", "table": TABLE}
    except (ClientError, BotoCoreError) as e:
        response.status_code = 503
        return {"status": "not ready", "reason": type(e).__name__}


@app.post("/notes", status_code=201)
def create_note(note: NoteIn):
    item = {"id": str(uuid.uuid4()), "text": note.text, "createdAt": int(time.time())}
    _table().put_item(Item=item)
    return item


@app.get("/notes/{note_id}")
def get_note(note_id: str):
    item = _table().get_item(Key={"id": note_id}).get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="note not found")
    return item


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str):
    try:
        _table().delete_item(Key={"id": note_id}, ConditionExpression="attribute_exists(id)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HTTPException(status_code=404, detail="note not found") from e
        raise
    return Response(status_code=204)


@app.get("/notes")
def list_notes(limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
    kwargs = {"Limit": limit}
    if cursor:
        kwargs["ExclusiveStartKey"] = {"id": cursor}
    page = _table().scan(**kwargs)
    return {"items": page.get("Items", []), "next": (page.get("LastEvaluatedKey") or {}).get("id")}
