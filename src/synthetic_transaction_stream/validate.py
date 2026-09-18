"""Validate generated files and summarize their behaviour."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def validate_output(output_dir: Path) -> dict:
    users = read_csv(output_dir / "users.csv")
    partners = read_csv(output_dir / "partners.csv")
    merchants = read_csv(output_dir / "merchants.csv")
    transactions = read_csv(output_dir / "transactions.csv")
    labels = read_csv(output_dir / "scenario_labels.csv")
    with (output_dir / "transaction_events.ndjson").open(encoding="utf-8") as file:
        events = [json.loads(line) for line in file if line.strip()]

    user_ids = {row["user_id"] for row in users}
    partner_ids = {row["partner_id"] for row in partners}
    merchant_ids = {row["merchant_id"] for row in merchants}
    transaction_ids = {row["transaction_id"] for row in transactions}
    assert len(user_ids) == len(users), "duplicate user ID"
    assert len(partner_ids) == len(partners), "duplicate partner ID"
    assert len(merchant_ids) == len(merchants), "duplicate merchant ID"
    assert len(transaction_ids) == len(transactions), "duplicate transaction ID"
    assert all(row["partner_id"] in partner_ids for row in merchants), "orphan merchant"
    assert all(row["user_id"] in user_ids and row["merchant_id"] in merchant_ids
               for row in transactions), "orphan transaction"
    assert all(row["transaction_id"] in transaction_ids for row in labels), "orphan label"

    latest: dict[str, dict] = {}
    event_ids = set()
    previous_time = ""
    transitions = {
        None: {"pending"},
        "pending": {"approved", "declined"},
        "approved": {"refunded"},
    }
    for expected_sequence, event in enumerate(events, start=1):
        assert event["sequence_no"] == expected_sequence, "event sequence gap"
        assert event["event_id"] not in event_ids, "duplicate event ID"
        event_ids.add(event["event_id"])
        assert event["emitted_at"] >= previous_time, "events out of order"
        previous_time = event["emitted_at"]
        tx = event["transaction"]
        tx_id = tx["transaction_id"]
        assert tx_id in transaction_ids, "orphan event"
        old = latest.get(tx_id)
        assert tx["status"] in transitions.get(old["status"] if old else None, set()), \
            "invalid status transition"
        assert tx["status_version"] == (old["status_version"] + 1 if old else 1), \
            "invalid status version"
        assert event["emitted_at"] == tx["status_updated_at"], "event time mismatch"
        expected_type = "transaction.created" if old is None else "transaction.status_changed"
        assert event["event_type"] == expected_type, "event type mismatch"
        latest[tx_id] = tx
    assert len(latest) == len(transactions), "transaction missing from event log"
    for row in transactions:
        tx = latest[row["transaction_id"]]
        assert all(str(tx[field]) == value for field, value in row.items()), \
            "snapshot differs from latest event"
        assert int(row["amount_minor"]) > 0, "nonpositive amount"

    hours = Counter(datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).hour
                    for row in transactions)
    statuses = Counter(row["status"] for row in transactions)
    by_day = defaultdict(int)
    for row in transactions:
        by_day[row["created_at"][:10]] += 1
    return {
        "users": len(users),
        "partners": len(partners),
        "merchants": len(merchants),
        "transactions": len(transactions),
        "events": len(events),
        "scenario_transactions": len(labels),
        "status_counts": dict(sorted(statuses.items())),
        "hourly_counts_utc": {f"{hour:02d}": hours[hour] for hour in range(24)},
        "daily_counts": dict(sorted(by_day.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated transaction files")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_output(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
