-- INAURA Evidence Collection — Phase 4A
-- Run in Supabase SQL Editor after 001_create_profiles.sql
-- Stores URL evidence, file references, projects, certifications

-- 1. Generic evidence (URLs + file metadata)
create table if not exists public.evidence (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  evidence_type text not null check (evidence_type in (
    'github','leetcode','codeforces','kaggle','linkedin',
    'resume','syllabus','certification_file','project_doc'
  )),
  source_url text,
  file_path text,
  title text,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 2. Projects (manual)
create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 120),
  description text not null check (char_length(description) between 10 and 800),
  technologies text[] not null default '{}',
  project_url text,
  github_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 3. Certifications (manual)
create table if not exists public.certifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 150),
  issuing_org text not null check (char_length(issuing_org) between 2 and 120),
  completion_year int not null check (completion_year between 2000 and 2035),
  certificate_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Updated_at triggers (reuse handle_updated_at from 001)
drop trigger if exists set_updated_at_evidence on public.evidence;
create trigger set_updated_at_evidence
  before update on public.evidence
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at_projects on public.projects;
create trigger set_updated_at_projects
  before update on public.projects
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at_certs on public.certifications;
create trigger set_updated_at_certs
  before update on public.certifications
  for each row execute function public.handle_updated_at();

-- RLS
alter table public.evidence enable row level security;
alter table public.projects enable row level security;
alter table public.certifications enable row level security;

-- Evidence policies
drop policy if exists "Users can manage own evidence" on public.evidence;
create policy "Users can manage own evidence"
  on public.evidence for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Projects policies
drop policy if exists "Users can manage own projects" on public.projects;
create policy "Users can manage own projects"
  on public.projects for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Certifications policies
drop policy if exists "Users can manage own certifications" on public.certifications;
create policy "Users can manage own certifications"
  on public.certifications for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Grants
grant select, insert, update, delete on public.evidence to anon, authenticated, service_role;
grant select, insert, update, delete on public.projects to anon, authenticated, service_role;
grant select, insert, update, delete on public.certifications to anon, authenticated, service_role;

-- Indexes
create index if not exists idx_evidence_user_type on public.evidence (user_id, evidence_type);
create index if not exists idx_projects_user on public.projects (user_id);
create index if not exists idx_certs_user on public.certifications (user_id);

-- Storage bucket for file evidence (private)
insert into storage.buckets (id, name, public)
values ('user-evidence', 'user-evidence', false)
on conflict (id) do nothing;

-- Storage policies — users can only access their own folder: user_id/...
-- Note: storage.objects RLS is separate; these assume bucket is private
do $$
begin
  -- Allow authenticated to upload to own folder
  if not exists (select 1 from pg_policies where policyname = 'Users can upload own evidence' and tablename = 'objects') then
    create policy "Users can upload own evidence"
      on storage.objects for insert
      with check (
        bucket_id = 'user-evidence'
        and auth.role() = 'authenticated'
        and (storage.foldername(name))[1] = auth.uid()::text
      );
  end if;

  if not exists (select 1 from pg_policies where policyname = 'Users can view own evidence' and tablename = 'objects') then
    create policy "Users can view own evidence"
      on storage.objects for select
      using (
        bucket_id = 'user-evidence'
        and auth.uid()::text = (storage.foldername(name))[1]
      );
  end if;

  if not exists (select 1 from pg_policies where policyname = 'Users can update own evidence' and tablename = 'objects') then
    create policy "Users can update own evidence"
      on storage.objects for update
      using (
        bucket_id = 'user-evidence'
        and auth.uid()::text = (storage.foldername(name))[1]
      );
  end if;

  if not exists (select 1 from pg_policies where policyname = 'Users can delete own evidence' and tablename = 'objects') then
    create policy "Users can delete own evidence"
      on storage.objects for delete
      using (
        bucket_id = 'user-evidence'
        and auth.uid()::text = (storage.foldername(name))[1]
      );
  end if;
end $$;

-- Ensure service_role bypasses storage RLS (default), but grant usage
grant select, insert, update, delete on storage.objects to service_role;

comment on table public.evidence is 'Phase 4A — URL + file evidence, 9 sources, optional. user_id FK, RLS isolated.';
comment on table public.projects is 'Phase 4A — manual projects, future analysis will consume.';
comment on table public.certifications is 'Phase 4A — manual certifications.';
