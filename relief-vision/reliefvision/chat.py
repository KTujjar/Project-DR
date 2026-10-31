"""Camera chatbot and scene log (Claude, via the Anthropic Python SDK). Only used with --serve.

- CameraChat answers a coordinator's questions about one camera from its last 30 minutes of
  crowd metrics (CameraHistory), finished passes, scene-log notes and the current frame.
- SceneLogger keeps that scene log: every ~30 s, or sooner when something notable changes, it asks
  the model for a 1-2 sentence note about the current frame, so past moments can be asked about.

Needs ANTHROPIC_API_KEY in the environment (./start.sh passes the one in relay-text-feature/.env).
Without it, chat raises ChatUnavailable and no scene notes are made. Frames go to Anthropic only
for a chat question or a scene note; nothing is stored on disk. The model is told never to
identify people.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence

from .history import CameraHistory, PassRecord, SceneNote
from .schema import Event

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-5-5"
MAX_TURNS = 10            # conversation turns sent back to the model
MAX_QUESTION_CHARS = 2000
FRAME_MAX_AGE_S = 10.0    # an older frame means the camera stopped; don't describe it as "now"

# The system prompt is a fixed string (no timestamps), but it's below the minimum size the API
# caches, so no cache_control is set; the per-question context goes in the last user turn.
CHAT_SYSTEM = """You are the camera assistant in a disaster-relief coordinator dashboard.
You answer questions about ONE camera at a relief site, using only the data in the user's last
message: the latest crowd metrics, a minute-by-minute timeline of the last 30 minutes, finished
"passes" (a robot or person sweeping a line and counting unique people), scene-log notes written
from earlier camera frames, and, when attached, the current camera image.

Rules:
- Answer only from that data and the image. If something isn't in it, say you can't tell.
- Use the clock times given (local time). Be specific about when things happened.
- Counts are estimates from a person detector; say "about" and mention when the data says
  "at least N" or the camera was moving.
- Never identify people or guess at identity, age, ethnicity or other personal traits. Describe
  activity, crowding, movement, mobility aids and possible need for help, not individuals.
- Keep answers short: a few sentences or a short list. Point out anything that looks urgent."""

SCENE_SYSTEM = """You write a short log of what a camera at a disaster-relief site shows.
Describe the scene in 1-2 plain sentences: roughly how many people, what they are doing
(queuing, waiting, walking, sitting), crowding or bottlenecks, mobility aids, and anything that
might need attention (someone on the floor, distress, blocked exits). Never identify anyone or
describe faces, identity, age, ethnicity or clothing that singles a person out. If the image is
too dark or unclear, say so in a few words."""


class ChatUnavailable(Exception):
    """No API key / chat disabled: the dashboard shows how to turn it on."""


class ChatError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def make_client():
    """Anthropic client from ANTHROPIC_API_KEY, or None if no key is configured."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return None
    import anthropic

    return anthropic.Anthropic()


# ----------------------------------------------------------------------------- context (pure)
def clock_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _aids_text(aids: Optional[Dict[str, int]]) -> str:
    seen = {k: v for k, v in (aids or {}).items() if v}
    return ", ".join(f"{v} {k}" for k, v in seen.items())


def timeline(events: Sequence[Event], bucket_s: float = 60.0) -> List[str]:
    """One line per minute: people range, density, movement, children, aids, new warnings."""
    if not events:
        return []
    buckets: Dict[int, List[Event]] = {}
    for ev in events:
        buckets.setdefault(int(ev.ts // bucket_s), []).append(ev)
    density_rank = {"low": 0, "medium": 1, "high": 2, "packed": 3}
    seen_warnings: set = set()
    lines = []
    for key in sorted(buckets):
        evs = buckets[key]
        people = [e.people for e in evs]
        parts = [f"people {min(people)}" + (f"-{max(people)}" if max(people) != min(people) else "")]
        if any(e.people_is_lower_bound for e in evs):
            parts[-1] += " (at least)"
        parts.append("density " + max((e.density for e in evs), key=density_rank.get))
        modes = {e.camera_mode for e in evs}
        parts.append("camera moving" if modes == {"mobile"} else ("camera moving/still" if len(modes) > 1 else "camera still"))
        flows = Counter(e.dominant_flow for e in evs if e.dominant_flow)
        if flows:
            parts.append("flow " + flows.most_common(1)[0][0])
        still = [e.stationary_fraction for e in evs if e.stationary_fraction is not None]
        if still:
            parts.append(f"{round(100 * sum(still) / len(still))}% standing still")
        kids = [e.children_est for e in evs if e.children_est is not None]
        if kids and max(kids):
            parts.append(f"children ~{max(kids)}")
        aids = _aids_text(evs[-1].mobility_aids)
        if aids:
            parts.append("aids: " + aids)
        new = [i.message for e in evs for i in e.insights if i.level == "warn" and i.message not in seen_warnings]
        for msg in dict.fromkeys(new):
            seen_warnings.add(msg)
        if new:
            parts.append("WARNING: " + " / ".join(dict.fromkeys(new)))
        lines.append(f"{clock_time(key * bucket_s)}  " + ", ".join(parts))
    return lines


def latest_summary(ev: Optional[Event]) -> str:
    if ev is None:
        return "No measurements yet."
    bits = [f"{'at least ' if ev.people_is_lower_bound else ''}{ev.people} people in view",
            f"density {ev.density} ({round(ev.crowd_fraction * 100)}% of frame)",
            f"camera {ev.camera_mode}"]
    if ev.children_est is not None:
        bits.append(f"children ~{ev.children_est}")
    aids = _aids_text(ev.mobility_aids)
    bits.append("mobility aids: " + (aids or ("none" if ev.mobility_aids is not None else "detector off")))
    if ev.dominant_flow:
        bits.append(f"flow {ev.dominant_flow}")
    if ev.stationary_fraction is not None:
        bits.append(f"{round(ev.stationary_fraction * 100)}% standing still")
    if ev.hotspots:
        bits.append("crowded+still areas: " + ", ".join(h.region for h in ev.hotspots))
    if ev.free_space_fraction is not None:
        bits.append(f"free space {round(ev.free_space_fraction * 100)}%")
    text = f"At {clock_time(ev.ts)}: " + "; ".join(bits) + "."
    if ev.insights:
        text += "\nCurrent notes: " + " ".join(i.message for i in ev.insights)
    return text


def build_context(camera_id: str, site: str, latest: Optional[Event], events: Sequence[Event],
                  passes: Sequence[PassRecord], notes: Sequence[SceneNote], now: float,
                  image_attached: bool, minutes: int) -> str:
    sections = [
        f"Camera {camera_id} at {site}. Current time {clock_time(now)}.",
        "LATEST METRICS\n" + latest_summary(latest),
        f"TIMELINE (last {minutes} min, one line per minute)\n" + ("\n".join(timeline(events)) or "No data."),
        "FINISHED PASSES (unique people per sweep)\n"
        + ("\n".join(f"{clock_time(p.ts)}  {p.total} people" for p in passes) or "None."),
        "SCENE LOG (notes written from camera frames)\n"
        + ("\n".join(f"{clock_time(n.ts)}  {n.text}" for n in notes) or "No notes yet."),
        "IMAGE: the current camera frame is attached." if image_attached
        else "IMAGE: no current frame available (camera offline or not started).",
    ]
    return "\n\n".join(sections)


def clean_messages(messages: Any) -> List[Dict[str, str]]:
    """Validates the dashboard's conversation: alternating user/assistant text, ending with a question."""
    if not isinstance(messages, list) or not messages:
        raise ChatError(422, "Send at least one message.")
    out: List[Dict[str, str]] = []
    for m in messages[-MAX_TURNS:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            raise ChatError(422, "Each message needs a role (user/assistant) and text content.")
        text = m["content"].strip()[:MAX_QUESTION_CHARS]
        if text:
            out.append({"role": m["role"], "content": text})
    while out and out[0]["role"] != "user":   # the API needs the conversation to start with the user
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise ChatError(422, "The last message must be a question.")
    return out


def _image_block(jpeg: bytes) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(jpeg).decode("ascii")}}


def _call(client, model: str, system: str, messages: List[Dict[str, Any]], max_tokens: int) -> str:
    """One model call with the SDK's typed errors mapped to friendly ChatErrors."""
    import anthropic

    try:
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                      output_config={"effort": "low"}, messages=messages)
    except anthropic.AuthenticationError:
        raise ChatError(502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in relay-text-feature/.env.")
    except anthropic.PermissionDeniedError:
        raise ChatError(502, "The Anthropic API key isn't allowed to use this model.")
    except anthropic.RateLimitError:
        raise ChatError(429, "The AI is busy (rate limited). Try again in a moment.")
    except anthropic.BadRequestError as e:
        raise ChatError(502, f"The AI rejected the request: {e.message}")
    except anthropic.APIStatusError as e:
        raise ChatError(502, f"The AI service returned an error ({e.status_code}). Try again.")
    except anthropic.APIConnectionError:
        raise ChatError(502, "Can't reach the AI service. Check the internet connection.")
    if resp.stop_reason == "refusal":
        raise ChatError(422, "The AI declined to answer that question.")
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


# ----------------------------------------------------------------------------- chat
class CameraChat:
    def __init__(self, history: CameraHistory, client, model: str = DEFAULT_MODEL, include_image: bool = True,
                 minutes: int = 30, max_tokens: int = 1024, clock: Callable[[], float] = time.time):
        self.history, self.client, self.model = history, client, model
        self.include_image, self.minutes, self.max_tokens = include_image, minutes, max_tokens
        self._clock = clock
        self._busy: Dict[str, threading.Lock] = {}
        self._busy_guard = threading.Lock()

    @property
    def available(self) -> bool:
        return self.client is not None

    def _lock_for(self, camera_id: str) -> threading.Lock:
        with self._busy_guard:
            return self._busy.setdefault(camera_id, threading.Lock())

    def answer(self, camera_id: str, messages: Any, site: Optional[str] = None) -> Dict[str, Any]:
        if not self.available:
            raise ChatUnavailable("Add an Anthropic API key (ANTHROPIC_API_KEY in relay-text-feature/.env) "
                                  "and restart to use the camera chat.")
        convo = clean_messages(messages)
        lock = self._lock_for(camera_id)
        if not lock.acquire(blocking=False):
            raise ChatError(429, "Still answering the previous question for this camera.")
        try:
            now = self._clock()
            frame, frame_ts = self.history.latest_frame(camera_id)
            use_image = bool(self.include_image and frame and frame_ts and now - frame_ts <= FRAME_MAX_AGE_S)
            notes = self.history.notes(camera_id)
            context = build_context(camera_id, site or "its site", self.history.latest_event(camera_id),
                                    self.history.events(camera_id), self.history.passes(camera_id), notes,
                                    now, use_image, self.minutes)
            question = convo[-1]["content"]
            last: List[Dict[str, Any]] = [_image_block(frame)] if use_image else []
            last.append({"type": "text", "text": context + "\n\nQUESTION: " + question})
            api_messages = convo[:-1] + [{"role": "user", "content": last}]
            reply = _call(self.client, self.model, CHAT_SYSTEM, api_messages, self.max_tokens)
            return {"reply": reply or "I couldn't produce an answer.",
                    "used": {"image": use_image, "minutes": self.minutes, "scene_notes": len(notes)}}
        finally:
            lock.release()


# ----------------------------------------------------------------------------- scene log
def should_note(now: float, last_note_ts: Optional[float], last_people: Optional[int], people: Optional[int],
                new_warning: bool, frame_age: Optional[float], interval_s: float, min_gap_s: float,
                people_change: int = 3) -> bool:
    """Whether to write a scene note now (pure, so the triggers are easy to test)."""
    if frame_age is None or frame_age > FRAME_MAX_AGE_S:
        return False                               # camera offline / stale: nothing new to see
    if last_note_ts is None:
        return True
    since = now - last_note_ts
    if since < min_gap_s:
        return False
    if since >= interval_s:
        return True
    changed = people is not None and last_people is not None and abs(people - last_people) >= people_change
    return changed or new_warning


class SceneLogger(threading.Thread):
    """Writes the scene log for every camera in the history (one background thread)."""

    def __init__(self, history: CameraHistory, client, model: str = DEFAULT_MODEL, interval_s: float = 30.0,
                 min_gap_s: float = 10.0, clock: Callable[[], float] = time.time, check_every_s: float = 2.0):
        super().__init__(daemon=True, name="scene-log")
        self.history, self.client, self.model = history, client, model
        self.interval_s, self.min_gap_s, self.check_every_s = interval_s, min_gap_s, check_every_s
        self._clock = clock
        self._stop_event = threading.Event()
        self._last: Dict[str, Dict[str, Any]] = {}   # camera -> {ts, people, warnings}
        self._warned = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.check_every_s):
            for camera_id in self.history.camera_ids():
                self.tick(camera_id)

    def tick(self, camera_id: str) -> bool:
        """Writes one note for the camera if due. Returns True if a note was added."""
        now = self._clock()
        frame, frame_ts = self.history.latest_frame(camera_id)
        ev = self.history.latest_event(camera_id)
        last = self._last.get(camera_id, {})
        warnings = {i.message for i in (ev.insights if ev else []) if i.level == "warn"}
        if not should_note(now, last.get("ts"), last.get("people"), ev.people if ev else None,
                           bool(warnings - last.get("warnings", set())), None if frame_ts is None else now - frame_ts,
                           self.interval_s, self.min_gap_s) or not frame:
            return False
        content = [_image_block(frame),
                   {"type": "text", "text": "Metrics for this frame: " + latest_summary(ev) + "\nWrite the log note."}]
        try:
            text = _call(self.client, self.model, SCENE_SYSTEM, [{"role": "user", "content": content}], 300)
        except ChatError as e:
            if not self._warned:
                log.warning("scene log paused for %s: %s", camera_id, e.message)
                self._warned = True
            self._last[camera_id] = {**last, "ts": now}   # back off until the next interval
            return False
        self._warned = False
        if text:
            self.history.add_note(camera_id, text, ts=now)
        self._last[camera_id] = {"ts": now, "people": ev.people if ev else None, "warnings": warnings}
        return bool(text)
