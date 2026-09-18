# Tencent Lighthouse deployment plan

This is a preparation checklist. Nothing in this repository purchases or creates a cloud server. The current Python producer and SQLite replay log can run on one Lighthouse Linux instance using the repository's Docker Compose setup.

## Proposed first instance

- Region: Singapore, for a nearby public endpoint.
- Bundle: Lighthouse Linux Starter, 2 vCPU, 2 GB RAM, 40 GB SSD, 20 Mbps, 0.5 TB monthly outbound transfer.
- Term: the one-year first-purchase offer shown in the Tencent checkout screenshot on 18 September 2026 was US$10.08 paid upfront. The crossed-out regular annual price was US$50.40. These are a planning snapshot, not a guaranteed future checkout or renewal price.
- Before any payment, confirm the selected region, Linux image, total due today, traffic allowance, tax, renewal price, and whether auto-renewal is enabled. Use the final checkout amount as the source of truth.

The 2 GB bundle is for the initial Python producer, SQLite log, and Caddy proxy. It is not sized to run a Kafka broker or Databricks on the same machine. The project's public HTTP/SSE stream can later feed those systems elsewhere.

## Prepare before purchase

1. Choose a public hostname. An existing domain can be used; buying a new one is not required for local validation.
2. Keep this repository and its `codex/initial-generator` branch available on GitHub.
3. Decide who can access SSH and which source IPs to allow. Plan to expose only TCP 80 and 443 to the public internet. Compose binds application port 8080 to the server's loopback interface.
4. Decide where to keep off-server SQLite backups. The Docker volume persists across container recreation, but it is still stored on the same server.

## Once a server exists

These commands are for an Ubuntu or Debian Linux instance. Install Docker Engine and the Compose plugin using the [official Docker instructions](https://docs.docker.com/engine/install/ubuntu/) for the selected operating system. Install Git and verify `docker compose version`. Select a Linux system image, use SSH key login, and configure the Lighthouse firewall for SSH from your own IP plus public TCP 80 and 443.

Clone the prepared branch:

```sh
git clone --branch codex/initial-generator https://github.com/amrlasyraf/synthetic-transaction-stream.git
cd synthetic-transaction-stream
```

Start privately first, without DNS or a domain:

```sh
docker compose up -d --build stream
docker compose ps
curl -fsS http://127.0.0.1:8080/health
```

From your computer, `ssh -L 8080:127.0.0.1:8080 USER@SERVER_IP` makes the viewer available at `http://127.0.0.1:8080/` while the tunnel is open. Replace `USER` with the image's SSH user. Do not open port 8080 in the Lighthouse firewall.

When a hostname resolves to the server, copy `.env.example` to `.env` and replace `stream.example.com` with that hostname. `.env` is ignored by Git. Then start HTTPS:

```sh
docker compose --profile public up -d --build
docker compose ps
curl -fsS https://YOUR_HOSTNAME/health
```

Caddy needs inbound TCP 80 and 443 to obtain and renew its HTTPS certificate. `YOUR_HOSTNAME` is the name entered in `.env`.

## Acceptance checks

1. Open `/` and `/health`. Confirm the health response contains the current sequence range and seven-day retention.
2. Leave `/v1/transactions/stream` open in two clients. Both should receive the same sequence numbers and event values.
3. Disconnect one client and reconnect with `?after=<last_sequence_no>`. It should receive the missed retained events.
4. Check `/v1/transactions/events?after=0&limit=5` for bounded JSON replay and `/v1/users`, `/v1/merchants`, `/v1/partners` for reference snapshots.
5. Restart with `docker compose restart stream`, then verify that `/health` retains its sequence range and new events resume. Production stops during server downtime; it does not backfill that interval.
6. Check server disk use and monthly outbound transfer. The plan includes 0.5 TB of outbound transfer; exceeding it can add charges.

## Backup and updates

SQLite uses WAL mode, so do not copy the live database file directly. On the server, use SQLite's online backup API and then copy the resulting file out of the container:

```sh
mkdir -p backups
docker compose exec -T stream python -c 'import sqlite3; source = sqlite3.connect("file:/data/events.sqlite?mode=ro", uri=True); target = sqlite3.connect("/data/events-backup.sqlite"); source.backup(target); target.close(); source.close()'
docker compose cp stream:/data/events-backup.sqlite ./backups/events-backup.sqlite
docker compose exec -T stream rm /data/events-backup.sqlite
```

Move that backup to a separate device or storage account. The file includes unpublished scenario labels, so keep it private. `backups/` is ignored by Git. Before an update, make a backup; then pull the branch and run `docker compose --profile public up -d --build`. The named `stream_data` volume survives container recreation. Never run two producers against the same SQLite file.

For service diagnostics, use `docker compose ps`, `docker compose logs --tail=100 stream`, and `docker compose logs --tail=100 proxy`. Container logs rotate at three 10 MB files per service to limit disk use.
