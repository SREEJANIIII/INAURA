-- INAURA Analysis State — Phase 4B
-- Run in Supabase SQL Editor after 003_industry_knowledge.sql

create table if not exists public.analysis_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  target_role text,
  status text not null check (status in ('not_started','ready','processing','completed','failed')),
  last_retrieval jsonb,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

-- Updated_at trigger
drop trigger if exists set_updated_at_analysis on public.analysis_state;
create trigger set_updated_at_analysis
  before update on public.analysis_state
  for each row execute function public.handle_updated_at();

-- RLS — user-specific
alter table public.analysis_state enable row level security;

drop policy if exists "Users can manage own analysis state" on public.analysis_state;
create policy "Users can manage own analysis state"
  on public.analysis_state for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Grants
grant select, insert, update, delete on public.analysis_state to anon, authenticated, service_role;

comment on table public.analysis_state is 'Phase 4B — per-user analysis state (not_started/ready/processing/completed/failed) + last retrieval context. No proficiency yet.';
