-- INAURA 013 — Evidence Provenance & Safe Personalization
-- Adds user-controlled personalization without deleting evidence, plus AI-assisted flag.
-- Run in Supabase SQL Editor after 012_skill_assessment.sql
-- Additive only: no existing table/column is dropped.

-- 1. Evidence exclusion + AI-assisted flags on evidence tables
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='is_excluded') then
    alter table public.evidence add column is_excluded boolean not null default false;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='is_ai_assisted') then
    alter table public.evidence add column is_ai_assisted boolean not null default false;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='projects' and column_name='is_excluded') then
    alter table public.projects add column is_excluded boolean not null default false;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='projects' and column_name='is_ai_assisted') then
    alter table public.projects add column is_ai_assisted boolean not null default false;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='certifications' and column_name='is_excluded') then
    alter table public.certifications add column is_excluded boolean not null default false;
  end if;
end $$;

create index if not exists idx_evidence_is_excluded on public.evidence (user_id, is_excluded);
create index if not exists idx_projects_is_excluded on public.projects (user_id, is_excluded);

comment on column public.evidence.is_excluded is 'User excluded this evidence from scoring; raw evidence preserved, scoring inactive';
comment on column public.evidence.is_ai_assisted is 'User marked this evidence as AI-assisted; scoring contribution reduced via reliability, not zeroed';
comment on column public.projects.is_excluded is 'User excluded this project from scoring';
comment on column public.projects.is_ai_assisted is 'Project flagged as AI-assisted';

-- 2. Per-skill user override (downward only to 0)
create table if not exists public.user_skill_overrides (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_name text not null,
  skill_key text not null,
  is_zero_override boolean not null default true,
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, skill_key)
);

drop trigger if exists set_updated_at_user_skill_overrides on public.user_skill_overrides;
create trigger set_updated_at_user_skill_overrides
  before update on public.user_skill_overrides
  for each row execute function public.handle_updated_at();

alter table public.user_skill_overrides enable row level security;
drop policy if exists "Users can manage own skill overrides" on public.user_skill_overrides;
create policy "Users can manage own skill overrides"
  on public.user_skill_overrides for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

grant select, insert, update, delete on public.user_skill_overrides to authenticated, service_role;

create index if not exists idx_user_skill_overrides_user on public.user_skill_overrides (user_id);

comment on table public.user_skill_overrides is 'Per-skill downward personalization: user rejected estimate, effective proficiency forced to 0 until new evidence or assessment';
comment on column public.user_skill_overrides.is_zero_override is 'When true, active proficiency is forced to 0 regardless of evidence; history and raw signals preserved';

-- 3. Allow skill_signals to carry AI-assisted metadata already (no schema change needed)
-- provenance is computed at analysis time from signals + overrides, not stored separately.
