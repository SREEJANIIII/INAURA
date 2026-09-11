-- INAURA Gemini Embeddings Migration — 768 dimensions
-- Migrates from OpenAI text-embedding-3-small (1536d) to Google gemini-embedding-001 (768d via MRL)
-- IMPORTANT: Existing 1536-d vectors CANNOT be compared with 768-d Gemini vectors.
-- This migration NULLs existing embeddings; they MUST be regenerated via scripts/reembed_industry_knowledge.py
-- or by re-running the embedding backfill. Until re-embedded, vector search will fallback to keyword.
--
-- Run in Supabase SQL Editor after 015_github_repo_personalization.sql
-- Safe to re-run (idempotent).

-- 1. Drop existing vector indexes (dimension-specific)
drop index if exists public.idx_industry_embedding_hnsw;
drop index if exists public.idx_industry_embedding_ivfflat;
drop index if exists public.idx_knowledge_chunks_embedding_hnsw;
drop index if exists public.idx_knowledge_chunks_embedding_ivfflat;

-- Drop dependent RPCs (will be recreated with new signature)
drop function if exists public.match_industry_knowledge_chunks(vector, int);
drop function if exists public.match_industry_requirements(vector, text, int);

-- 2. Clear existing embeddings (1536-d incompatible with new 768-d)
-- Do NOT attempt to cast; Gemini vs OpenAI spaces are unrelated even if dimensions matched.
update public.industry_requirements set embedding = null where embedding is not null;
update public.industry_knowledge_chunks set embedding = null where embedding is not null;

-- 3. Alter columns to 768 dimensions
-- Use USING NULL to avoid cast error from 1536 -> 768
alter table public.industry_requirements alter column embedding type vector(768) using null;
alter table public.industry_knowledge_chunks alter column embedding type vector(768) using null;

-- 4. Recreate vector indexes for 768-d (HNSW preferred, fallback to IVFFlat)
do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    begin
      create index if not exists idx_industry_embedding_hnsw
        on public.industry_requirements using hnsw (embedding vector_cosine_ops);
    exception when others then
      begin
        create index if not exists idx_industry_embedding_ivfflat
          on public.industry_requirements using ivfflat (embedding vector_cosine_ops) with (lists = 100);
      exception when others then null;
      end;
    end;
    begin
      create index if not exists idx_knowledge_chunks_embedding_hnsw
        on public.industry_knowledge_chunks using hnsw (embedding vector_cosine_ops);
    exception when others then null;
    end;
  end if;
end $$;

-- 5. Recreate RPC: match_industry_knowledge_chunks (768-d)
create or replace function public.match_industry_knowledge_chunks (
  query_embedding vector(768),
  match_count int default 5
) returns table (
  id uuid,
  role text,
  topic text,
  content text,
  skills_mentioned jsonb,
  source text,
  source_url text,
  source_quality double precision,
  similarity double precision
) language plpgsql stable as $$
begin
  return query
  select
    c.id,
    c.role,
    c.topic,
    c.content,
    c.skills_mentioned,
    c.source,
    c.source_url,
    c.source_quality,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.industry_knowledge_chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit match_count;
end;
$$;

grant execute on function public.match_industry_knowledge_chunks to anon, authenticated, service_role;

-- 6. RPC: match_industry_requirements (768-d) — previously missing, now added for retrieval_service._vector_search
create or replace function public.match_industry_requirements (
  query_embedding vector(768),
  filter_role text default null,
  match_count int default 10
) returns table (
  id uuid,
  role text,
  skill text,
  skill_category text,
  importance double precision,
  demand double precision,
  interview_relevance double precision,
  required_level double precision,
  industry_confidence double precision,
  source text,
  source_url text,
  description text,
  similarity double precision
) language plpgsql stable as $$
begin
  return query
  select
    r.id,
    r.role,
    r.skill,
    r.skill_category,
    r.importance,
    r.demand,
    r.interview_relevance,
    r.required_level,
    r.industry_confidence,
    r.source,
    r.source_url,
    r.description,
    1 - (r.embedding <=> query_embedding) as similarity
  from public.industry_requirements r
  where r.embedding is not null
    and (filter_role is null or r.role = filter_role)
  order by r.embedding <=> query_embedding
  limit match_count;
end;
$$;

grant execute on function public.match_industry_requirements to anon, authenticated, service_role;

-- 7. Comments
comment on column public.industry_requirements.embedding is '768-d Gemini gemini-embedding-001 (outputDimensionality=768 via MRL). Previously 1536-d OpenAI text-embedding-3-small; vectors must be regenerated after migration 016.';
comment on column public.industry_knowledge_chunks.embedding is '768-d Gemini gemini-embedding-001 (outputDimensionality=768). NULL until re-embedded via scripts/reembed_industry_knowledge.py';
