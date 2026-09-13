-- INAURA Retrieval Source Provenance — Phase 6
-- Extends match_industry_requirements so vector-path retrieval preserves the
-- same source metadata the deterministic fallback already carries: quality,
-- evidence context, and timestamps. Additive only: same function signature
-- and argument order, additional OUT columns. Callers read columns by name
-- (item.get(...)), so old and new database versions both keep working.
-- Safe to re-run (idempotent).

-- 1. Recreate RPC with source-provenance columns (768-d, matching 016)
drop function if exists public.match_industry_requirements(vector, text, int);

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
  source_quality double precision,
  evidence_context text,
  published_at date,
  retrieved_at timestamptz,
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
    r.source_quality,
    r.evidence_context,
    r.published_at,
    r.retrieved_at,
    1 - (r.embedding <=> query_embedding) as similarity
  from public.industry_requirements r
  where r.embedding is not null
    and (filter_role is null or r.role = filter_role)
  order by r.embedding <=> query_embedding
  limit match_count;
end;
$$;

grant execute on function public.match_industry_requirements to anon, authenticated, service_role;

comment on function public.match_industry_requirements is 'Phase 6 — vector match with source provenance (source_quality, evidence_context, published_at, retrieved_at) so pgvector retrieval preserves the same metadata as the deterministic fallback path.';
