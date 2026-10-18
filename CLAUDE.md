# CLAUDE.md

Setup, pipeline order and tests: [`README.md`](README.md). Build plan: [`docs/PLAN.md`](docs/PLAN.md).
Frontend ↔ backend contract: [`docs/FRONTEND_API.md`](docs/FRONTEND_API.md).

## Shared backend

The team may share one backend over the LAN instead of each running Postgres, embeddings and the LLM
locally. The API then requires a bearer token (`API_TOKEN` on the host, `BACKEND_TOKEN` for the frontend
proxy). See [`docs/SHARED_SERVER.md`](docs/SHARED_SERVER.md) for both the host and the teammate side.

- To work against a teammate's backend: `cd frontend && BACKEND_URL=http://<host-ip>:8000 BACKEND_TOKEN=<token> npm run dev`.
  Ask the user for the host IP and token; never write the token into a tracked file.
- A `401` from `/api` means a missing or wrong token, not a bug in the route.
