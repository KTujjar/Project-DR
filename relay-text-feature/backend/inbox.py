"""Incoming community messages, asynchronous interpretation, reviewed web replies."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException

from .schemas import IntakeInput, ReviewedReply
from .text_service import ServiceError, assemble_output


def register_inbox(app, connect, knowledge):
    with connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "kind" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'message'")
        conn.execute("""CREATE TABLE IF NOT EXISTS reviewed_replies (
            case_id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL,
            message_id TEXT NOT NULL
        )""")

    def now():
        return datetime.now(timezone.utc).isoformat()

    def read_case(conn, case_id):
        row = conn.execute("SELECT payload FROM analyses WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Message not found.")
        return json.loads(row["payload"])

    def save_case(conn, payload):
        conn.execute("UPDATE analyses SET payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), payload["id"]))

    def analyze(case_id):
        with connect() as conn:
            case = read_case(conn, case_id)
            rows = conn.execute("""SELECT id, role, text FROM messages
                WHERE conversation_id=? AND rowid < (SELECT rowid FROM messages WHERE id=?)
                ORDER BY rowid DESC LIMIT 20""", (case["conversation_id"], case["message_id"])).fetchall()
        history = [dict(row) for row in reversed(rows)]
        current = {"id": case["message_id"], "role": "user", "text": case["message_context"]}
        try:
            interpreted = app.state.service.interpret(current["text"], current["id"], history, knowledge)
            output = assemble_output(interpreted, history + [current], knowledge)
            draft = output["community_reply"].replace(
                "Your delivery report has been recorded for a responder to check. This report has not changed inventory or marked a delivery complete.",
                "Thanks for the update. A responder will check the delivery record and the amount still outstanding.")
            changes = {"interpretation": output["interpretation"], "suggested_reply": output["community_reply"],
                       "clarifying_questions": output["clarifying_questions"], "sources": output["sources"],
                       "status": output["status"], "processing_status": "ready", "analysis_error": None}
            changes["suggested_reply"] = draft
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ServiceError) else "Automatic interpretation could not complete. Review the original message and write a reply."
            fallback = dict(case["interpretation"])
            fallback["responder_summary"] = "Automatic interpretation is unavailable. Read the original message and review it manually."
            changes = {"processing_status": "unavailable", "analysis_error": reason[:500], "interpretation": fallback}
        with connect() as conn:
            # A coordinator may already have replied while the model was running.
            conn.execute("BEGIN IMMEDIATE")
            latest = read_case(conn, case_id)
            latest.update(changes, updated_at=now())
            save_case(conn, latest)

    @app.post("/intake", status_code=202)
    def intake(message: IntakeInput, background: BackgroundTasks):
        text = message.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Please enter a message.")
        timestamp = now()
        case_id, message_id = "R-" + uuid4().hex[:8].upper(), "msg_" + uuid4().hex
        location = message.reported_location.strip()
        context = text + ("\nLocation provided in form: " + location if location else "")
        acknowledgment = f"Message received for responder review. Reference {case_id}. This does not confirm assistance or a delivery."
        case = {
            "schema_version": 2, "id": case_id, "message_id": message_id,
            "conversation_id": message.conversation_id, "sender_name": message.sender_name.strip() or "Community member",
            "contact": message.contact.strip(), "reported_location": location, "channel": message.channel,
            "original_message": text, "message_context": context, "community_reply": acknowledgment,
            "suggested_reply": "", "reply_text": None, "reply_sent_at": None,
            "created_at": timestamp, "updated_at": timestamp, "mode": app.state.service.mode,
            "review_status": "new", "review_required": True, "processing_status": "processing",
            "analysis_error": None, "status": "pending_review", "clarifying_questions": [], "sources": [],
            "interpretation": {"purposes": [], "needs": [], "location": None, "access_barriers": [],
                               "delivery_report": None, "responder_summary": "Awaiting interpretation; the original message is available for review.",
                               "faq_ids": [], "unanswered_questions": [], "evidence": []},
        }
        with connect() as conn:
            conn.execute("INSERT INTO messages (id, conversation_id, role, text, created_at, kind) VALUES (?, ?, 'user', ?, ?, 'incoming')",
                         (message_id, message.conversation_id, context, timestamp))
            conn.execute("INSERT INTO messages (id, conversation_id, role, text, created_at, kind) VALUES (?, ?, 'assistant', ?, ?, 'acknowledgment')",
                         ("msg_" + uuid4().hex, message.conversation_id, acknowledgment, timestamp))
            conn.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?)",
                         (case_id, message_id, message.conversation_id, timestamp, json.dumps(case, ensure_ascii=False)))
        background.add_task(analyze, case_id)
        return case

    @app.get("/inbox")
    def inbox():
        with connect() as conn:
            rows = conn.execute("SELECT payload FROM analyses ORDER BY rowid DESC LIMIT 2000").fetchall()
        latest = {}
        for row in rows:
            case = json.loads(row["payload"])
            if case.get("schema_version") != 2:
                continue
            latest.setdefault(case["conversation_id"], case)
        return {"items": list(latest.values())[:100]}

    @app.post("/inbox/{case_id}/reply")
    def reply(case_id: str, body: ReviewedReply):
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Write a reply before sending.")
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            case = read_case(conn, case_id)
            if case.get("schema_version") != 2:
                raise HTTPException(status_code=409, detail="Use the current community inbox for this message.")
            sent = conn.execute("SELECT text FROM reviewed_replies WHERE case_id=?", (case_id,)).fetchone()
            if sent:
                if sent["text"] == text:
                    return case
                raise HTTPException(status_code=409, detail="A reply was already sent for this message.")
            latest = conn.execute("SELECT id FROM analyses WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1", (case["conversation_id"],)).fetchone()
            if latest["id"] != case_id:
                raise HTTPException(status_code=409, detail="A new community message arrived. Review the latest message before replying.")
            timestamp, reply_id = now(), "msg_" + uuid4().hex
            conn.execute("INSERT INTO messages (id, conversation_id, role, text, created_at, kind) VALUES (?, ?, 'assistant', ?, ?, 'reviewed_reply')",
                         (reply_id, case["conversation_id"], text, timestamp))
            conn.execute("INSERT INTO reviewed_replies VALUES (?, ?, ?, ?)", (case_id, text, timestamp, reply_id))
            case.update(reply_text=text, reply_sent_at=timestamp, updated_at=timestamp, review_required=False,
                        review_status="needs_information" if body.awaiting_information else "replied")
            save_case(conn, case)
        return case

    @app.post("/inbox/{case_id}/retry")
    def retry(case_id: str, background: BackgroundTasks):
        with connect() as conn:
            case = read_case(conn, case_id)
            if case.get("schema_version") != 2 or case["reply_sent_at"]:
                raise HTTPException(status_code=409, detail="This message does not need another AI draft.")
            if case["processing_status"] == "processing":
                return case
            case.update(processing_status="processing", analysis_error=None, updated_at=now())
            save_case(conn, case)
        background.add_task(analyze, case_id)
        return case
