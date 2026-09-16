-- INAURA Adaptive Weekly Roadmap & Learner State Engine — Migration 022
-- Run in Supabase SQL Editor after 021_voice_interview.sql
-- Creates:
--   1. evidence_snapshots (immutable historical record before roadmap generation)
--   2. learner_skill_states (explicit KNOWN / INFERRED / UNKNOWN skill states)
--   3. skill_dependencies (DAG of canonical prerequisites)
--   4. roadmap_weeks (weekly time-budgeted containers)
--   5. roadmap_tasks (4-stage tasks: learn, practice, build, validate)

-- 1. Evidence Snapshots Table
create table if not exists public.evidence_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  analysis_result_id uuid references public.analysis_results(id) on delete set null,
  sources_analyzed jsonb not null default '[]'::jsonb,
  sources_available jsonb not null default '[]'::jsonb,
  sources_unavailable jsonb not null default '[]'::jsonb,
  learner_skill_states jsonb not null default '{}'::jsonb,
  engine_version text not null default '5A-v1',
  created_at timestamptz not null default now()
);

alter table public.evidence_snapshots enable row level security;
drop policy if exists "Users can manage own evidence snapshots" on public.evidence_snapshots;
create policy "Users can manage own evidence snapshots"
  on public.evidence_snapshots for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
grant select, insert, update, delete on public.evidence_snapshots to authenticated, service_role;
create index if not exists idx_evidence_snapshots_user on public.evidence_snapshots(user_id, created_at desc);

-- 2. Learner Skill States (Persistent latest learner state per skill)
create table if not exists public.learner_skill_states (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_slug text not null,
  skill_name text not null,
  state_classification text not null check (state_classification in ('KNOWN', 'INFERRED', 'UNKNOWN')),
  proficiency double precision not null check (proficiency between 0 and 1),
  confidence double precision not null check (confidence between 0 and 1),
  required_level double precision not null default 0.75,
  gap double precision not null default 0.0,
  evidence_coverage double precision not null default 0.0,
  evidence_strength double precision not null default 0.0,
  evidence_count integer not null default 0,
  evidence_depth integer not null default 0,
  evidence_recency_days integer,
  active_sources jsonb not null default '[]'::jsonb,
  evidence_ids jsonb not null default '[]'::jsonb,
  reasoning text not null default '',
  last_evaluated_at timestamptz not null default now(),
  unique(user_id, skill_slug)
);

alter table public.learner_skill_states enable row level security;
drop policy if exists "Users can manage own learner skill states" on public.learner_skill_states;
create policy "Users can manage own learner skill states"
  on public.learner_skill_states for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
grant select, insert, update, delete on public.learner_skill_states to authenticated, service_role;
create index if not exists idx_learner_skill_states_user on public.learner_skill_states(user_id);
create index if not exists idx_learner_skill_states_slug on public.learner_skill_states(user_id, skill_slug);

-- 3. Skill Dependencies Table (Canonical DAG)
create table if not exists public.skill_dependencies (
  id uuid primary key default gen_random_uuid(),
  skill_slug text not null,
  prerequisite_slug text not null,
  dependency_type text not null check (dependency_type in ('hard_requirement', 'recommended_prior', 'conceptual_overlap')) default 'recommended_prior',
  description text,
  created_at timestamptz not null default now(),
  unique(skill_slug, prerequisite_slug)
);

alter table public.skill_dependencies enable row level security;
drop policy if exists "All authenticated users can read skill dependencies" on public.skill_dependencies;
create policy "All authenticated users can read skill dependencies"
  on public.skill_dependencies for select
  to authenticated, service_role, anon
  using (true);
grant select on public.skill_dependencies to authenticated, service_role, anon;
grant insert, update, delete on public.skill_dependencies to service_role;
create index if not exists idx_skill_deps_slug on public.skill_dependencies(skill_slug);
create index if not exists idx_skill_deps_prereq on public.skill_dependencies(prerequisite_slug);

-- 4. Extend roadmaps table with adaptive & snapshot metadata
alter table public.roadmaps
  add column if not exists evidence_snapshot_id uuid references public.evidence_snapshots(id) on delete set null,
  add column if not exists weekly_hours_budget integer default 10,
  add column if not exists total_weeks integer default 4,
  add column if not exists current_week_index integer default 1,
  add column if not exists adaptive_rebalance_count integer default 0,
  add column if not exists last_rebalanced_at timestamptz;

-- 5. Roadmap Weeks Table
create table if not exists public.roadmap_weeks (
  id uuid primary key default gen_random_uuid(),
  roadmap_id uuid not null references public.roadmaps(id) on delete cascade,
  week_number integer not null check (week_number >= 1),
  title text not null,
  objective text not null,
  estimated_hours double precision not null check (estimated_hours >= 0) default 0,
  skills jsonb not null default '[]'::jsonb, -- Array of skill slugs/names
  status text not null check (status in ('locked', 'current', 'completed', 'behind_schedule')) default 'locked',
  completion_percentage double precision not null check (completion_percentage between 0 and 100) default 0,
  start_date date,
  target_completion_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(roadmap_id, week_number)
);

alter table public.roadmap_weeks enable row level security;
drop policy if exists "Users can manage own roadmap weeks" on public.roadmap_weeks;
create policy "Users can manage own roadmap weeks"
  on public.roadmap_weeks for all
  using (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()))
  with check (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()));
grant select, insert, update, delete on public.roadmap_weeks to authenticated, service_role;
create index if not exists idx_roadmap_weeks_roadmap on public.roadmap_weeks(roadmap_id, week_number);

-- 6. Roadmap Tasks Table (4 stages: learn, practice, build, validate)
create table if not exists public.roadmap_tasks (
  id uuid primary key default gen_random_uuid(),
  roadmap_week_id uuid not null references public.roadmap_weeks(id) on delete cascade,
  skill_slug text not null,
  skill_name text not null,
  task_type text not null check (task_type in ('learn', 'practice', 'build', 'validate')),
  title text not null,
  description text not null,
  estimated_minutes integer not null check (estimated_minutes > 0),
  sequence_order integer not null,
  status text not null check (status in ('not_started', 'in_progress', 'completed', 'skipped')) default 'not_started',
  completion_percentage double precision not null check (completion_percentage between 0 and 100) default 0,
  resources jsonb not null default '[]'::jsonb, -- Array of resource objects
  validation_method text not null default 'self_check', -- quiz, code_submission, repo_inspection, practical_test, self_check
  evidence_generated jsonb default null, -- Signal record generated upon completion
  why_this_task text not null default '',
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.roadmap_tasks enable row level security;
drop policy if exists "Users can manage own roadmap tasks" on public.roadmap_tasks;
create policy "Users can manage own roadmap tasks"
  on public.roadmap_tasks for all
  using (exists (
    select 1 from public.roadmap_weeks rw
    join public.roadmaps r on r.id = rw.roadmap_id
    where rw.id = roadmap_week_id and r.user_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.roadmap_weeks rw
    join public.roadmaps r on r.id = rw.roadmap_id
    where rw.id = roadmap_week_id and r.user_id = auth.uid()
  ));
grant select, insert, update, delete on public.roadmap_tasks to authenticated, service_role;
create index if not exists idx_roadmap_tasks_week on public.roadmap_tasks(roadmap_week_id, sequence_order);
create index if not exists idx_roadmap_tasks_skill on public.roadmap_tasks(skill_slug);
