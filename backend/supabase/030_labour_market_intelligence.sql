-- INAURA Labour Market Intelligence — Migration 030
-- Provider-neutral persistent ingestion + aggregation layer UNDERNEATH
-- industry_intelligence.py (which is NOT modified here).
--
-- Three tables:
--   labour_market_postings        raw job-posting observations (deduplicated)
--   labour_market_posting_skills  skill observations per posting (mapped or preserved)
--   labour_market_demand_signals  monthly aggregated derived signals
--
-- Design notes:
--   * demand / required_level / importance / trend / confidence in the signals
--     table are DERIVED measurements, never ground truth. Raw counts
--     (posting_count, skill_posting_count, distinct_company_count) are always
--     stored beside them for explainability.
--   * No PII: postings carry company_name + location + description only.
--     Never ingest candidate names, emails, phones, or resumes.
--   * RLS mirrors the industry/employer pattern: authenticated SELECT only;
--     writes are service-role only (refresh/import endpoint is authenticated
--     and idempotent; direct table writes stay server-side).
--   * Safe to re-run (IF NOT EXISTS / idempotent policies).

-- ===========================================================================
-- A) labour_market_postings — raw observations
-- ===========================================================================
create table if not exists public.labour_market_postings (
  id uuid primary key default gen_random_uuid(),
  external_posting_id text,
  provider_id text not null check (char_length(provider_id) between 1 and 120),
  title text not null check (char_length(title) between 1 and 300),
  description text,
  role_key text,
  role_mapping_status text not null default 'unresolved'
    check (role_mapping_status in ('mapped', 'unresolved')),
  company_name text,
  location_country text,
  location_region text,
  location_city text,
  employment_type text,
  published_at timestamptz,
  collected_at timestamptz not null default now(),
  source_url text,
  source_version text,
  content_hash text not null,
  data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  created_at timestamptz not null default now()
);

-- Deduplication: same provider + external id is one posting (when external id exists).
create unique index if not exists uq_lmp_provider_external
  on public.labour_market_postings (provider_id, external_posting_id)
  where external_posting_id is not null;

create index if not exists idx_lmp_role_key on public.labour_market_postings (role_key);
create index if not exists idx_lmp_location
  on public.labour_market_postings (location_country, location_region, location_city);
create index if not exists idx_lmp_published_at on public.labour_market_postings (published_at);
create index if not exists idx_lmp_collected_at on public.labour_market_postings (collected_at);
create index if not exists idx_lmp_provider on public.labour_market_postings (provider_id);
create index if not exists idx_lmp_content_hash on public.labour_market_postings (content_hash);

-- ===========================================================================
-- B) labour_market_posting_skills — per-posting skill observations
-- ===========================================================================
create table if not exists public.labour_market_posting_skills (
  id uuid primary key default gen_random_uuid(),
  posting_id uuid not null references public.labour_market_postings(id) on delete cascade,
  source_concept text not null check (char_length(source_concept) between 1 and 200),
  skill_id uuid references public.skills(id) on delete set null,
  canonical_skill_slug text,
  mapping_status text not null default 'unmapped'
    check (mapping_status in ('mapped', 'unmapped')),
  mapping_rationale text,
  extraction_method text not null default 'taxonomy_match'
    check (extraction_method in ('taxonomy_match', 'provider_tag', 'import')),
  confidence numeric check (confidence is null or (confidence >= 0 and confidence <= 1)),
  created_at timestamptz not null default now(),
  constraint uq_lmps_posting_concept unique (posting_id, source_concept)
);

create index if not exists idx_lmps_posting on public.labour_market_posting_skills (posting_id);
create index if not exists idx_lmps_slug on public.labour_market_posting_skills (canonical_skill_slug);
create index if not exists idx_lmps_status on public.labour_market_posting_skills (mapping_status);

-- ===========================================================================
-- C) labour_market_demand_signals — monthly aggregated derived signals
-- ===========================================================================
create table if not exists public.labour_market_demand_signals (
  id uuid primary key default gen_random_uuid(),
  role_key text not null,
  skill_id uuid references public.skills(id) on delete set null,
  source_concept text,
  canonical_skill_slug text,
  mapping_status text not null default 'mapped'
    check (mapping_status in ('mapped', 'unmapped')),
  location_scope text not null default 'global'
    check (location_scope in ('global', 'country', 'region', 'city')),
  country text,
  region text,
  city text,
  period_start date not null,
  period_end date not null,
  posting_count integer not null default 0 check (posting_count >= 0),
  skill_posting_count integer not null default 0 check (skill_posting_count >= 0),
  distinct_company_count integer check (distinct_company_count is null or distinct_company_count >= 0),
  -- Derived measurements (explainable; raw counts above are authoritative).
  skill_share numeric check (skill_share is null or (skill_share >= 0 and skill_share <= 1)),
  demand numeric check (demand is null or (demand >= 0 and demand <= 1)),
  required_level numeric check (required_level is null or (required_level >= 0 and required_level <= 1)),
  importance numeric check (importance is null or (importance >= 0 and importance <= 1)),
  trend text not null default 'insufficient_data'
    check (trend in ('stable', 'rising', 'emerging', 'declining', 'insufficient_data')),
  confidence numeric check (confidence is null or (confidence >= 0 and confidence <= 1)),
  evidence_suppressed boolean not null default false,
  -- Provenance (every signal answers "where did this come from?").
  provider_id text not null default '',
  data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  source_version text,
  evidence_context text,
  computed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint chk_lmd_period check (period_end >= period_start)
);

-- Logical uniqueness: provider + role + skill-or-concept + location + period.
-- Two partial uniques keep NULL semantics unambiguous: canonical rows carry a
-- slug; raw-concept rows carry a source_concept with mapping_status=unmapped.
create unique index if not exists uq_lmd_canonical_cell
  on public.labour_market_demand_signals
    (provider_id, role_key, canonical_skill_slug, location_scope,
     coalesce(country, ''), coalesce(region, ''), coalesce(city, ''), period_start)
  where canonical_skill_slug is not null;

create unique index if not exists uq_lmd_raw_cell
  on public.labour_market_demand_signals
    (provider_id, role_key, source_concept, location_scope,
     coalesce(country, ''), coalesce(region, ''), coalesce(city, ''), period_start)
  where canonical_skill_slug is null;

create index if not exists idx_lmd_role_period
  on public.labour_market_demand_signals (role_key, period_start);
create index if not exists idx_lmd_provider on public.labour_market_demand_signals (provider_id);
create index if not exists idx_lmd_trend on public.labour_market_demand_signals (trend);

-- ===========================================================================
-- RLS: authenticated SELECT only; writes are service-role only.
-- ===========================================================================
alter table public.labour_market_postings enable row level security;
alter table public.labour_market_posting_skills enable row level security;
alter table public.labour_market_demand_signals enable row level security;

drop policy if exists "Authenticated can read labour postings" on public.labour_market_postings;
create policy "Authenticated can read labour postings"
  on public.labour_market_postings for select
  using (auth.uid() is not null);

drop policy if exists "Authenticated can read labour posting skills" on public.labour_market_posting_skills;
create policy "Authenticated can read labour posting skills"
  on public.labour_market_posting_skills for select
  using (auth.uid() is not null);

drop policy if exists "Authenticated can read labour demand signals" on public.labour_market_demand_signals;
create policy "Authenticated can read labour demand signals"
  on public.labour_market_demand_signals for select
  using (auth.uid() is not null);

revoke all on public.labour_market_postings from anon, public;
revoke all on public.labour_market_posting_skills from anon, public;
revoke all on public.labour_market_demand_signals from anon, public;

grant select on public.labour_market_postings to authenticated;
grant select on public.labour_market_posting_skills to authenticated;
grant select on public.labour_market_demand_signals to authenticated;
grant select, insert, update, delete on public.labour_market_postings to service_role;
grant select, insert, update, delete on public.labour_market_posting_skills to service_role;
grant select, insert, update, delete on public.labour_market_demand_signals to service_role;

comment on table public.labour_market_postings is 'P0#1 raw job-posting observations. Deduplicated by (provider_id, external_posting_id) and content_hash. No PII. Locations come from the posting source, never inferred.';
comment on table public.labour_market_posting_skills is 'P0#1 per-posting skill observations. Unmapped concepts preserved with mapping_status=unmapped, never forced onto unrelated canonical skills.';
comment on table public.labour_market_demand_signals is 'P0#1 monthly aggregated DERIVED signals. demand/required_level/importance/trend/confidence are explainable derivations; raw counts (posting_count, skill_posting_count, distinct_company_count) are authoritative.';
