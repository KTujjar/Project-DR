import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.text_service import EXAMPLES, ServiceError, TextService


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(service=TextService(), db_path=tmp_path / "inbox.sqlite3"))


def incoming(client, conversation="person-a", index=0, **extra):
    return client.post("/intake", json={"conversation_id": conversation, "sender_name": "Shelter volunteer",
                                       "text": EXAMPLES[index]["text"], **extra})


def latest(client):
    return client.get("/inbox").json()["items"][0]


def test_inbox_starts_empty_and_received_messages_are_global(client):
    assert client.get("/inbox").json()["items"] == []
    assert incoming(client, "a").status_code == 202
    assert incoming(client, "b", 1).status_code == 202
    assert len(client.get("/inbox").json()["items"]) == 2
    assert latest(client)["sender_name"] == "Shelter volunteer"


def test_ai_draft_is_not_sent_to_the_community(client):
    incoming(client)
    case = latest(client)
    assert case["suggested_reply"]
    assert case["review_required"]
    assert case["reply_sent_at"] is None
    thread = client.get("/conversations/person-a").json()["messages"]
    assert len(thread) == 2
    assert thread[1]["kind"] == "acknowledgment"
    assert thread[1]["text"] != case["suggested_reply"]


def test_a_failed_ai_call_does_not_lose_the_community_message(client):
    class Unavailable:
        mode, model = "live", "test-model"

        def interpret(self, *args):
            raise ServiceError("API access is unavailable.")

    client.app.state.service = Unavailable()
    assert incoming(client).status_code == 202
    case = latest(client)
    assert case["processing_status"] == "unavailable"
    assert case["original_message"] == EXAMPLES[0]["text"]
    assert case["review_required"]
    result = client.post(f"/inbox/{case['id']}/reply", json={"text": "Please confirm the town and a collection contact."})
    assert result.status_code == 200
    assert result.json()["reply_sent_at"]


def test_reviewed_reply_is_saved_once_and_visible_in_the_web_conversation(client):
    incoming(client)
    case_id = latest(client)["id"]
    body = {"text": "Please confirm a collection contact.", "awaiting_information": True}
    first = client.post(f"/inbox/{case_id}/reply", json=body)
    duplicate = client.post(f"/inbox/{case_id}/reply", json=body)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["review_status"] == "needs_information"
    assert first.json()["review_required"] is False
    replies = [m for m in client.get("/conversations/person-a").json()["messages"] if m["kind"] == "reviewed_reply"]
    assert len(replies) == 1
    assert replies[0]["text"] == body["text"]


def test_a_new_followup_reopens_the_conversation_inbox(client):
    incoming(client)
    first = latest(client)
    client.post(f"/inbox/{first['id']}/reply", json={"text": "Please confirm the quantity."})
    incoming(client, index=3)
    items = client.get("/inbox").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] != first["id"]
    assert items[0]["review_required"] is True
    assert items[0]["interpretation"]["needs"][0]["quantity"] is None


def test_stale_reply_is_blocked_when_a_new_community_message_arrives(client):
    incoming(client)
    old = latest(client)
    incoming(client, index=1)
    response = client.post(f"/inbox/{old['id']}/reply", json={"text": "Old response"})
    assert response.status_code == 409
    assert "new community message" in response.json()["detail"].lower()


def test_blank_incoming_text_and_blank_reply_are_rejected(client):
    assert client.post("/intake", json={"conversation_id": "a", "text": "  "}).status_code == 422
    incoming(client)
    assert client.post(f"/inbox/{latest(client)['id']}/reply", json={"text": "  "}).status_code == 422


def test_schema_upgrade_preserves_existing_messages(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)")
        conn.execute("INSERT INTO messages VALUES ('old-msg', 'old-thread', 'user', 'Earlier message', '2026-10-30T00:00:00Z')")
    client = TestClient(create_app(service=TextService(), db_path=path))
    assert client.get("/conversations/old-thread").json()["messages"][0]["text"] == "Earlier message"
    assert incoming(client).status_code == 202
