-- INAURA Person 2: Employers — Migration 026
-- Tables: employers, employer_members, hiring_requirements, hiring_requirement_skills
-- Sensitive employer/hiring data: authenticated + service_role ONLY. No anon access.
-- Rollback (reverse order): drop table if exists hiring_requirement_skills, hiring_requirements, employer_members, employers.

create table if not exists public.employers (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 200),
  description text,
  industry text,
  website text,
  location text,
  contact_email text,
  status text not null default 'active' check (status in ('active', 'suspended', 'archived')),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.employer_members (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null references public.employers(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  constraint employer_members_employer_user_key unique (employer_id, user_id)
);

create table if not exists public.hiring_requirements (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null references public.employers(id) on delete cascade,
  title text not null check (char_length(title) between 2 and 200),
  role_key text,
  location text,
  employment_type text check (employment_type in ('full_time', 'part_time', 'internship', 'contract', 'apprenticeship') or employment_type is null),
  description text,
  experience_min_years numeric check (experience_min_years is null or experience_min_years >= 0),
  qualification_text text,
  status text not null default 'open' check (status in ('draft', 'open', 'paused', 'closed')),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.hiring_requirement_skills (
  id uuid primary key default gen_random_uuid(),
  hiring_requirement_id uuid not null references public.hiring_requirements(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete restrict,
  importance text not null check (importance in ('required', 'preferred')),
  required_level numeric check (required_level is null or (required_level >= 0 and required_level <= 1)),
  note text,
  created_at timestamptz not null default now(),
  constraint hiring_requirement_skills_req_skill_key unique (hiring_requirement_id, skill_id)
);

-- Updated-at triggers (reuse handle_updated_at from 001)
drop trigger if exists set_updated_at on public.employers;
create trigger set_updated_at before update on public.employers
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at on public.hiring_requirements;
create trigger set_updated_at before update on public.hiring_requirements
  for each row execute function public.handle_updated_at();

-- Enable RLS
alter table public.employers enable row level security;
alter table public.employer_members enable row level security;
alter table public.hiring_requirements enable row level security;
alter table public.hiring_requirement_skills enable row level security;

-- Employers policies (members + creator only, no anon)
drop policy if exists "Members can view employers" on public.employers;
create policy "Members can view employers"
  on public.employers for select
  using (
    auth.uid() is not null and (
      created_by = auth.uid()
      or exists (select 1 from public.employer_members m where m.employer_id = employers.id and m.user_id = auth.uid())
    )
  );

drop policy if exists "Users can create employers" on public.employers;
create policy "Users can create employers"
  on public.employers for insert
  with check (auth.uid() is not null and created_by = auth.uid());

drop policy if exists "Owners can update employers" on public.employers;
create policy "Owners can update employers"
  on public.employers for update
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = employers.id and m.user_id = auth.uid() and m.role = 'owner'
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = employers.id and m.user_id = auth.uid() and m.role = 'owner'
    )
  );

drop policy if exists "Owners can delete employers" on public.employers;
create policy "Owners can delete employers"
  on public.employers for delete
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = employers.id and m.user_id = auth.uid() and m.role = 'owner'
    )
  );

-- Employer members policies
drop policy if exists "Users can view own memberships" on public.employer_members;
create policy "Users can view own memberships"
  on public.employer_members for select
  using (auth.uid() is not null and user_id = auth.uid());

drop policy if exists "Users can bootstrap own membership" on public.employer_members;
create policy "Users can bootstrap own membership"
  on public.employer_members for insert
  with check (auth.uid() is not null and user_id = auth.uid());

drop policy if exists "Owners can manage memberships" on public.employer_members;
create policy "Owners can manage memberships"
  on public.employer_members for all
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members o
      where o.employer_id = employer_members.employer_id and o.user_id = auth.uid() and o.role = 'owner'
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.employer_members o
      where o.employer_id = employer_members.employer_id and o.user_id = auth.uid() and o.role = 'owner'
    )
  );

-- Hiring requirements policies (employer members only)
drop policy if exists "Members manage hiring requirements" on public.hiring_requirements;
create policy "Members manage hiring requirements"
  on public.hiring_requirements for all
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = hiring_requirements.employer_id and m.user_id = auth.uid()
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = hiring_requirements.employer_id and m.user_id = auth.uid()
    )
  );

-- Hiring requirement skills policies (via parent requirement membership)
drop policy if exists "Members manage requirement skills" on public.hiring_requirement_skills;
create policy "Members manage requirement skills"
  on public.hiring_requirement_skills for all
  using (
    auth.uid() is not null and exists (
      select 1 from public.hiring_requirements hr
      join public.employer_members m on m.employer_id = hr.employer_id
      where hr.id = hiring_requirement_skills.hiring_requirement_id and m.user_id = auth.uid()
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.hiring_requirements hr
      join public.employer_members m on m.employer_id = hr.employer_id
      where hr.id = hiring_requirement_skills.hiring_requirement_id and m.user_id = auth.uid()
    )
  );

-- Grants: authenticated + service_role ONLY. Explicitly revoke anon/PUBLIC.
revoke all on public.employers from anon, public;
revoke all on public.employer_members from anon, public;
revoke all on public.hiring_requirements from anon, public;
revoke all on public.hiring_requirement_skills from anon, public;
grant select, insert, update, delete on public.employers to authenticated, service_role;
grant select, insert, update, delete on public.employer_members to authenticated, service_role;
grant select, insert, update, delete on public.hiring_requirements to authenticated, service_role;
grant select, insert, update, delete on public.hiring_requirement_skills to authenticated, service_role;

-- Indexes
create index if not exists idx_employers_created_by on public.employers (created_by);
create index if not exists idx_employers_status on public.employers (status);
create index if not exists idx_employer_members_user on public.employer_members (user_id);
create index if not exists idx_employer_members_employer on public.employer_members (employer_id);
create index if not exists idx_hreq_employer on public.hiring_requirements (employer_id);
create index if not exists idx_hreq_status on public.hiring_requirements (status);
create index if not exists idx_hreq_role_key on public.hiring_requirements (role_key);
create index if not exists idx_hrskills_req on public.hiring_requirement_skills (hiring_requirement_id);
create index if not exists idx_hrskills_skill on public.hiring_requirement_skills (skill_id);

comment on table public.employers is 'Person 2: employer identity. Members-only read; contact_email never exposed to non-members.';
comment on table public.employer_members is 'Person 2: employer ownership/auth (owner/member). Only employer auth table.';
comment on table public.hiring_requirements is 'Person 2: employer role posting. Skills in hiring_requirement_skills FK skills.id; role_key is free-text industry role link, not a duplicate of industry_requirements.';
comment on table public.hiring_requirement_skills is 'Person 2: normalized requirement skills referencing canonical skills.id (required/preferred).';
