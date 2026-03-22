create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists corpus_chunks (
  id uuid primary key default gen_random_uuid(),
  source_name text not null,
  source_url text not null,
  section_title text,
  content text not null,
  embedding vector(1536),
  date_fetched timestamptz default now(),
  chunk_index integer
);

create index if not exists corpus_chunks_embedding_idx
  on corpus_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create table if not exists research_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  query text not null,
  route text,
  report text,
  sources jsonb,
  eval_scores jsonb,
  cost_usd float,
  latency_ms integer,
  trace_url text,
  created_at timestamptz default now()
);

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  password_hash text not null,
  created_at timestamptz default now()
);
