"""Event output: JSON lines on disk, plus an optional webhook with a local SQLite outbox.

If the network drops, events queue in the outbox and are delivered (oldest first) when it returns.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.request
from typing import Optional

from .schema import Event

MAX_OUTBOX = 5000


class EventSink:
    def __init__(self, jsonl_path: Optional[str] = None, webhook: Optional[str] = None,
                 outbox_db: str = "outbox.sqlite"):
        self._lock = threading.Lock()
        self._f = open(jsonl_path, "a", buffering=1) if jsonl_path else None
        self.webhook = webhook
        self._stop = False
        self._thread = None
        if webhook:
            self._db = sqlite3.connect(outbox_db, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)")
            self._db.commit()
            self._thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._thread.start()

    def emit(self, ev: Event) -> None:
        line = ev.model_dump_json()
        with self._lock:
            if self._f:
                self._f.write(line + "\n")
            if self.webhook:
                self._db.execute("INSERT INTO outbox(payload) VALUES (?)", (line,))
                self._db.execute(
                    "DELETE FROM outbox WHERE id <= (SELECT MAX(id) FROM outbox) - ?", (MAX_OUTBOX,))
                self._db.commit()

    def _post(self, payload: str) -> bool:
        req = urllib.request.Request(self.webhook, data=payload.encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return 200 <= r.status < 300
        except Exception:
            return False

    def _flush_loop(self) -> None:
        backoff = 1.0
        while not self._stop:
            with self._lock:
                row = self._db.execute("SELECT id, payload FROM outbox ORDER BY id LIMIT 1").fetchone()
            if row is None:
                time.sleep(0.3)
                continue
            if self._post(row[1]):
                with self._lock:
                    self._db.execute("DELETE FROM outbox WHERE id=?", (row[0],))
                    self._db.commit()
                backoff = 1.0
            else:
                time.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    def pending(self) -> int:
        if not self.webhook:
            return 0
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def close(self, drain_s: float = 3.0) -> None:
        t0 = time.time()
        while self.webhook and self.pending() and time.time() - t0 < drain_s:
            time.sleep(0.1)
        self._stop = True
        if self._f:
            self._f.close()
