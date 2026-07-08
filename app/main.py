"""Minimal notes API — the vehicle for the DevSecOps pipeline, not the point.

/health           liveness check (no AWS calls)
POST /notes       create a note in DynamoDB
GET  /notes/{id}  fetch one
GET  /notes       list (small scan)
"""

import os
import time
import uuid

import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="secure-container-pipeline notes API")

TABLE = os.environ.get("NOTES_TABLE", "secure-container-pipeline-notes")
REGION = os.environ.get("AWS_REGION", "us-east-1")
_ddb = boto3.resource("dynamodb", region_name=REGION)


def _table():
    return _ddb.Table(TABLE)


class NoteIn(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok"}


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


@app.get("/notes")
def list_notes():
    return _table().scan(Limit=50).get("Items", [])
