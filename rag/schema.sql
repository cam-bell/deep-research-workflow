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

create or replace function match_chunks(
  query_embedding vector(1536),
  match_count int default 5,
  filter_source text default null
)
returns table (
  id uuid,
  content text,
  source_name text,
  source_url text,
  section_title text,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    c.id,
    c.content,
    c.source_name,
    c.source_url,
    c.section_title,
    1 - (c.embedding <=> query_embedding) as similarity
  from corpus_chunks c
  where filter_source is null or c.source_name = filter_source
  order by c.embedding <=> query_embedding
  limit match_count;
end;
$$;
