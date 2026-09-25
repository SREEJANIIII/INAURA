-- INAURA Dynamic Industry Intelligence — Phase 8 (Person 1)
-- Additive and idempotent: extends industry_requirements with optional
-- location / trend / freshness provenance so dynamic overlays can persist.
-- Existing selects, RPCs, and application code keep working because all
-- readers use defensive .get() access with deterministic fallbacks.
-- Safe to re-run. Does NOT touch O*NET/ESCO baseline semantics.

alter table public.industry_requirements
  add column if not exists location_scope text not null default 'global'
    check (location_scope in ('global', 'country', 'region', 'city')),
  add column if not exists location_country text,
  add column if not exists location_region text,
  add column if not exists location_city text,
  add column if not exists location_label text not null default 'Global',
  add column if not exists trend text not null default 'stable'
    check (trend in ('stable', 'rising', 'emerging', 'declining', 'insufficient_data')),
  add column if not exists freshness text not null default 'unknown'
    check (freshness in ('current', 'aging', 'stale', 'unknown')),
  add column if not exists data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  add column if not exists collected_at timestamptz,
  add column if not exists last_updated timestamptz,
  add column if not exists source_concept text,
  add column if not exists mapping_status text not null default 'mapped'
    check (mapping_status in ('mapped', 'unmapped'));

create index if not exists idx_industry_role_location
  on public.industry_requirements (role, location_scope, location_city);
create index if not exists idx_industry_trend
  on public.industry_requirements (trend);
create index if not exists idx_industry_data_origin
  on public.industry_requirements (data_origin);

comment on column public.industry_requirements.location_scope is 'Phase 8 — location scope for this requirement: global (default/baseline), country, region, or city. Global rows apply everywhere; specific rows never fabricate demand.';
comment on column public.industry_requirements.trend is 'Phase 8 — skill trend with evidence gating: stable (baseline default), rising, emerging, declining, insufficient_data. Rising/emerging require dynamic provenance.';
comment on column public.industry_requirements.freshness is 'Phase 8 — freshness state derived from collected_at/last_updated/retrieved_at/published_at (current <=2y, aging 2-8y, stale >8y, unknown when dateless). Mirrors retrieval freshness bounds.';
comment on column public.industry_requirements.data_origin is 'Phase 8 — provenance tier: source_data (O*NET/ESCO/benchmarks), inaura_derived (aggregation/mapping), demo_seeded (deterministic demo, never live).';
comment on column public.industry_requirements.source_concept is 'Phase 8 — original external concept before canonical mapping; preserved verbatim when no clean mapping exists (mapping_status=unmapped).';
