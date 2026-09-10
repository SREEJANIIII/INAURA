-- INAURA Phase 5A — Direct Skill Assessment
-- Run in Supabase SQL Editor after 011_gap_analysis_engine.sql
--
-- Adds the assessment attempt store and the columns needed to distinguish
-- evidence-based estimates from assessment-validated results.
-- Purely additive: no existing table, column, or historical row is modified.

-- 1. Assessment attempts (one row per started attempt)
create table if not exists public.assessment_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid references public.skills(id) on delete set null,
  skill_key text not null,
  skill_name text not null,
  assessment_version text not null,
  status text not null default 'in_progress'
    check (status in ('in_progress', 'completed', 'expired', 'abandoned')),
  question_ids text[] not null default '{}',
  question_count int not null default 0,
  correct_count int not null default 0,
  score double precision not null default 0 check (score between 0 and 1),
  validity text not null default 'valid'
    check (validity in ('valid', 'low_confidence', 'invalid')),
  -- Per-question correctness and difficulty mix only. Submitted answer text is
  -- never persisted.
  result_summary jsonb not null default '{}'::jsonb,
  duration_seconds int,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_assessment_attempts on public.assessment_attempts;
create trigger set_updated_at_assessment_attempts
  before update on public.assessment_attempts
  for each row execute function public.handle_updated_at();

alter table public.assessment_attempts enable row level security;
drop policy if exists "Users can manage own assessment attempts" on public.assessment_attempts;
create policy "Users can manage own assessment attempts" on public.assessment_attempts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.assessment_attempts to authenticated, service_role;

create index if not exists idx_assessment_attempts_user on public.assessment_attempts (user_id);
create index if not exists idx_assessment_attempts_user_skill
  on public.assessment_attempts (user_id, skill_name, completed_at desc);

-- 2. Record the assessment contribution alongside each per-skill result so the
--    UI can separate "evidence-based estimate" from "assessment" and "final".
alter table if exists public.skill_assessments
  add column if not exists evidence_proficiency double precision,
  add column if not exists assessment_score double precision,
  add column if not exists validation_strength double precision,
  add column if not exists has_assessment boolean not null default false,
  add column if not exists metadata jsonb not null default '{}'::jsonb;

-- 3. Allow the new evidence source in skill_signals.source_type.
do $$
begin
  if exists (
    select 1 from information_schema.constraint_column_usage
    where table_schema = 'public'
      and table_name = 'skill_signals'
      and constraint_name = 'skill_signals_source_type_check'
  ) then
    alter table public.skill_signals drop constraint skill_signals_source_type_check;
  end if;
end $$;

alter table public.skill_signals
  add constraint skill_signals_source_type_check
  check (source_type in (
    'github', 'leetcode', 'codeforces', 'kaggle', 'linkedin', 'resume',
    'syllabus', 'coursework', 'certification', 'certification_file',
    'project', 'project_doc', 'self_declared', 'assessment'
  ));

comment on table public.assessment_attempts is
  'Phase 5A — INAURA direct skill assessment attempts. Prototype heuristic instrument; stores correctness only, never answer text.';
comment on column public.assessment_attempts.validity is
  'valid = counts as evidence; low_confidence = partial/expired submission; invalid = malformed attempt';
comment on column public.skill_assessments.evidence_proficiency is
  'Proficiency from non-assessment evidence only (GitHub/projects/platforms/documents)';
comment on column public.skill_assessments.assessment_score is
  'Normalized score (correct/total) of the effective INAURA assessment for this skill';
comment on column public.skill_assessments.validation_strength is
  'How directly the strongest evidence demonstrates the person''s own ability (confidence model input)';
