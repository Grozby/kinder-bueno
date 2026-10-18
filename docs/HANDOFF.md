# Running the Navigator (v0.1.0)

How to run the whole Navigator on your own machine: Postgres, the API and the UI, all in Docker. Follow the steps in
order. Development setup is in the [README](../README.md#local-development-setup).

## What you need

- Docker with Compose 2.24 or newer (`docker compose version`). Docker Desktop on macOS or Windows works.
- About 12 GB of free disk space (images ~3 GB, models ~4.5 GB, database) and 8 GB of RAM for Docker.
- Internet access. Search, chat, case analysis and pitches call the Apertus gateway (`gateway.keera.ch`), and the
  first start downloads two models from Hugging Face. Nothing connects to cantonal networks.
- A Keera API key for the Apertus gateway.
- The database snapshot `demo.dump`, which we send you directly. It is not in the repository because it holds the
  text of the crawled pages. It contains no cases, chats or feedback.

## 1. Get the code

```bash
git clone --branch v0.1.0 https://github.com/Grozby/kinder-bueno.git
cd kinder-bueno
mkdir -p checkpoints && cp /path/to/demo.dump checkpoints/demo.dump
```

## 2. Configure

```bash
cp .env.example .env
```

Add this line to `.env`. It selects the packaged stack (`docker-compose.handoff.yml`: the built UI, and only the UI
published), so every `docker compose` command below uses it:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.handoff.yml
```

Then set these three values:

| Variable            | Value                                                                    |
|---------------------|--------------------------------------------------------------------------|
| `KEERA_API_KEY`     | your Keera key                                                           |
| `POSTGRES_PASSWORD` | a password for the database, e.g. the output of `openssl rand -hex 16`  |
| `API_TOKEN`         | a token for the API, e.g. the output of `openssl rand -hex 24`          |

The UI's proxy adds `API_TOKEN` to every API call. You never type it, and the browser never sees it.

## 3. Load the data and the models (once)

```bash
docker compose up -d db                                     # Postgres 16 + pgvector
docker compose run --rm restore                             # loads checkpoints/demo.dump
docker compose build                                        # app and UI images, ~5–10 min
docker compose run --rm app uv run navigator init-db        # brings the snapshot to the current schema
docker compose run --rm app uv run navigator warm           # downloads bge-m3 and the reranker (~4.5 GB)
```

`restore` replaces the whole database. Run it again later only if you want to go back to the snapshot: it deletes
every case, chat and rating added since.

## 4. Start

```bash
docker compose up -d
```

Open **http://localhost:8080**. The API takes about a minute to load its model; until then `docker compose ps` shows
`app` as `starting` and the UI is not up yet.

### Check that it works

1. `docker compose ps`: `db` and `app` are `healthy`, and `frontend` is `running`.
2. The **Sources** page lists `artorg`, `dcb` and `unibe` with their pages.
3. Drop `docs/examples/glucora-business-model.pdf` on the board. The analysis finishes within 1–2 minutes and lists
   experts and units for the company's needs, each linked to its source page.

## Day to day

```bash
docker compose stop                       # stop; data and models are kept
docker compose up -d                      # start again
docker compose logs -f app                # API log
docker compose exec -T db pg_dump -Fc --no-owner -U navigator navigator > backup.dump   # back up
```

All data is in the Docker volumes `pgdata` (database) and `hf_cache` (models). `docker compose down` keeps them;
`docker compose down -v` deletes them.

### Opening the UI to other machines

By default the UI only listens on this machine (127.0.0.1). To open it to your network:

```bash
UI_BIND=0.0.0.0 docker compose up -d frontend      # UI_PORT=80 to change the port as well
```

There are no user accounts: everyone who can open the UI can upload cases and read every case. Only open it on a
network you trust, or put it behind your own login proxy with HTTPS. The database and the API are not reachable from
outside Docker.

### Updating to a new version

```bash
git fetch --tags && git checkout v<new version>
docker compose up -d --build
docker compose run --rm app uv run navigator init-db
```

## Building the data from scratch instead of the snapshot

`ingest` crawls the sources in `config/sources.yaml`, embeds the pages and extracts the facts with Apertus. It takes
about 15–20 minutes for 100 pages.

```bash
docker compose up -d db
docker compose run --rm app uv run navigator ingest
```

How to add a source is in the [README](../README.md#add-a-new-source).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `app` stays `starting` for more than 5 minutes | It is downloading or loading the model. Check with `docker compose logs app`; run step 3's `warm` if you skipped it. |
| The UI shows errors and `/api` answers **502** | The API is down or restarting. Check `docker compose ps` and `docker compose logs app`. |
| The UI is on :5173 and the database on :5432 | `COMPOSE_FILE` is missing from `.env` (step 2), so the development stack started. Add it and run `docker compose up -d`. |
| `/api` answers **401** | `API_TOKEN` was changed in `.env` but the containers still have the old one. Run `docker compose up -d`. |
| Search or case analysis fails or hangs, with gateway errors in the log | Check `KEERA_API_KEY` and that `gateway.keera.ch` is reachable. `docker compose run --rm app uv run navigator llm-speed` measures the gateway. |
| Upload answers **413** | The PDF is larger than 10 MB. |
| `restore` fails with "relation already exists" or similar | Use the snapshot we sent with this version. |

## Limits of this version

- One API process: chats and the background ingest are kept in its memory. Don't scale it to several workers or
  replicas (#103).
- The chat in a case runs a new search for each message; it does not resolve "#1" or "more like" yet (#97).
- Uploaded business models are company data. How they are stored is described under
  [Data protection](../README.md#data-protection).
