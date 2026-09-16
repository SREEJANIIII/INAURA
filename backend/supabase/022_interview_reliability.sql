-- Durable idempotency records for adaptive voice-interview answers.
-- Run after 021_voice_interview.sql.
create table if not exists public.assessment_interview_answer_claims (
  session_id uuid not null references public.assessment_interview_sessions(id) on delete cascade,
  question_id text not null,
  transcript_hash text not null,
  status text not null default 'processing' check (status in ('processing', 'completed', 'failed')),
  response jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (session_id, question_id)
);

drop trigger if exists set_updated_at_interview_answer_claims on public.assessment_interview_answer_claims;
create trigger set_updated_at_interview_answer_claims
  before update on public.assessment_interview_answer_claims
  for each row execute function public.handle_updated_at();

alter table public.assessment_interview_answer_claims enable row level security;
drop policy if exists "Users can manage own interview answer claims" on public.assessment_interview_answer_claims;
create policy "Users can manage own interview answer claims" on public.assessment_interview_answer_claims
  for all using (exists (
    select 1 from public.assessment_interview_sessions s
    where s.id = session_id and s.user_id = auth.uid()
  )) with check (exists (
    select 1 from public.assessment_interview_sessions s
    where s.id = session_id and s.user_id = auth.uid()
  ));

grant select, insert, update, delete on public.assessment_interview_answer_claims to authenticated, service_role;

-- Completion claims prevent two workers from grading the same session.
create table if not exists public.assessment_interview_completion_claims (
  session_id uuid primary key references public.assessment_interview_sessions(id) on delete cascade,
  status text not null default 'processing' check (status in ('processing', 'completed')),
  response jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_interview_completion_claims on public.assessment_interview_completion_claims;
create trigger set_updated_at_interview_completion_claims
  before update on public.assessment_interview_completion_claims
  for each row execute function public.handle_updated_at();

alter table public.assessment_interview_completion_claims enable row level security;
drop policy if exists "Users can manage own interview completion claims" on public.assessment_interview_completion_claims;
create policy "Users can manage own interview completion claims" on public.assessment_interview_completion_claims
  for all using (exists (
    select 1 from public.assessment_interview_sessions s
    where s.id = session_id and s.user_id = auth.uid()
  )) with check (exists (
    select 1 from public.assessment_interview_sessions s
    where s.id = session_id and s.user_id = auth.uid()
  ));

grant select, insert, update, delete on public.assessment_interview_completion_claims to authenticated, service_role;
