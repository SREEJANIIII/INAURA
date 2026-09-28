-- INAURA P0 #3: Cohort skill supply — Migration 032
-- Tables: cohorts, cohort_members
--
-- Cohorts group existing students (auth.users, the canonical student identity
-- shared with profiles.user_id, skill_signals.user_id, skill_assessments.user_id)
-- under an institution + course. NO new student table, NO skill-state
-- duplication: per-learner verified skill state stays in skill_signals /
-- skill_assessments and is aggregated live by the service layer.
--
-- Reference-data RLS (same convention as 029/030/031): authenticated SELECT;
-- writes go through the backend service-role client only. No anon access.
-- Policies reference no other tables, so RLS cannot recurse.
--
-- Membership history is retained: leaving a cohort sets enrollment_status
-- (never a hard delete from the API). Only one ACTIVE membership per
-- (cohort, student) is allowed; re-joining after withdrawal inserts a new row.
--
-- Rollback (reverse order): drop table if exists cohort_members, cohorts.

create table if not exists public.cohorts (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 200),
  code text,
  start_date date,
  end_date date,
  academic_year text,
  status text not null default 'draft'
    check (status in ('draft', 'active', 'completed', 'archived')),
  data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_cohort_dates check (end_date is null or start_date is null or end_date >= start_date)
);

-- Same course + same cohort name is an accidental duplicate, not a new batch.
create unique index if not exists uq_cohorts_course_name
  on public.cohorts (course_id, (lower(name)));
create unique index if not exists uq_cohorts_code
  on public.cohorts (code) where code is not null;

create table if not exists public.cohort_members (
  id uuid primary key default gen_random_uuid(),
  cohort_id uuid not null references public.cohorts(id) on delete cascade,
  -- Canonical student identifier: auth.users.id, shared with profiles.user_id
  -- and all skill tables. No second student/profile entity.
  user_id uuid not null references auth.users(id) on delete cascade,
  enrollment_status text not null default 'active'
    check (enrollment_status in ('active', 'completed', 'withdrawn')),
  joined_at timestamptz not null default now(),
  exited_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One active membership per (cohort, student). History rows (completed /
-- withdrawn) are retained and may repeat the pair.
create unique index if not exists uq_cohort_members_active
  on public.cohort_members (cohort_id, user_id)
  where enrollment_status = 'active';

-- Updated-at triggers (reuse handle_updated_at from 001)
drop trigger if exists set_updated_at on public.cohorts;
create trigger set_updated_at before update on public.cohorts
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.cohort_members;
create trigger set_updated_at before update on public.cohort_members
  for each row execute function public.handle_updated_at();

-- RLS: authenticated SELECT; writes are service-role only (backend API).
alter table public.cohorts enable row level security;
alter table public.cohort_members enable row level security;

drop policy if exists "Authenticated can read cohorts" on public.cohorts;
create policy "Authenticated can read cohorts"
  on public.cohorts for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read cohort members" on public.cohort_members;
create policy "Authenticated can read cohort members"
  on public.cohort_members for select using (auth.uid() is not null);

-- Grants: authenticated SELECT + service_role ALL. Explicitly revoke anon/PUBLIC.
revoke all on public.cohorts from anon, public;
revoke all on public.cohort_members from anon, public;
grant select on public.cohorts to authenticated;
grant select on public.cohort_members to authenticated;
grant select, insert, update, delete on public.cohorts to service_role;
grant select, insert, update, delete on public.cohort_members to service_role;

-- Lookup indexes
create index if not exists idx_cohorts_course on public.cohorts (course_id);
create index if not exists idx_cohorts_institution on public.cohorts (institution_id);
create index if not exists idx_cohorts_status on public.cohorts (status);
create index if not exists idx_cohort_members_cohort on public.cohort_members (cohort_id);
create index if not exists idx_cohort_members_user on public.cohort_members (user_id);
create index if not exists idx_cohort_members_status on public.cohort_members (enrollment_status);

comment on table public.cohorts is 'P0#3 learner batches under one institution + course. Skill state is NOT stored here; skill_signals/skill_assessments remain the source of truth and are aggregated live.';
comment on table public.cohort_members is 'P0#3 cohort roster keyed by auth.users.id (canonical student id). History retained via enrollment_status; leaving a cohort withdraws, never hard-deletes.';
comment on column public.cohort_members.user_id is 'Canonical student identifier (auth.users.id = profiles.user_id). No second student table.';
