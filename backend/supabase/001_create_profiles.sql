-- INAURA profiles table — Phase 3
-- Run in Supabase SQL Editor or via CLI: supabase db push
-- Requires auth.users from Supabase Auth

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null check (char_length(full_name) >= 2),
  college text not null check (char_length(college) >= 2),
  degree text not null,
  branch text not null,
  current_year text not null,
  graduation_year int not null check (graduation_year between 2000 and 2035),
  career_interests text[] not null default '{}',
  hours_per_week int not null check (hours_per_week between 1 and 80),
  profile_completed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Updated_at trigger
create or replace function public.handle_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists set_updated_at on public.profiles;
create trigger set_updated_at
  before update on public.profiles
  for each row execute function public.handle_updated_at();

-- Enable RLS
alter table public.profiles enable row level security;

-- Policies: users can read/update only their own row
drop policy if exists "Users can view own profile" on public.profiles;
create policy "Users can view own profile"
  on public.profiles for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own profile" on public.profiles;
create policy "Users can insert own profile"
  on public.profiles for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own profile" on public.profiles;
create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Grant privileges — REQUIRED for anon/authenticated/service_role to access via PostgREST
-- Without these, you get "permission denied for table profiles"
grant select, insert, update, delete on public.profiles to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;

-- Optional: allow service_role full access (already bypasses RLS)

-- Index for future queries
create index if not exists idx_profiles_graduation_year on public.profiles (graduation_year);

-- Comment for future expansion
comment on table public.profiles is 'INAURA user onboarding — Phase 3. Future tables: evidence, skills, career_goals, skill_gaps, roadmaps, roadmap_progress, industry_requirements will reference user_id.';

