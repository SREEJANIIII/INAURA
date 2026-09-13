-- INAURA Industry Evidence Trust — Phase 7
-- Reserves additive columns so industry requirements can carry evidence
-- strength tiers and supporting knowledge-chunk references directly on the
-- row. Additive and idempotent: existing selects, RPCs, and application code
-- keep working whether or not this migration has been applied, because all
-- readers use defensive .get() access with deterministic fallbacks.
-- Safe to re-run.

alter table public.industry_requirements
  add column if not exists evidence_strength text not null default 'moderate'
    check (evidence_strength in ('strong', 'moderate', 'weak', 'insufficient')),
  add column if not exists supporting_chunks jsonb not null default '[]'::jsonb,
  add column if not exists duplicate_sources_collapsed integer not null default 0
    check (duplicate_sources_collapsed >= 0);

comment on column public.industry_requirements.evidence_strength is 'Phase 7 — trust tier for this requirement: strong (2+ distinct solid sources), moderate (single solid source), weak (low-quality source), insufficient (no usable source). Computed deterministically; see industry_service.classify_requirement_evidence.';
comment on column public.industry_requirements.supporting_chunks is 'Phase 7 — references (chunk id, role, topic, source, url) to benchmark knowledge chunks mentioning this skill. References only; chunk bodies are never copied here.';
comment on column public.industry_requirements.duplicate_sources_collapsed is 'Phase 7 — count of same-source duplicate rows collapsed during aggregation so one source cannot stack influence.';
