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
  rel         text NOT NULL CHECK (rel IN ('member_of','part_of','works_on','provides','listed_in')),
  to_id       int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  quote       text NOT NULL,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false,
  UNIQUE (from_id, rel, to_id, page_id)
);

-- [PoC] LLM judge verdicts (section 7.8). ALTER so existing databases get the columns too.
ALTER TABLE claim    ADD COLUMN IF NOT EXISTS judge_verdict text CHECK (judge_verdict IN ('supported','partial','unsupported'));
ALTER TABLE claim    ADD COLUMN IF NOT EXISTS judge_reason  text;
ALTER TABLE relation ADD COLUMN IF NOT EXISTS judge_verdict text CHECK (judge_verdict IN ('supported','partial','unsupported'));
ALTER TABLE relation ADD COLUMN IF NOT EXISTS judge_reason  text;

-- listed_in (person -> unit): the person is listed on the unit's member page (#23). Not member_of:
-- the quote (the person's name on that page) supports "listed on", not "is a member of".
-- Created by resolve, never by the extractor. Re-created here so existing databases accept it.
ALTER TABLE relation DROP CONSTRAINT IF EXISTS relation_rel_check;
ALTER TABLE relation ADD CONSTRAINT relation_rel_check
  CHECK (rel IN ('member_of','part_of','works_on','provides','listed_in'));

-- Raw extraction output, one row per claim / relation, before entity merging (resolve).
-- Kept so resolve can be re-run without new LLM calls.
CREATE TABLE IF NOT EXISTS raw_claim (
  id           serial PRIMARY KEY,
  page_id      int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  entity_type  text NOT NULL,
  entity_name  text NOT NULL,
  field        text NOT NULL,
  value        text NOT NULL,
  quote        text NOT NULL,              -- exact page text when verified, model output otherwise
  verified     boolean NOT NULL,
  fail_reason  text
);
CREATE INDEX IF NOT EXISTS raw_claim_page_idx ON raw_claim(page_id);

CREATE TABLE IF NOT EXISTS raw_relation (
  id           serial PRIMARY KEY,
  page_id      int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  from_type    text NOT NULL,
  from_name    text NOT NULL,
  rel          text NOT NULL,
  to_type      text NOT NULL,
  to_name      text NOT NULL,
  quote        text NOT NULL,
  verified     boolean NOT NULL,
  fail_reason  text
);
CREATE INDEX IF NOT EXISTS raw_relation_page_idx ON raw_relation(page_id);

-- [PoC] User feedback from the UI. Log only: it never changes what is shown.
-- entity/claim ids change on re-ingest, so keep a text snapshot; ids become NULL.
CREATE TABLE IF NOT EXISTS feedback (
  id          serial PRIMARY KEY,
  session_id  text NOT NULL,
  query       text,
  entity_id   int REFERENCES entity(id) ON DELETE SET NULL,
  claim_id    int REFERENCES claim(id) ON DELETE SET NULL,
  entity_name text,
  claim_text  text,
  rating      text NOT NULL CHECK (rating IN ('up','down','wrong_fact')),
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Business model PDFs uploaded on the board (FRONTEND_API "Cases", #52). Company data, not public data:
-- only the PDF's text is stored, never the file. "case" is a reserved word, so always quote it.
CREATE TABLE IF NOT EXISTS "case" (
  id              text PRIMARY KEY,
  company_name    text NOT NULL,
  file_name       text NOT NULL,
  uploaded_at     timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_review','accepted','rejected')),
  analysis_status text NOT NULL DEFAULT 'pending' CHECK (analysis_status IN ('pending','done','failed')),
  industry        text,
  score           int CHECK (score BETWEEN 0 AND 100),
  score_breakdown jsonb NOT NULL DEFAULT '[]',  -- [{criterion, score, rationale}]
  summary         text,
  pdf_text        text NOT NULL,
  needs           jsonb NOT NULL DEFAULT '[]',  -- analysis output (#53): search queries
  refs            jsonb NOT NULL DEFAULT '[]',  -- analysis output (#53): [{entity_id, needs}], best first
  pitch           jsonb                         -- last sales pitch (#54): {text, entity_ids, generated_at}
);
CREATE INDEX IF NOT EXISTS case_uploaded_idx ON "case"(uploaded_at DESC);
ALTER TABLE "case" ADD COLUMN IF NOT EXISTS pitch jsonb;
