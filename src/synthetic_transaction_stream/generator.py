"""Deterministic, entirely fictional transaction data generation."""

from __future__ import annotations

import csv
import json
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


NAMESPACE = uuid.UUID("3b397662-85ba-4b67-9581-d11521c5d3d8")
UTC = timezone.utc
CATEGORIES = {
    "dining": (700, 6500),
    "grocery": (1200, 16000),
    "transit": (200, 3000),
    "retail": (1500, 26000),
    "digital": (400, 12000),
}
FIRST = ("Amber", "Blue", "Copper", "Golden", "Indigo", "Silver", "Velvet")
LAST = ("Finch", "Kite", "Otter", "Pine", "Quartz", "Robin", "Willow")
USER_FIELDS = ("user_id", "display_name", "home_zone", "created_at")
PARTNER_FIELDS = ("partner_id", "display_name", "created_at")
MERCHANT_FIELDS = (
    "merchant_id", "partner_id", "display_name", "category", "zone_code", "created_at"
)
TRANSACTION_FIELDS = (
    "transaction_id", "user_id", "merchant_id", "amount_minor", "currency",
    "channel", "status", "status_version", "created_at", "status_updated_at"
)
LABEL_FIELDS = ("scenario_id", "transaction_id", "scenario_type", "persona_id")


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Config:
    seed: int = 42
    start_date: date = date(2026, 1, 1)
    days: int = 30
    users: int = 250
    merchants: int = 40
    partners: int = 5
    transactions_per_day: int = 200
    anomalies: bool = True

    def validate(self) -> None:
        if not 1 <= self.days <= 366:
            raise ValueError("days must be between 1 and 366")
        if self.users < 3 or self.merchants < 5 or self.partners < 1:
            raise ValueError("need at least 3 users, 5 merchants, and 1 partner")
        if not 1 <= self.transactions_per_day <= 10_000:
            raise ValueError("transactions-per-day must be between 1 and 10000")


class Generator:
    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self.rng = random.Random(config.seed)
        self.users: list[dict] = []
        self.partners: list[dict] = []
        self.merchants: list[dict] = []
        self.transactions: dict[str, dict] = {}
        self.events: list[dict] = []
        self.labels: list[dict] = []
        self._make_reference_data()

    def _id(self, kind: str, key: str) -> str:
        return str(uuid.uuid5(NAMESPACE, f"{self.config.seed}:{kind}:{key}"))

    def _make_reference_data(self) -> None:
        before = iso(datetime.combine(self.config.start_date, time.min, UTC) - timedelta(days=30))
        for i in range(self.config.partners):
            self.partners.append({
                "partner_id": self._id("partner", str(i)),
                "display_name": f"Demo Partner {i + 1:02d}",
                "created_at": before,
            })
        for i in range(self.config.merchants):
            category = list(CATEGORIES)[i % len(CATEGORIES)]
            self.merchants.append({
                "merchant_id": self._id("merchant", str(i)),
                "partner_id": self.partners[i % len(self.partners)]["partner_id"],
                "display_name": f"Demo {category.title()} {i + 1:03d}",
                "category": category,
                "zone_code": f"zone_{i % 6 + 1:02d}",
                "created_at": before,
            })
        for i in range(self.config.users):
            name = f"{FIRST[i % len(FIRST)]} {LAST[(i // len(FIRST)) % len(LAST)]}"
            if i == 0:
                name = "Copper Kite"
            elif i == 1:
                name = "copper-kite"
            elif i == 2:
                name = "C. Kite"
            self.users.append({
                "user_id": self._id("user", str(i)),
                "display_name": name,
                "home_zone": f"zone_{i % 6 + 1:02d}",
                "created_at": before,
            })

    def _hour_weights(self, weekend: bool) -> list[float]:
        if weekend:
            return [0.12] * 7 + [0.4, 0.7, 1.2, 1.8, 2.0, 2.1, 2.0,
                    1.8, 1.8, 2.0, 2.3, 2.5, 2.1, 1.5, 0.9, 0.5, 0.25]
        return [0.10] * 6 + [0.5, 1.5, 1.8, 1.1, 0.9, 1.4, 2.3, 2.0,
                1.1, 0.9, 1.3, 2.0, 2.8, 2.5, 1.6, 0.9, 0.5, 0.25]

    def _merchant(self, hour: int) -> dict:
        weights = []
        for merchant in self.merchants:
            category = merchant["category"]
            weight = 1.0
            if category == "dining" and hour in (11, 12, 13, 18, 19, 20):
                weight = 3.5
            elif category == "transit" and hour in (7, 8, 17, 18):
                weight = 3.0
            elif category == "grocery" and 16 <= hour <= 20:
                weight = 2.0
            weights.append(weight)
        return self.rng.choices(self.merchants, weights=weights, k=1)[0]

    def _add_transaction(self, when: datetime, user: dict, merchant: dict,
                         anomaly: bool = False, scenario_id: str = "") -> None:
        tx_id = self._id("transaction", f"{iso(when)}:{len(self.transactions)}")
        low, high = CATEGORIES[merchant["category"]]
        amount = self.rng.randint(low, high)
        if anomaly:
            amount *= self.rng.randint(4, 8)
        channel = "web" if merchant["category"] == "digital" else self.rng.choice(
            ("mobile", "in_store", "in_store")
        )
        tx = {
            "transaction_id": tx_id,
            "user_id": user["user_id"],
            "merchant_id": merchant["merchant_id"],
            "amount_minor": amount,
            "currency": "USD",
            "channel": channel,
            "status": "pending",
            "status_version": 1,
            "created_at": iso(when),
            "status_updated_at": iso(when),
        }
        self._add_event(when, "transaction.created", tx)
        update_time = when + timedelta(seconds=self.rng.randint(1, 90))
        approved = self.rng.random() >= (0.12 if anomaly else 0.035)
        tx = {**tx, "status": "approved" if approved else "declined",
              "status_version": 2, "status_updated_at": iso(update_time)}
        self._add_event(update_time, "transaction.status_changed", tx)
        if approved and not anomaly and self.rng.random() < 0.015:
            refund_time = update_time + timedelta(hours=self.rng.randint(1, 168))
            horizon = datetime.combine(
                self.config.start_date + timedelta(days=self.config.days), time.min, UTC
            )
            if refund_time < horizon:
                tx = {**tx, "status": "refunded", "status_version": 3,
                      "status_updated_at": iso(refund_time)}
                self._add_event(refund_time, "transaction.status_changed", tx)
        self.transactions[tx_id] = tx
        if anomaly:
            self.labels.append({
                "scenario_id": scenario_id,
                "transaction_id": tx_id,
                "scenario_type": "alias_velocity_burst",
                "persona_id": "fictional_persona_01",
            })

    def _add_event(self, when: datetime, event_type: str, tx: dict) -> None:
        self.events.append({
            "event_id": self._id("event", f"{tx['transaction_id']}:{tx['status_version']}"),
            "event_type": event_type,
            "emitted_at": iso(when),
            "transaction": tx.copy(),
        })

    def generate(self) -> "Generator":
        next_burst_day = self.rng.randint(3, 6)
        for day_index in range(self.config.days):
            day = self.config.start_date + timedelta(days=day_index)
            weekend = day.weekday() >= 5
            count = max(1, round(self.config.transactions_per_day
                                 * (0.75 if weekend else 1.0)
                                 * self.rng.uniform(0.88, 1.12)))
            hour_weights = self._hour_weights(weekend)
            times = []
            for _ in range(count):
                hour = self.rng.choices(range(24), weights=hour_weights, k=1)[0]
                seconds = self.rng.randrange(3600)
                times.append(datetime.combine(day, time(hour), UTC) + timedelta(seconds=seconds))
            for when in sorted(times):
                user = self.rng.choice(self.users[3:] if self.config.anomalies else self.users)
                self._add_transaction(when, user, self._merchant(when.hour))
            if self.config.anomalies and day_index == next_burst_day:
                base = datetime.combine(
                    day, time(self.rng.randint(1, 4), self.rng.randrange(60)), UTC
                )
                scenario_id = f"burst_{day.isoformat()}"
                for j in range(self.rng.randint(5, 9)):
                    user = self.users[j % 3]
                    merchant = self.merchants[(j * 7 + day_index) % len(self.merchants)]
                    self._add_transaction(base + timedelta(seconds=j * 38), user, merchant,
                                          anomaly=True, scenario_id=scenario_id)
                next_burst_day += self.rng.randint(5, 10)
        self.events.sort(key=lambda event: (event["emitted_at"], event["event_id"]))
        for sequence, event in enumerate(self.events, start=1):
            event["sequence_no"] = sequence
        return self

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        tables = (
            ("users.csv", USER_FIELDS, self.users),
            ("partners.csv", PARTNER_FIELDS, self.partners),
            ("merchants.csv", MERCHANT_FIELDS, self.merchants),
            ("transactions.csv", TRANSACTION_FIELDS, self.transactions.values()),
            ("scenario_labels.csv", LABEL_FIELDS, self.labels),
        )
        for filename, fields, rows in tables:
            with (output_dir / filename).open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        with (output_dir / "transaction_events.ndjson").open("w", encoding="utf-8") as file:
            for event in self.events:
                file.write(json.dumps(event, separators=(",", ":")) + "\n")
        manifest = {
            "synthetic": True,
            "seed": self.config.seed,
            "start_date": self.config.start_date.isoformat(),
            "days": self.config.days,
            "transaction_count": len(self.transactions),
            "event_count": len(self.events),
            "anomaly_transaction_count": len(self.labels),
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
