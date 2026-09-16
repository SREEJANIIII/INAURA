-- INAURA — Adaptive AI mock interview (evidence source)
-- Run in Supabase SQL Editor after 019_assessment_layers.sql
--
-- Stores ONLY transcripts + structured evaluations. Raw video/audio is NEVER
-- stored: camera/mic stay in the browser for presence. Purely additive: no
-- existing table, column, or historical row is modified.

-- 1. Sessions (one row per multi-skill mock interview)
create table if not exists public.mock_interview_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  target_role text not null,
  status text not null default 'in_progress'
    check (status in ('in_progress', 'completed', 'abandoned', 'expired')),
  current_index int not null default 0,
  question_count int not null default 6,
  -- Deterministic evidence-driven plan context (ranked skills, no PII)
  plan jsonb not null default '{}'::jsonb,
  -- Snapshot of prior proficiency/confidence per skill for contradiction
  -- detection (copied at start; never mutated afterwards)
  prior_snapshot jsonb not null default '[]'::jsonb,
  -- Final evidence report (skill_results, corroboration, inconsistencies)
  report jsonb,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_mock_interview_sessions on public.mock_interview_sessions;
create trigger set_updated_at_mock_interview_sessions
  before update on public.mock_interview_sessions
  for each row execute function public.handle_updated_at();

alter table public.mock_interview_sessions enable row level security;
drop policy if exists "Users can manage own mock interviews" on public.mock_interview_sessions;
create policy "Users can manage own mock interviews" on public.mock_interview_sessions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.mock_interview_sessions to authenticated, service_role;

create index if not exists idx_mock_interview_sessions_user
  on public.mock_interview_sessions (user_id);
create index if not exists idx_mock_interview_sessions_user_status
  on public.mock_interview_sessions (user_id, status, created_at desc);

-- 2. Questions (deterministic plan + adaptive follow-ups)
create table if not exists public.mock_interview_questions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.mock_interview_sessions(id) on delete cascade,
  question_key text not null,
  sequence int not null,
  question text not null,
  question_type text not null default 'technical',
  target_skill text not null default '',
  source_evidence text not null default '',
  priority double precision not null default 0,
  interview_relevance double precision not null default 0,
  is_follow_up boolean not null default false,
  parent_question_id uuid references public.mock_interview_questions(id) on delete set null,
  created_at timestamptz not null default now()
);

alter table public.mock_interview_questions enable row level security;
drop policy if exists "Users can manage own mock interview questions" on public.mock_interview_questions;
create policy "Users can manage own mock interview questions" on public.mock_interview_questions
  for all using (
    exists (select 1 from public.mock_interview_sessions s where s.id = session_id and s.user_id = auth.uid())
  ) with check (
    exists (select 1 from public.mock_interview_sessions s where s.id = session_id and s.user_id = auth.uid())
  );
grant select, insert, update, delete on public.mock_interview_questions to authenticated, service_role;

create index if not exists idx_mock_interview_questions_session
  on public.mock_interview_questions (session_id, sequence);

-- 3. Responses (transcript + structured evaluation only)
create table if not exists public.mock_interview_responses (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.mock_interview_sessions(id) on delete cascade,
  question_id uuid references public.mock_interview_questions(id) on delete set null,
  question_key text not null default '',
  transcript text not null default '',
  evaluation jsonb,
  created_at timestamptz not null default now()
);

alter table public.mock_interview_responses enable row level security;
drop policy if exists "Users can manage own mock interview responses" on public.mock_interview_responses;
create policy "Users can manage own mock interview responses" on public.mock_interview_responses
  for all using (
    exists (select 1 from public.mock_interview_sessions s where s.id = session_id and s.user_id = auth.uid())
  ) with check (
    exists (select 1 from public.mock_interview_sessions s where s.id = session_id and s.user_id = auth.uid())
  );
grant select, insert, update, delete on public.mock_interview_responses to authenticated, service_role;

create index if not exists idx_mock_interview_responses_session
  on public.mock_interview_responses (session_id, created_at);

comment on table public.mock_interview_sessions is
  'Adaptive AI mock interview sessions. Evidence source only: plan + prior snapshot + report. No video/audio stored.';
comment on table public.mock_interview_questions is
  'Mock interview questions: deterministic evidence-driven plan plus adaptive follow-ups.';
comment on table public.mock_interview_responses is
  'Mock interview answers: transcript + structured Gemini evaluation only.';
