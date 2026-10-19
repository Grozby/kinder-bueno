# Running the Navigator (v0.2.1)

How to run the whole Navigator on your own machine: Postgres, the API and the UI, all in Docker. Follow the steps in
order. Development setup is in the [README](../README.md#local-development-setup).

## What you need

- Docker with Compose 2.24 or newer (`docker compose version`). Docker Desktop on macOS or Windows works.
- About 12 GB of free disk space (images ~3 GB, models ~4.5 GB, database) and 8 GB of RAM for Docker.
- Internet access. Search, chat, case analysis and pitches call the Apertus gateway (`gateway.keera.ch`), and the
  first start downloads two models from Hugging Face. Nothing connects to cantonal networks.
- A Keera API key for the Apertus gateway.
- The database snapshot `demo-340-precisa.dump` (340 crawled pages, ~5 MB), which we send you directly with its
  SHA-256 checksum. It is not in the repository because it holds the text of the crawled pages. It contains one
  analysed example case, Precisa Surgical (a fictional company, `docs/examples/precisa-business-model.pdf`), and no
  chats or feedback.

## 1. Get the code

```bash
git clone --branch v0.2.1 https://github.com/Grozby/kinder-bueno.git
cd kinder-bueno
shasum -a 256 /path/to/demo-340-precisa.dump      # must match the checksum we sent
mkdir -p checkpoints && cp /path/to/demo-340-precisa.dump checkpoints/demo.dump
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

### Optional: download the images instead of building them

Every release is published as ready-made images for Intel/AMD and ARM (`ghcr.io/grozby/kinder-bueno-app` and
`-frontend`, public, no login). Downloading them is faster and needs no build tools. To use them, change the
`COMPOSE_FILE` line and add the version:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.handoff.yml:docker-compose.images.yml
NAVIGATOR_VERSION=0.2.1
```

Then run `docker compose pull` instead of `docker compose build` in step 3.

## 3. Load the data and the models (once)

`scripts/demo.sh setup` runs steps 3 and 4 in one go and prints the URL when the stack is healthy.
The commands it runs:

```bash
docker compose up -d db                                     # Postgres 16 + pgvector
docker compose run --rm restore                             # loads checkpoints/demo.dump
docker compose build                                        # app and UI images, ~5–10 min (or `pull`, see step 2)
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
2. The **Sources** page lists `artorg` (110 pages), `dcb` (30) and `unibe` (200).
3. The board shows the **Precisa Surgical** card in "New" with a fit score of **85**. Open it: the breakdown reads
   "5 of 5 needs covered", and of its 25 references the top 10 are preselected, each marked "Matches" and linked
   to its source page.
4. Drop `docs/examples/glucora-business-model.pdf` on the board. The analysis finishes within 1–2 minutes; the score
   is about 60–70, because Apertus reads the PDF afresh on each upload.

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

`ingest` crawls the sources in `backend/config/sources.yaml`, embeds the pages and extracts the facts with Apertus. It takes
about 15–20 minutes per 100 pages, most of it Apertus calls.

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

- Chats and the one-ingest-at-a-time slot are kept in Postgres (#103), so the API may run several workers
  (`navigator serve --workers N`) or replicas on the same database. Each worker loads the models (~3 GB of
  RAM). A case analysis or ingest still runs in the worker that started it: if that worker stops, the
  source shows "interrupted" on the next ingest; a case analysis stays "pending" until it is uploaded again.
- Uploaded business models are company data. How they are stored is described under
  [Data protection](../README.md#data-protection).
