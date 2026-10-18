# Frontend

The Vue 3 UI of the Navigator: the case **Pipeline** board (`/`) and the **Sources** page (`/sources`). It uses Vite,
TypeScript, Pinia and vue-router, with its own small components in `src/components/ui` (no component library). The
backend contract is in [`docs/FRONTEND_API.md`](../docs/FRONTEND_API.md).

## Develop

Node `^22.18` or `>=24.12`.

```sh
npm ci
npm run dev                  # http://localhost:5173, real backend at http://localhost:8000
```

The dev server proxies `/api` to the backend (`vite.config.ts`), so the browser only talks to one origin and the
backend needs no CORS. To run without a backend, or against someone else's:

```sh
VITE_USE_MOCK=true npm run dev                                         # in-memory mock (src/api/mock.ts)
BACKEND_URL=http://<host-ip>:8000 BACKEND_TOKEN=<token> npm run dev    # a teammate's backend
```

In Docker, `docker compose up -d` runs this same dev server with hot reload on :5173 (the repository README,
"Run with Docker").

## Settings

| Variable | When | Effect |
|---|---|---|
| `BACKEND_URL` | dev server | where `/api` goes (default `http://localhost:8000`) |
| `BACKEND_TOKEN` | dev server | sent as `Authorization: Bearer ...` by the proxy, never to the browser ([`docs/SHARED_SERVER.md`](../docs/SHARED_SERVER.md)) |
| `VITE_USE_MOCK` | build time | `true`: the in-memory mock instead of the backend; a "mock" badge shows in the header |
| `VITE_SHOW_UNFINISHED` | build time | `true`: show controls whose backend is not there yet (the chat examples, #97); always on with the mock |
| `VITE_API_BASE_URL` | build time | the API on another origin; needs CORS on the backend, which it does not have, so leave it unset |

`VITE_*` values are baked into the bundle when it is built, not read at runtime.

## Code map

| Path | What |
|---|---|
| `src/api/client.ts` | every request; errors are `Error("<status> <detail>")` with the backend's `detail` |
| `src/api/index.ts` | the typed endpoints, and the switch between the backend and the mock |
| `src/api/types.ts` | the response types, mirroring `src/navigator/models.py` |
| `src/api/mock.ts` | the mock: same shapes and errors as the backend; keep it in step when a route changes |
| `src/stores/` | `cases` (board, drawer, chat, pitch, feedback) and `sources` (sources, pages, crawl rules) |
| `src/views/` | `BoardView` and `SourcesView` |
| `src/components/` | the drawer, cards, chat, evidence list, crawl graph and rules; `ui/` holds the base components |

## Check and build

```sh
npm run lint                 # oxlint + eslint (they fix what they can)
npm run build                # vue-tsc type check + production build into dist/
npm run format               # prettier on src/
```

CI runs `npx oxlint . && npx eslint .` and `npm run build` on every pull request.

## Production image

`Dockerfile` builds the bundle and serves it with nginx (`deploy/default.conf.template`):

- `/api` is proxied to `BACKEND_URL` (default `http://app:8000`), and the proxy adds `API_TOKEN`.
- Unknown paths fall back to `index.html`, for the history-mode routes.
- Uploads may be up to 12 MB, and proxied calls wait up to 180 s for the LLM.

The image is built with `VITE_USE_MOCK=false` and `VITE_SHOW_UNFINISHED=false` by default
(`--build-arg` to change). [`docs/HANDOFF.md`](../docs/HANDOFF.md) runs it through `docker-compose.handoff.yml`.
