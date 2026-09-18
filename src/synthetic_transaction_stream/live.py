"""Shared live producer with a seven-day replay log and HTTP event stream."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .generator import CATEGORIES, Config, Generator, iso


class EventStore:
    def __init__(self, path: Path, retention_days: int = 7):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS event_log (
                sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                published_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_events (
                event_id TEXT PRIMARY KEY,
                due_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenario_labels (
                scenario_id TEXT NOT NULL,
                transaction_id TEXT NOT NULL,
                scenario_type TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS pending_due_idx ON pending_events(due_at);
            CREATE INDEX IF NOT EXISTS event_published_idx ON event_log(published_at);
        """)
        self.db.commit()
        self.lock = threading.RLock()
        self.retention_days = retention_days
        self.retention_seconds = retention_days * 86400

    def _insert_event(self, event: dict, published_at: float) -> int:
        cursor = self.db.execute(
            "INSERT INTO event_log(event_id, published_at, payload) VALUES (?, ?, ?)",
            (event["event_id"], published_at, "{}"),
        )
        sequence = cursor.lastrowid
        event = {**event, "sequence_no": sequence}
        self.db.execute(
            "UPDATE event_log SET payload = ? WHERE sequence_no = ?",
            (json.dumps(event, separators=(",", ":")), sequence),
        )
        return sequence

    def publish(self, event: dict, scheduled: list[tuple[float, dict]] | None = None,
                label: tuple[str, str] | None = None) -> int:
        with self.lock, self.db:
            sequence = self._insert_event(event, time.time())
            for due_at, pending in scheduled or []:
                self.db.execute(
                    "INSERT INTO pending_events(event_id, due_at, payload) VALUES (?, ?, ?)",
                    (pending["event_id"], due_at, json.dumps(pending, separators=(",", ":"))),
                )
            if label:
                self.db.execute(
                    "INSERT INTO scenario_labels VALUES (?, ?, ?)",
                    (label[0], label[1], "alias_velocity_burst"),
                )
            return sequence

    def publish_due(self, now: float) -> int:
        with self.lock, self.db:
            due = self.db.execute(
                "SELECT event_id, payload FROM pending_events WHERE due_at <= ? "
                "ORDER BY due_at, event_id", (now,),
            ).fetchall()
            for event_id, payload in due:
                self._insert_event(json.loads(payload), now)
                self.db.execute("DELETE FROM pending_events WHERE event_id = ?", (event_id,))
            return len(due)

    def bounds(self) -> tuple[int, int]:
        with self.lock:
            row = self.db.execute("SELECT MIN(sequence_no), MAX(sequence_no) FROM event_log").fetchone()
            if row[0] is not None:
                return row[0], row[1]
            last = self.db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = 'event_log'"
            ).fetchone()
            latest = last[0] if last else 0
            return latest + 1, latest

    def after(self, sequence: int, limit: int = 100) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM event_log WHERE sequence_no > ? "
                "ORDER BY sequence_no LIMIT ?", (sequence, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def prune(self, now: float) -> int:
        with self.lock, self.db:
            cursor = self.db.execute(
                "DELETE FROM event_log WHERE published_at < ?",
                (now - self.retention_seconds,),
            )
            return cursor.rowcount

    def close(self) -> None:
        with self.lock:
            self.db.close()


class LiveProducer(threading.Thread):
    def __init__(self, store: EventStore, reference: Generator, per_day: int,
                 stop: threading.Event):
        super().__init__(daemon=True, name="transaction-producer")
        self.store = store
        self.reference = reference
        self.per_day = per_day
        self.stop = stop
        self.rng = random.Random()
        self.next_burst = time.time() + self.rng.randint(3600, 21600)

    def _event(self, kind: str, when: datetime, tx: dict) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": kind,
            "emitted_at": iso(when),
            "transaction": tx.copy(),
        }

    def create_transaction(self, when: datetime, user: dict, merchant: dict,
                           scenario_id: str | None = None) -> str:
        tx_id = str(uuid.uuid4())
        low, high = CATEGORIES[merchant["category"]]
        amount = self.rng.randint(low, high)
        if scenario_id:
            amount *= self.rng.randint(4, 8)
        tx = {
            "transaction_id": tx_id,
            "user_id": user["user_id"],
            "merchant_id": merchant["merchant_id"],
            "amount_minor": amount,
            "currency": "USD",
            "channel": "web" if merchant["category"] == "digital" else
                       self.rng.choice(("mobile", "in_store", "in_store")),
            "status": "pending",
            "status_version": 1,
            "created_at": iso(when),
            "status_updated_at": iso(when),
        }
        created = self._event("transaction.created", when, tx)
        decision_time = when + timedelta(seconds=self.rng.randint(1, 90))
        approved = self.rng.random() >= (0.12 if scenario_id else 0.035)
        decision = {**tx, "status": "approved" if approved else "declined",
                    "status_version": 2, "status_updated_at": iso(decision_time)}
        scheduled = [(decision_time.timestamp(), self._event(
            "transaction.status_changed", decision_time, decision
        ))]
        if approved and not scenario_id and self.rng.random() < 0.015:
            refund_time = decision_time + timedelta(hours=self.rng.randint(1, 168))
            refunded = {**decision, "status": "refunded", "status_version": 3,
                        "status_updated_at": iso(refund_time)}
            scheduled.append((refund_time.timestamp(), self._event(
                "transaction.status_changed", refund_time, refunded
            )))
        label = (scenario_id, tx_id) if scenario_id else None
        self.store.publish(created, scheduled, label)
        return tx_id

    def inject_burst(self, when: datetime) -> None:
        scenario_id = f"burst_{uuid.uuid4().hex[:12]}"
        for index in range(self.rng.randint(5, 9)):
            merchant = self.rng.choice(self.reference.merchants)
            user = self.reference.users[index % 3]
            self.create_transaction(when, user, merchant, scenario_id)

    def run(self) -> None:
        last_prune = 0.0
        while not self.stop.is_set():
            now = time.time()
            self.store.publish_due(now)
            when = datetime.fromtimestamp(now, timezone.utc)
            weights = self.reference._hour_weights(when.weekday() >= 5)
            weekend_factor = 0.75 if when.weekday() >= 5 else 1.0
            per_second = self.per_day * weekend_factor * weights[when.hour] / sum(weights) / 3600
            if self.rng.random() < per_second:
                user = self.rng.choice(self.reference.users[3:])
                merchant = self.reference._merchant(when.hour)
                self.create_transaction(when, user, merchant)
            if now >= self.next_burst:
                self.inject_burst(when)
                self.next_burst = now + self.rng.randint(5, 10) * 86400
            if now - last_prune >= 60:
                self.store.prune(now)
                last_prune = now
            self.stop.wait(1)


class StreamServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: EventStore,
                 reference: Generator, stop: threading.Event):
        self.store = store
        self.reference = reference
        self.stop = stop
        self.stream_slots = threading.BoundedSemaphore(40)
        super().__init__(address, StreamHandler)


class StreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: StreamServer

    def _json(self, status: int, body: object) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _cursor(self, query: dict) -> int | None:
        raw = self.headers.get("Last-Event-ID") or query.get("after", [None])[0]
        if raw is None:
            return None
        value = int(raw)
        if value < 0:
            raise ValueError("cursor must be nonnegative")
        return value

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/health":
            oldest, latest = self.server.store.bounds()
            self._json(200, {"status": "ok", "oldest_sequence": oldest,
                             "latest_sequence": latest,
                             "retention_days": self.server.store.retention_days})
            return
        references = {
            "/v1/users": self.server.reference.users,
            "/v1/partners": self.server.reference.partners,
            "/v1/merchants": self.server.reference.merchants,
        }
        if url.path in references:
            self._json(200, references[url.path])
            return
        if url.path not in ("/v1/transactions/events", "/v1/transactions/stream"):
            self._json(404, {"error": "not_found"})
            return
        try:
            after = self._cursor(query)
        except ValueError:
            self._json(400, {"error": "invalid_cursor"})
            return
        oldest, latest = self.server.store.bounds()
        if after is None:
            after = latest if url.path.endswith("/stream") else max(0, oldest - 1)
        if after < oldest - 1:
            self._json(410, {"error": "replay_window_expired",
                             "oldest_sequence": oldest, "latest_sequence": latest})
            return
        if url.path.endswith("/events"):
            try:
                limit = min(1000, max(1, int(query.get("limit", [100])[0])))
            except ValueError:
                self._json(400, {"error": "invalid_limit"})
                return
            self._json(200, self.server.store.after(after, limit))
            return
        if not self.server.stream_slots.acquire(blocking=False):
            self._json(503, {"error": "too_many_streams"})
            return
        try:
            self._stream(after)
        finally:
            self.server.stream_slots.release()

    def _stream(self, after: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        heartbeat_at = time.monotonic()
        try:
            while not self.server.stop.is_set():
                oldest, latest = self.server.store.bounds()
                if after < oldest - 1:
                    message = json.dumps({"oldest_sequence": oldest,
                                          "latest_sequence": latest})
                    self.wfile.write(f"event: gap\ndata: {message}\n\n".encode())
                    self.wfile.flush()
                    return
                events = self.server.store.after(after)
                for event in events:
                    self.wfile.write(
                        f"id: {event['sequence_no']}\nevent: transaction\n"
                        f"data: {json.dumps(event, separators=(',', ':'))}\n\n".encode()
                    )
                    after = event["sequence_no"]
                if events:
                    self.wfile.flush()
                    heartbeat_at = time.monotonic()
                    continue
                if time.monotonic() - heartbeat_at >= 15:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    heartbeat_at = time.monotonic()
                self.server.stop.wait(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shared live transaction producer")
    parser.add_argument("--db", type=Path, default=Path("data/events.sqlite"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--transactions-per-day", type=int, default=6000)
    args = parser.parse_args()
    if not 1 <= args.transactions_per_day <= 20_000:
        parser.error("transactions-per-day must be between 1 and 20000")
    reference = Generator(Config(seed=args.seed, start_date=date(2026, 1, 1)))
    store = EventStore(args.db)
    store.prune(time.time())
    stop = threading.Event()
    producer = LiveProducer(store, reference, args.transactions_per_day, stop)
    server = StreamServer((args.host, args.port), store, reference, stop)
    producer.start()
    print(f"Serving http://{args.host}:{args.port} with a seven-day replay window", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        producer.join(timeout=3)
        store.close()


if __name__ == "__main__":
    main()
