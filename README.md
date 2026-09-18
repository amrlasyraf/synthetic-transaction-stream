# Synthetic Transaction Stream

An open source producer of **entirely synthetic** retail transaction data. It creates four related tables and a chronological event file suitable for learning ingestion, joins, streaming, and anomaly detection. The scenarios, identities, merchants, and partners are fictional and were created for this project.

The generator creates reproducible local files. A separate live service now produces a shared stream locally; public hosting and a Kafka adapter remain planned.

For an always-running container and VPS plan, see [`docs/deployment.md`](docs/deployment.md).

## Generate data

Requires Python 3.10 or newer. The generator has no runtime dependencies.

```sh
python -m pip install -e .
synthetic-transactions --output output --start-date 2026-01-01 --days 30 --seed 42
```

Or without installing the package:

```sh
PYTHONPATH=src python -m synthetic_transaction_stream --output output
```

PowerShell equivalent for the second command:

```powershell
$env:PYTHONPATH = 'src'
python -m synthetic_transaction_stream --output output
```

Use `--transactions-per-day`, `--users`, `--merchants`, and `--partners` to change the scale. `--no-anomalies` removes the scripted anomaly bursts. A fixed seed and settings reproduce the same files.

Validate the files and print status, daily, and hourly counts:

```sh
python -m synthetic_transaction_stream.validate output
```

## Files

| File | Contents |
| --- | --- |
| `users.csv` | Fictional user identifiers, pseudonyms, and home zones |
| `partners.csv` | Fictional partner reference data |
| `merchants.csv` | Merchants linked to partners, with category and zone |
| `transactions.csv` | Final transaction state after all generated events |
| `transaction_events.ndjson` | Chronological creation and status-change events |
| `scenario_labels.csv` | Separate answer key for injected anomaly transactions |
| `manifest.json` | Seed, time range, and row counts |

`scenario_labels.csv` is intentionally separate from the event stream. Do not give it to a learner before an exercise if they should detect the scenarios themselves.

## Shared live stream

Start one producer and HTTP server locally:

```sh
python -m synthetic_transaction_stream.live --db data/events.sqlite --port 8080
```

Open `http://127.0.0.1:8080/` in a browser for a small live viewer and endpoint links. In another terminal, inspect the raw stream with `curl -N http://127.0.0.1:8080/v1/transactions/stream` (`curl.exe -N` in PowerShell). Check `http://127.0.0.1:8080/health` for the current sequence range. The stream begins at the current tip, so leave it open for new events or supply `?after=0` to read retained events from the start.

The process produces transactions independently of listeners. It writes events to a SQLite log and keeps seven days of published events. Pending status changes also survive a restart. The rate varies by hour and weekday; `--transactions-per-day` sets the approximate weekday volume (default 6000). The live database stays in `data/`, which Git ignores.

The live reference tables are fixed at startup in this version: 250 users, 40 merchants, and 5 partners by default. Transactions continue to grow. Later, new reference records should appear in the stream before any transaction refers to them.

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Current sequence range and retention |
| `GET /v1/users`, `/v1/merchants`, `/v1/partners` | Reference snapshots |
| `GET /v1/transactions/events?after=0&limit=100` | Bounded JSON replay |
| `GET /v1/transactions/stream` | SSE live stream |

The SSE stream starts at the current tip when no cursor is supplied. To catch up, connect with `?after=<last_sequence_no>` or the SSE `Last-Event-ID` header. A cursor older than the retained log receives HTTP `410` with the available sequence range. A connected stream sends a `gap` event and closes if it falls behind retention. Every listener sees the same global sequence; listeners only differ in how far they have read.

For example, if a client receives sequence 10 and disconnects, it can reconnect to `/v1/transactions/stream?after=10` to receive 11 onward. This is a one-way stream, so clients keep a connection open rather than polling once per second.

## Data model

The SQL types and constraints are in [`schema.sql`](schema.sql). IDs are UUIDs. Timestamps are UTC ISO 8601 in generated files and `TIMESTAMPTZ` in SQL. `amount_minor` is a positive integer in currency minor units; the first version uses USD only. The transaction status is `pending`, `approved`, `declined`, or `refunded`. A full refund changes the original transaction's status and leaves its original amount intact. Partial refunds are outside the first version.

`transaction_events.ndjson` has one JSON object per line. Each event has a unique `event_id`, increasing `sequence_no`, `event_type`, `emitted_at`, and a full `transaction` snapshot. A transaction starts at `status_version: 1`; later status changes increase the version. Consumers can upsert by `transaction_id` and apply only newer versions.

Example event:

```json
{"event_id":"...","event_type":"transaction.created","emitted_at":"2026-01-01T08:30:00Z","transaction":{"transaction_id":"...","user_id":"...","merchant_id":"...","amount_minor":1250,"currency":"USD","channel":"in_store","status":"pending","status_version":1,"created_at":"2026-01-01T08:30:00Z","status_updated_at":"2026-01-01T08:30:00Z"},"sequence_no":1}
```

## Behaviour

Transactions follow weekday and weekend hourly profiles. Dining is more common around lunch and dinner, transit around commute times, and grocery purchases in the evening. Amount ranges vary by merchant category. A small share of transactions decline; a smaller share of approved transactions become fully refunded.

Occasionally, a fictional persona uses three separate accounts with styled versions of one pseudonym and makes a rapid burst of unusually large transactions. The labels identify the scripted scenario for evaluation. Similar display names alone should not be treated as evidence of fraud.

## Roadmap

1. Validate generated month-long patterns and the event contract.
2. Validate the shared live service under longer runs and disconnections.
3. Add gradual reference-table growth with creation events.
4. Host the HTTP stream and reference snapshots publicly.
5. Add a local Kafka adapter and optional database sink examples.

No real financial data, personal data, payment credentials, or proprietary business rules belong in this repository.
