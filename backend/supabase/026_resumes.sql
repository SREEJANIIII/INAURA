-- INAURA Resume Builder
-- Structured, user-owned resume documents. Claims keep evidence anchors in JSONB so
-- the first version stays additive and can evolve without duplicating evidence tables.
create table if not exists public.resumes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 2 and 160),
  target_role text not null check (char_length(target_role) between 2 and 120),
  template text not null default 'classic' check (template in ('classic', 'modern', 'minimal')),
  content jsonb not null default '{}'::jsonb,
  claims jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_resumes on public.resumes;
create trigger set_updated_at_resumes before update on public.resumes
for each row execute function public.handle_updated_at();

alter table public.resumes enable row level security;
drop policy if exists "Users can manage own resumes" on public.resumes;
create policy "Users can manage own resumes" on public.resumes for all
using (auth.uid() = user_id) with check (auth.uid() = user_id);

grant select, insert, update, delete on public.resumes to authenticated, service_role;
create index if not exists idx_resumes_user_updated on public.resumes (user_id, updated_at desc);
