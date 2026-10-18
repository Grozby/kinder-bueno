# Sharing a backend on the local network

One teammate runs the backend (database, embeddings, LLM key); the others use it over the LAN,
protected by a shared bearer token.

## Host: the machine that runs the backend

```bash
echo "API_TOKEN=$(openssl rand -hex 24)" >> .env     # shared secret; send it privately, never commit it
uv run navigator serve --host 0.0.0.0 --port 8000    # default host 127.0.0.1 is not reachable from the LAN
ipconfig getifaddr en0                               # macOS: LAN IP to give the teammate
```

With `API_TOKEN` set, every `/api/*` request needs `Authorization: Bearer <token>`, otherwise it gets
`401 {"detail": "Invalid or missing token"}`. Without `API_TOKEN`, the API is open, as in local dev.
`/docs` and `/openapi.json` stay open: they describe the API and contain no data.

## Teammate: using someone else's backend

No database, `KEERA_API_KEY` or model download is needed: only the frontend runs locally.

```bash
cd frontend
BACKEND_URL=http://<host-ip>:8000 BACKEND_TOKEN=<token> npm run dev
```

The Vite dev proxy (`frontend/vite.config.ts`) forwards `/api` to `BACKEND_URL` and adds the
`Authorization` header from `BACKEND_TOKEN`, so the token never reaches browser code.

Direct calls:

```bash
curl -H "Authorization: Bearer <token>" "http://<host-ip>:8000/api/stats"
```

## Troubleshooting

- **Connection refused / timeout**: the host must serve with `--host 0.0.0.0`, both machines must be on
  the same network, and the macOS firewall must allow incoming connections for Python.
- **401**: `BACKEND_TOKEN` does not match the host's `API_TOKEN`; the host must restart `serve` after
  changing `.env`.
- **503 Database unavailable**: Postgres is down on the host (`docker compose up -d db`).

## Caveats

- Plain HTTP: anyone on the same network can read the token. Fine on a trusted LAN; across networks use
  `tailscale serve 8000` or `cloudflared tunnel --url http://localhost:8000` (HTTPS, token still applies).
- Every search calls the LLM with the host's `KEERA_API_KEY`.
