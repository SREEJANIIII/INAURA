-- INAURA 015 — Per-Repository Personalization for GitHub Evidence
-- Each discovered repository gets independent included/excluded and AI-assisted state
-- Defaults: included=true (is_excluded=false), ai_assisted=false

create table if not exists public.user_github_repo_settings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  repo_full_name text not null, -- e.g. owner/repo lowercased
  repo_url text,
  is_excluded boolean not null default false,
  is_ai_assisted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, repo_full_name)
);

drop trigger if exists set_updated_at_github_repo_settings on public.user_github_repo_settings;
create trigger set_updated_at_github_repo_settings
  before update on public.user_github_repo_settings
  for each row execute function public.handle_updated_at();

alter table public.user_github_repo_settings enable row level security;
drop policy if exists "Users can manage own repo settings" on public.user_github_repo_settings;
create policy "Users can manage own repo settings"
  on public.user_github_repo_settings for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

grant select, insert, update, delete on public.user_github_repo_settings to authenticated, service_role;

create index if not exists idx_repo_settings_user on public.user_github_repo_settings (user_id);
create index if not exists idx_repo_settings_repo on public.user_github_repo_settings (repo_full_name);

comment on table public.user_github_repo_settings is 'Per-repository personalization: each GitHub repository has independent included/excluded and AI-assisted state. Defaults: included (is_excluded=false), not AI-assisted. Raw evidence preserved. Prototype heuristic adjustment for AI-assisted.';
comment on column public.user_github_repo_settings.is_excluded is 'When true, repository evidence does not contribute to active skill calculation';
comment on column public.user_github_repo_settings.is_ai_assisted is 'When true, repository contribution reduced via reliability (centralized heuristic, not zeroed)';
