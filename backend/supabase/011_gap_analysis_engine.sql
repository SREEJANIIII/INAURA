-- Phase 4D: Gap Analysis & Readiness Engine Schema Enhancement
-- Adds gap categorization, gap types, industry confidence, and explainability context

-- 1. Extend skill_gaps table
alter table if exists public.skill_gaps
  add column if not exists gap_type text not null default 'skill_gap'
    check (gap_type in ('skill_gap', 'evidence_gap', 'coverage_gap', 'industry_data_gap')),
  add column if not exists priority_category text not null default 'medium'
    check (priority_category in ('critical', 'high', 'medium', 'low', 'covered')),
  add column if not exists industry_confidence double precision default 0.85,
  add column if not exists evidence_context text,
  add column if not exists actionable_advice text;

create index if not exists idx_gaps_type on public.skill_gaps (gap_type);
create index if not exists idx_gaps_category on public.skill_gaps (priority_category);

-- 2. Extend analysis_results table
alter table if exists public.analysis_results
  add column if not exists readiness_explanation text,
  add column if not exists industry_confidence double precision default 0.85,
  add column if not exists metadata jsonb default '{}'::jsonb;

comment on column public.skill_gaps.gap_type is 'Gap classification: skill_gap, evidence_gap, coverage_gap, industry_data_gap';
comment on column public.skill_gaps.priority_category is 'Priority tier: critical, high, medium, low, covered';
comment on column public.skill_gaps.actionable_advice is 'Constructive next step or proof artifact recommendation';
comment on column public.analysis_results.metadata is 'Enriched gap summary, DSA topic gaps, and strength highlights';
