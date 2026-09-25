-- INAURA Phase 3: industry outcome observations — Migration 029
-- Exactly one new table. No changes to existing tables.
-- Scope design (approved Correction 6, option A): scope + location are both
-- NOT NULL. Non-city scopes use the 'GLOBAL' location sentinel, so the
-- UNIQUE key has no NULL ambiguity. No FKs back to Person 2 source tables
-- (retention-decoupled on purpose).
-- Rollback: drop table public.industry_outcome_observations.

create table if not exists public.industry_outcome_observations (
  id uuid primary key default gen_random_uuid(),
  role text not null check (char_length(role) between 2 and 150),
  skill text not null check (char_length(skill) between 1 and 150),
  skill_id uuid references public.skills(id) on delete set null,
  scope text not null check (scope in ('city', 'role', 'global')),
  location text not null check (char_length(location) between 1 and 200),
  window_from timestamptz,
  window_to timestamptz,
  requirements_n integer not null default 0 check (requirements_n >= 0),
  applied_n integer not null default 0 check (applied_n >= 0),
  interview_count integer not null default 0 check (interview_count >= 0),
  selection_count integer not null default 0 check (selection_count >= 0),
  placement_count integer not null default 0 check (placement_count >= 0),
  feedback_count integer not null default 0 check (feedback_count >= 0),
  observed_demand double precision check (observed_demand is null or (observed_demand >= 0 and observed_demand <= 1)),
  observed_skill_gap double precision check (observed_skill_gap is null or (observed_skill_gap >= -1 and observed_skill_gap <= 1)),
  min_n_met boolean not null default false,
  signal_version text not null default 'industry-outcome-signal-v1',
  created_at timestamptz not null default now(),
  constraint industry_outcome_observations_cell_key unique (role, skill, scope, location, window_to)
);

-- RLS: authenticated SELECT only (aggregates, pre-suppressed at write).
-- Writes are service-role only: no authenticated INSERT/UPDATE/DELETE policies.
alter table public.industry_outcome_observations enable row level security;

drop policy if exists "Authenticated can read outcome observations" on public.industry_outcome_observations;
create policy "Authenticated can read outcome observations"
  on public.industry_outcome_observations for select
  using (auth.uid() is not null);

-- Grants: authenticated + service_role ONLY. Explicitly revoke anon/PUBLIC.
revoke all on public.industry_outcome_observations from anon, public;
grant select on public.industry_outcome_observations to authenticated;
grant select, insert, update, delete on public.industry_outcome_observations to service_role;

-- Lookup index for the overlay merge (latest window per cell).
create index if not exists idx_outcome_obs_cell
  on public.industry_outcome_observations (role, skill, scope, location, window_to desc);

comment on table public.industry_outcome_observations is 'Phase 3: append-only validated aggregate cells (role x skill x scope x window). Suppressed cells store NULL metrics. Never carries PII. Curated industry_requirements remain the sole benchmark source.';
