-- INAURA Phase 5B — Skill-specific 3-layer assessment
-- Run in Supabase SQL Editor after 012_skill_assessment.sql
--
-- Adds Layer 2 (practical work-sample attempts) and Layer 3 (AI skill
-- interview sessions). Purely additive: no existing table, column, or
-- historical row is modified. Knowledge-layer behavior is unchanged.
--
-- Privacy: interview sessions store the deterministic plan and the user's
-- WRITTEN answers only. Video/audio is never stored by the application.

-- 1. Practical attempts (one row per started work-sample attempt)
create table if not exists public.assessment_practical_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid references public.skills(id) on delete set null,
  skill_key text not null,
  skill_name text not null,
  task_id text not null,
  task_version text not null,
  status text not null default 'in_progress'
    check (status in ('in_progress', 'completed', 'expired', 'abandoned')),
  -- The submission IS the evidence here (structural checks only; code is
  -- never executed server-side).
  submission text not null default '',
  score double precision not null default 0 check (score between 0 and 1),
  validity text not null default 'valid'
    check (validity in ('valid', 'low_confidence', 'invalid')),
  -- Per-check pass/fail and per-dimension scores only.
  result_summary jsonb not null default '{}'::jsonb,
  duration_seconds int,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_practical_attempts on public.assessment_practical_attempts;
create trigger set_updated_at_practical_attempts
  before update on public.assessment_practical_attempts
  for each row execute function public.handle_updated_at();

alter table public.assessment_practical_attempts enable row level security;
drop policy if exists "Users can manage own practical attempts" on public.assessment_practical_attempts;
create policy "Users can manage own practical attempts" on public.assessment_practical_attempts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.assessment_practical_attempts to authenticated, service_role;

create index if not exists idx_practical_attempts_user on public.assessment_practical_attempts (user_id);
create index if not exists idx_practical_attempts_user_skill
  on public.assessment_practical_attempts (user_id, skill_name, completed_at desc);

-- 2. AI skill interview sessions (one row per skill-specific interview)
create table if not exists public.assessment_interview_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid references public.skills(id) on delete set null,
  skill_key text not null,
  skill_name text not null,
  interview_version text not null,
  status text not null default 'in_progress'
    check (status in ('in_progress', 'awaiting_review', 'graded', 'completed', 'expired', 'abandoned')),
  -- Deterministic competency-anchored plan (questions carry competency ids).
  plan jsonb not null default '{}'::jsonb,
  -- Written answers only: [{question_id, competency, prompt, answer, answered}].
  transcript jsonb not null default '[]'::jsonb,
  -- Technical scores feed the skill signal; communication scores NEVER do
  -- (kept separate by construction).
  technical_scores jsonb,
  communication_scores jsonb,
  validity text not null default 'valid'
    check (validity in ('valid', 'low_confidence', 'invalid')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_interview_sessions on public.assessment_interview_sessions;
create trigger set_updated_at_interview_sessions
  before update on public.assessment_interview_sessions
  for each row execute function public.handle_updated_at();

alter table public.assessment_interview_sessions enable row level security;
drop policy if exists "Users can manage own interview sessions" on public.assessment_interview_sessions;
create policy "Users can manage own interview sessions" on public.assessment_interview_sessions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.assessment_interview_sessions to authenticated, service_role;

create index if not exists idx_interview_sessions_user on public.assessment_interview_sessions (user_id);
create index if not exists idx_interview_sessions_user_skill
  on public.assessment_interview_sessions (user_id, skill_name, completed_at desc);

comment on table public.assessment_practical_attempts is
  'Phase 5B Layer 2 — practical work-sample attempts. Deterministic structural grading; submissions stored as evidence, never executed.';
comment on table public.assessment_interview_sessions is
  'Phase 5B Layer 3 — skill-specific AI interview sessions. Stores plan + written answers only; video/audio is never stored. Technical and communication scores kept separate.';
