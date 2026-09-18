# Running the stream continuously

The local PowerShell command stops when the terminal closes. The container setup runs the same producer as a service and keeps its SQLite replay log in a Docker volume. It works on a single Linux VPS; a public hostname and DNS record are needed for the HTTPS proxy.

For the proposed Tencent Lighthouse instance, pricing checks, firewall settings, validation steps, and backups, see [the Lighthouse plan](tencent-lighthouse.md).

## Local container check

From the repository root on a machine with Docker Compose:

```sh
docker compose up -d --build stream
docker compose ps
curl http://127.0.0.1:8080/health
```

Open `http://127.0.0.1:8080/` to see events. The container restarts unless it is deliberately stopped. The `stream_data` volume remains when the container is recreated, so event sequence numbers and scheduled status changes continue. The event log still retains only seven days of published events.

## Public VPS

1. Create a small Linux VPS with Docker Engine and the Compose plugin. Point a hostname such as `stream.example.com` at its public IP.
2. Allow inbound ports 80 and 443. Port 8080 is bound to the VPS loopback interface by Compose, so it is not directly public.
3. Clone this repository and set the hostname before starting the public profile:

```sh
export STREAM_DOMAIN=stream.example.com
docker compose --profile public up -d --build
docker compose ps
curl https://stream.example.com/health
```

Caddy proxies the HTTP event stream and obtains HTTPS certificates when the hostname resolves to the VPS and ports 80 and 443 are reachable. Its certificate data is kept in the `caddy_data` volume. The API and producer live in the `stream` container; Caddy is only the public entry point.

To inspect service output, run `docker compose logs -f stream`. After changing the application, run `docker compose --profile public up -d --build` again. Do not start a second copy of the producer against the same SQLite file. The single producer is what gives every client the same event timeline.

No cloud server or domain has been created for this project yet. The reference tables are currently fixed at startup; adding new reference records and corresponding stream events is a separate step before broad public use.
