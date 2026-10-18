CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source (
  id          text PRIMARY KEY,
  name        text NOT NULL
);

CREATE TABLE IF NOT EXISTS page (
  id          serial PRIMARY KEY,
  source_id   text NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  url         text NOT NULL UNIQUE,
  title       text,
  text        text NOT NULL,              -- cleaned text; quotes are checked against this
  fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk (
  id          serial PRIMARY KEY,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  ord         int NOT NULL,
  text        text NOT NULL,
  embedding   vector(1024),
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunk_tsv_idx ON chunk USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunk_emb_idx ON chunk USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS entity (
  id          serial PRIMARY KEY,
  type        text NOT NULL CHECK (type IN ('person','unit','project','infrastructure')),
  name        text NOT NULL,
  norm_key    text NOT NULL,
  UNIQUE (type, norm_key)
);

CREATE TABLE IF NOT EXISTS claim (
  id          serial PRIMARY KEY,
  entity_id   int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  field       text NOT NULL,
  value       text NOT NULL,
  quote       text NOT NULL,              -- exact text from page.text
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS claim_entity_idx ON claim(entity_id);
CREATE INDEX IF NOT EXISTS claim_page_idx ON claim(page_id);

CREATE TABLE IF NOT EXISTS relation (
  id          serial PRIMARY KEY,
  from_id     int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rel         text NOT NULL CHECK (rel IN ('member_of','part_of','works_on','provides')),
  to_id       int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  quote       text NOT NULL,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false,
  UNIQUE (from_id, rel, to_id, page_id)
);
