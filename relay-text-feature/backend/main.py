"""Local text feature. Run: python -m uvicorn backend.main:app --reload"""

import json
import os
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .schemas import MessageInput
from .text_service import EXAMPLES, ServiceError, TextService, assemble_output
from .inbox import register_inbox

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def create_app(service=None, db_path=None):
    app = FastAPI(title="Relay Text Feature", version="0.2.0")
    app.state.service = service or TextService()
    database = Path(db_path) if db_path else ROOT / "storage" / "relay.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    knowledge = json.loads((ROOT / "backend" / "knowledge.json").read_text(encoding="utf-8"))
    conversation_locks = defaultdict(threading.Lock)

    @contextmanager
    def connect():
        connection = sqlite3.connect(database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY, message_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL
            );
        """)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "backend" / "static" / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": app.state.service.mode,
                "model": app.state.service.model if app.state.service.mode == "live" else None,
                "scenario": knowledge["scenario"], "examples": EXAMPLES, "inbox_version": 2}

    @app.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        with connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY rowid", (conversation_id,)).fetchall()
        return {"messages": [dict(row) for row in rows]}

    @app.get("/requests")
    def requests(conversation_id: str | None = None):
        sql, params = "SELECT payload FROM analyses", ()
        if conversation_id:
            sql += " WHERE conversation_id=?"
            params = (conversation_id,)
        with connect() as conn:
            rows = conn.execute(sql + " ORDER BY rowid DESC LIMIT 100", params).fetchall()
        return {"items": [json.loads(row["payload"]) for row in rows]}

    @app.post("/messages")
    def receive_message(message: MessageInput):
        text = message.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Please enter a message.")
        with conversation_locks[message.conversation_id]:
            with connect() as conn:
                rows = conn.execute("SELECT id, role, text FROM messages WHERE conversation_id=? ORDER BY rowid DESC LIMIT 20", (message.conversation_id,)).fetchall()
            history = [dict(row) for row in reversed(rows)]
            message_id = "msg_" + uuid4().hex
            current = {"id": message_id, "role": "user", "text": text}
            try:
                interpretation = app.state.service.interpret(text, message_id, history, knowledge)
                output = assemble_output(interpretation, history + [current], knowledge)
            except ServiceError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            output.update(id="case_" + uuid4().hex[:12], message_id=message_id,
                          conversation_id=message.conversation_id, original_message=text,
                          created_at=datetime.now(timezone.utc).isoformat(), mode=app.state.service.mode)
            with connect() as conn:
                conn.execute("INSERT INTO messages (id, conversation_id, role, text, created_at) VALUES (?, ?, ?, ?, ?)", (message_id, message.conversation_id, "user", text, output["created_at"]))
                conn.execute("INSERT INTO messages (id, conversation_id, role, text, created_at) VALUES (?, ?, ?, ?, ?)", ("msg_" + uuid4().hex, message.conversation_id, "assistant", output["community_reply"], output["created_at"]))
                conn.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?)", (output["id"], message_id, message.conversation_id, output["created_at"], json.dumps(output, ensure_ascii=False)))
            return output

    register_inbox(app, connect, knowledge)
    return app


app = create_app()
