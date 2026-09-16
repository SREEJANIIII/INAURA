-- INAURA — Phase 1: Adaptive voice interview for skill-specific sessions
-- Run in Supabase SQL Editor after 020_mock_interview.sql
--
-- Extends assessment_interview_sessions with adaptive interview state.
-- Purely additive: no existing column or row is modified or removed.

-- 1. Adaptive state columns (backward-compatible: existing rows get defaults)
alter table public.assessment_interview_sessions
  add column if not exists current_index int not null default 0,
  add column if not exists prior_snapshot jsonb not null default '[]'::jsonb,
  add column if not exists evaluation_results jsonb not null default '[]'::jsonb;

comment on column public.assessment_interview_sessions.current_index is
  'Index of the current question being presented (0-based). Tracks adaptive flow progression.';
comment on column public.assessment_interview_sessions.prior_snapshot is
  'Snapshot of prior proficiency/confidence per skill at session start, for evidence corroboration.';
comment on column public.assessment_interview_sessions.evaluation_results is
  'Per-answer Gemini evaluations: [{question_id, competency, evaluation, follow_up}]';
