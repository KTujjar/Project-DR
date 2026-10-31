import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import create_app
from backend.schemas import Interpretation, Need
from backend.text_service import EXAMPLES, ServiceError, TextService, assemble_output


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(service=TextService(), db_path=tmp_path / "test.sqlite3"))


def submit(client, text, conversation="demo-1"):
    return client.post("/messages", json={"conversation_id": conversation, "text": text})


def test_preview_makes_multiple_purposes_visible_without_confirming_delivery(client):
    data = submit(client, EXAMPLES[0]["text"]).json()
    assert data["interpretation"]["purposes"] == ["assistance_request", "question"]
    assert data["interpretation"]["needs"][0]["quantity"] == 20
    assert data["review_required"] is True
    assert "Delivery has not been confirmed" in data["community_reply"]
    assert data["sources"][0]["id"] == "delivery-process"


def test_people_count_is_not_a_supply_quantity(client):
    data = submit(client, EXAMPLES[3]["text"]).json()
    assert data["interpretation"]["needs"][0]["quantity"] is None
    assert data["status"] == "needs_clarification"
    assert data["clarifying_questions"]


def test_qna_is_exactly_from_the_reference_and_unknowns_escalate(client):
    data = submit(client, EXAMPLES[1]["text"]).json()
    assert data["community_reply"] == data["sources"][0]["answer"]
    assert data["status"] == "answered_from_reference"
    unknown = submit(client, EXAMPLES[5]["text"]).json()
    assert unknown["sources"] == []
    assert unknown["review_required"] is True
    assert "do not have approved information" in unknown["community_reply"]


def test_partial_receipt_is_a_report_not_a_new_request_or_inventory_action(client):
    data = submit(client, EXAMPLES[4]["text"]).json()
    assert data["interpretation"]["needs"] == []
    assert data["interpretation"]["delivery_report"]
    assert "has not changed inventory" in data["community_reply"]
    assert "dispatch ID" in data["clarifying_questions"][0]


def test_preview_rejects_arbitrary_text_honestly_and_does_not_save_it(client):
    response = submit(client, "Some arbitrary text")
    assert response.status_code == 503
    assert "Preview mode" in response.json()["detail"]
    assert client.get("/conversations/demo-1").json()["messages"] == []


def test_saved_chat_and_inbox_are_separate_per_conversation(client):
    submit(client, EXAMPLES[0]["text"], "a")
    submit(client, EXAMPLES[1]["text"], "b")
    assert len(client.get("/conversations/a").json()["messages"]) == 2
    assert len(client.get("/requests?conversation_id=a").json()["items"]) == 1
    assert len(client.get("/requests").json()["items"]) == 2


def test_empty_and_invalid_messages_do_not_create_records(client):
    assert submit(client, "   ").status_code == 422
    assert submit(client, "x" * 4001).status_code == 422
    assert submit(client, "hello", "bad/id").status_code == 422
    assert client.get("/requests").json()["items"] == []


def test_invalid_quantities_are_rejected():
    for value in [-2, 0, 1.5, "20"]:
        with pytest.raises(ValidationError):
            Need(item="food", quantity=value, unit="packs")


def test_fabricated_quotes_prevent_a_record_from_being_saved(client):
    original_service = client.app.state.service

    class Fabricated:
        mode = "live"
        model = "fake-test-model"

        def interpret(self, text, message_id, history, knowledge):
            result = original_service._preview(EXAMPLES[0]["text"], message_id)
            result.evidence[0].quote = "This was never said."
            return result

    client.app.state.service = Fabricated()
    assert submit(client, EXAMPLES[0]["text"]).status_code == 503
    assert client.get("/requests").json()["items"] == []


def test_actual_service_sends_followup_context_to_sdk_and_persists_it(client, monkeypatch):
    service = TextService()
    service.mode = "live"
    seen = []

    def fake_parse(**kwargs):
        payload = json.loads(kwargs["messages"][0]["content"])
        seen.append(payload)
        current = payload["current_message"]
        result = service._preview(EXAMPLES[0]["text"], current["id"])
        result.evidence[0].quote = current["text"]
        return SimpleNamespace(parsed_output=result)

    service.client = SimpleNamespace(messages=SimpleNamespace(parse=fake_parse))
    client.app.state.service = service
    assert submit(client, "We need food.").status_code == 200
    assert submit(client, "20 food packs at Riverside School.").status_code == 200
    assert seen[1]["conversation"][0]["text"] == "We need food."
    assert seen[1]["conversation"][1]["role"] == "assistant"
    assert seen[1]["current_message"]["text"] == "20 food packs at Riverside School."


def test_unknown_reference_ids_cannot_supply_an_answer(client):
    original = client.app.state.service

    class WrongSource:
        mode = "live"
        model = "fake-test-model"

        def interpret(self, text, message_id, history, knowledge):
            result = original._preview(EXAMPLES[1]["text"], message_id)
            result.faq_ids = ["invented-source"]
            return result

    client.app.state.service = WrongSource()
    result = submit(client, EXAMPLES[1]["text"]).json()
    assert result["sources"] == []
    assert "do not have approved information" in result["community_reply"]
    assert result["review_required"] is True


def test_partial_answer_does_not_hide_an_unanswered_question(client):
    original = client.app.state.service

    class Partial:
        mode = "live"
        model = "fake-test-model"

        def interpret(self, text, message_id, history, knowledge):
            result = original._preview(EXAMPLES[1]["text"], message_id)
            result.evidence[0].quote = text
            result.unanswered_questions = ["Is the bridge safe?"]
            return result

    client.app.state.service = Partial()
    result = submit(client, "Where is food available, and is the bridge safe?").json()
    assert result["sources"]
    assert result["review_required"] is True
    assert "bridge safe" in result["community_reply"]
