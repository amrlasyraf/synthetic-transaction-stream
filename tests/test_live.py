import tempfile
import threading
import time
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from synthetic_transaction_stream.generator import Config, Generator
from synthetic_transaction_stream.live import EventStore, LiveProducer, StreamServer


def event() -> dict:
    return {"event_id": str(uuid.uuid4()), "event_type": "transaction.created",
            "emitted_at": "2026-01-01T00:00:00Z", "transaction": {"status": "pending"}}


def next_sequence(response) -> int:
    while True:
        line = response.readline().decode("utf-8").strip()
        if line.startswith("id: "):
            return int(line[4:])


class LiveTests(unittest.TestCase):
    def test_shared_sequence_and_reconnect(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EventStore(Path(temp) / "events.sqlite")
            stop = threading.Event()
            reference = type("Reference", (), {"users": [], "merchants": [], "partners": []})()
            server = StreamServer(("127.0.0.1", 0), store, reference, stop)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/", timeout=5) as home:
                    self.assertEqual(home.status, 200)
                    self.assertIn(b"Synthetic transaction stream", home.read())
                with urlopen(base + "/v1/transactions/stream?after=0", timeout=5) as a, \
                     urlopen(base + "/v1/transactions/stream?after=0", timeout=5) as b:
                    store.publish(event())
                    self.assertEqual(next_sequence(a), 1)
                    self.assertEqual(next_sequence(b), 1)
                    store.publish(event())
                    store.publish(event())
                    self.assertEqual(next_sequence(b), 2)
                    self.assertEqual(next_sequence(b), 3)
                with urlopen(base + "/v1/transactions/stream?after=1", timeout=5) as a_again:
                    self.assertEqual(next_sequence(a_again), 2)
                    self.assertEqual(next_sequence(a_again), 3)
                store.prune(time.time() + 8 * 86400)
                try:
                    urlopen(base + "/v1/transactions/events?after=1", timeout=5)
                except Exception as error:
                    self.assertEqual(error.code, 410)
                else:
                    self.fail("expired cursor should return 410")
            finally:
                stop.set()
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                store.close()

    def test_pending_status_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.sqlite"
            store = EventStore(path)
            pending = event()
            store.publish(event(), [(time.time() - 1, pending)])
            store.close()
            reopened = EventStore(path)
            try:
                self.assertEqual(reopened.publish_due(time.time()), 1)
                self.assertEqual([row["sequence_no"] for row in reopened.after(0)], [1, 2])
            finally:
                reopened.close()

    def test_live_producer_writes_without_a_client(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EventStore(Path(temp) / "events.sqlite")
            reference = Generator(Config(start_date=date(2026, 1, 1)))
            producer = LiveProducer(store, reference, 6000, threading.Event())
            try:
                when = datetime.now(timezone.utc)
                producer.create_transaction(when, reference.users[3], reference.merchants[0])
                created = store.after(0)
                self.assertEqual(len(created), 1)
                self.assertEqual(created[0]["transaction"]["status"], "pending")
                self.assertEqual(store.publish_due(time.time() + 91), 1)
                updated = store.after(1)
                self.assertEqual(updated[0]["transaction"]["status_version"], 2)
                self.assertIn(updated[0]["transaction"]["status"], ("approved", "declined"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
