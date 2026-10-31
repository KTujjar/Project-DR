import base64
import logging
import time
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from conftest import Clock
from test_history import ev

from reliefvision.chat import (CHAT_SYSTEM, MAX_TURNS, CameraChat, ChatError, ChatUnavailable, SceneLogger,
                               build_context, clean_messages, make_client, should_note, timeline)
from reliefvision.history import CameraHistory
from reliefvision.schema import Insight

JPEG = b"\xff\xd8fake-jpeg"


class FakeClient:
    """Stands in for anthropic.Anthropic(): records calls, returns a scripted reply or raises."""

    def __init__(self, reply="All calm.", stop_reason="end_turn", error=None):
        self.reply, self.stop_reason, self.error, self.calls = reply, stop_reason, error, []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=[
            SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.reply)])


def api_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


@pytest.fixture
def setup():
    clock = Clock(1_793_430_000.0)
    h = CameraHistory(clock=clock)
    for i in range(6):
        h.record_event(ev(clock.t - 300 + i * 60, people=3 + i,
                          insights=[Insight(level="warn", code="dense", message="Crowd is packed")] if i == 5 else []))
    h.record_pass("cam_laptop", 7, ts=clock.t - 120)
    h.add_note("cam_laptop", "About 5 people queuing by the door.", ts=clock.t - 60)
    h.set_frame("cam_laptop", JPEG, ts=clock.t - 1)
    return h, clock


# ---------------------------------------------------------------- pure context
def test_timeline_one_line_per_minute_with_new_warnings_once():
    lines = timeline([ev(60.0, people=2), ev(70.0, people=4), ev(130.0, people=4, insights=[
        Insight(level="warn", code="x", message="Packed")]), ev(140.0, people=4, insights=[
        Insight(level="warn", code="x", message="Packed")])])
    assert len(lines) == 2
    assert "people 2-4" in lines[0] and "WARNING" not in lines[0]
    assert lines[1].count("Packed") == 1


def test_context_has_all_sections(setup):
    h, clock = setup
    ctx = build_context("cam_laptop", "Hanover High School", h.latest_event("cam_laptop"), h.events("cam_laptop"),
                        h.passes("cam_laptop"), h.notes("cam_laptop"), clock.t, True, 30)
    for part in ("Hanover High School", "LATEST METRICS", "TIMELINE", "7 people", "queuing by the door",
                 "current camera frame is attached"):
        assert part in ctx


def test_clean_messages_validates_and_trims():
    convo = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(15)]
    out = clean_messages(convo)
    assert len(out) <= MAX_TURNS and out[0]["role"] == "user" and out[-1]["content"] == "m14"
    for bad in ([], [{"role": "assistant", "content": "hi"}], [{"role": "user", "content": 3}], "nope"):
        with pytest.raises(ChatError):
            clean_messages(bad)


# ---------------------------------------------------------------- answering
def test_answer_sends_image_context_model_and_effort(setup):
    h, clock = setup
    client = FakeClient("About 8 people, calm.")
    chat = CameraChat(h, client, clock=clock)
    res = chat.answer("cam_laptop", [{"role": "user", "content": "What's happening now?"}], site="Hanover High School")
    assert res == {"reply": "About 8 people, calm.", "used": {"image": True, "minutes": 30, "scene_notes": 1}}
    (call,) = client.calls
    assert call["model"] == "claude-haiku-5-5" and call["output_config"] == {"effort": "low"}
    assert call["system"] == CHAT_SYSTEM and call["max_tokens"] == 1024
    last = call["messages"][-1]["content"]
    assert last[0]["type"] == "image" and base64.b64decode(last[0]["source"]["data"]) == JPEG
    assert "QUESTION: What's happening now?" in last[1]["text"]


def test_answer_without_fresh_frame_sends_no_image(setup):
    h, clock = setup
    clock.t += 60                                            # frame now a minute old: camera offline
    client = FakeClient()
    res = CameraChat(h, client, clock=clock).answer("cam_laptop", [{"role": "user", "content": "now?"}])
    assert res["used"]["image"] is False
    assert all(b["type"] == "text" for b in client.calls[0]["messages"][-1]["content"])


def test_answer_keeps_earlier_turns_as_plain_text(setup):
    h, clock = setup
    client = FakeClient()
    convo = [{"role": "user", "content": "how many?"}, {"role": "assistant", "content": "about 8"},
             {"role": "user", "content": "and 5 min ago?"}]
    CameraChat(h, client, clock=clock).answer("cam_laptop", convo)
    msgs = client.calls[0]["messages"]
    assert msgs[:2] == convo[:2] and msgs[2]["role"] == "user"


def test_unavailable_without_client(setup):
    h, _ = setup
    with pytest.raises(ChatUnavailable):
        CameraChat(h, None).answer("cam_laptop", [{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("error,status,text", [
    (api_error(anthropic.AuthenticationError, 401), 502, "key was rejected"),
    (api_error(anthropic.RateLimitError, 429), 429, "busy"),
    (api_error(anthropic.InternalServerError, 500), 502, "(500)"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), 502, "Can't reach"),
])
def test_api_errors_become_friendly_chat_errors(setup, error, status, text):
    h, clock = setup
    with pytest.raises(ChatError) as e:
        CameraChat(h, FakeClient(error=error), clock=clock).answer("cam_laptop", [{"role": "user", "content": "q"}])
    assert e.value.status == status and text in e.value.message


def test_refusal_is_reported(setup):
    h, clock = setup
    with pytest.raises(ChatError) as e:
        CameraChat(h, FakeClient(stop_reason="refusal"), clock=clock).answer("cam_laptop", [{"role": "user", "content": "q"}])
    assert e.value.status == 422


def test_one_question_at_a_time_per_camera(setup):
    h, clock = setup
    chat = CameraChat(h, FakeClient(), clock=clock)
    chat._lock_for("cam_laptop").acquire()
    with pytest.raises(ChatError) as e:
        chat.answer("cam_laptop", [{"role": "user", "content": "q"}])
    assert e.value.status == 429


def test_make_client_needs_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert make_client() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert make_client() is not None


# ---------------------------------------------------------------- scene log
@pytest.mark.parametrize("args,expected", [
    (dict(last_note_ts=None, frame_age=1), True),                          # first note
    (dict(last_note_ts=None, frame_age=None), False),                      # no frame
    (dict(last_note_ts=None, frame_age=30), False),                        # stale frame (camera offline)
    (dict(last_note_ts=95, frame_age=1), False),                           # inside min gap
    (dict(last_note_ts=80, frame_age=1), False),                           # nothing changed, interval not up
    (dict(last_note_ts=70, frame_age=1), True),                            # interval reached
    (dict(last_note_ts=80, frame_age=1, last_people=2, people=6), True),   # notable change
    (dict(last_note_ts=80, frame_age=1, new_warning=True), True),          # new warning
])
def test_should_note(args, expected):
    kw = dict(now=100, last_people=2, people=3, new_warning=False, interval_s=30, min_gap_s=10)
    kw.update(args)
    assert should_note(**kw) is expected


def test_scene_logger_writes_notes_and_backs_off_on_errors(setup, caplog):
    h, clock = setup
    client = FakeClient("Five people queuing near the door.")
    logger = SceneLogger(h, client, clock=clock)
    assert logger.tick("cam_laptop") is True
    assert h.notes("cam_laptop")[-1].text == "Five people queuing near the door."
    call = client.calls[0]
    assert call["max_tokens"] == 300 and call["messages"][0]["content"][0]["type"] == "image"
    assert logger.tick("cam_laptop") is False                 # min gap
    caplog.set_level(logging.WARNING)
    clock.t += 31
    h.set_frame("cam_laptop", JPEG, ts=clock.t)
    client.error = api_error(anthropic.RateLimitError, 429)
    assert logger.tick("cam_laptop") is False
    assert "scene log paused" in caplog.text and "sk-ant" not in caplog.text


def test_scene_logger_thread_stops_cleanly(setup):
    h, clock = setup
    logger = SceneLogger(h, FakeClient(), clock=clock, check_every_s=0.01)
    logger.start()
    time.sleep(0.05)
    logger.stop()
    logger.join(2)
    assert not logger.is_alive()
