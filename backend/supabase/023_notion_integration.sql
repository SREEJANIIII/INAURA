-- INAURA Notion OAuth Integration — Migration 023
-- Secure server-side OAuth token storage, page sync tracking, and evidence layer integration

-- 1. Integration authorization table (tokens encrypted at rest)
create table if not exists public.user_integrations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null, -- 'notion'
  access_token_encrypted text not null,
  workspace_id text,
  workspace_name text,
  workspace_icon text,
  bot_id text,
  owner_user_id text,
  owner_user_name text,
  owner_user_email text,
  status text not null default 'connected' check (status in ('connected', 'disconnected', 'revoked', 'reconnect_required')),
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_integrations_user_provider_key unique (user_id, provider)
);

-- 2. Raw synchronized Notion pages (separate from canonical evidence layer)
create table if not exists public.notion_synced_pages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  page_id text not null,
  page_title text,
  page_url text,
  last_edited_time timestamptz,
  content_summary text,
  extracted_evidence jsonb default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint notion_synced_pages_user_page_key unique (user_id, page_id)
);

-- 3. Extend evidence table check constraint to support 'notion' evidence_type
do $$
begin
  -- Drop existing constraint if present and recreate with 'notion'
  if exists (
    select 1 from information_schema.table_constraints
    where constraint_name = 'evidence_evidence_type_check'
      and table_name = 'evidence'
  ) then
    alter table public.evidence drop constraint evidence_evidence_type_check;
  end if;

  alter table public.evidence add constraint evidence_evidence_type_check check (
    evidence_type in (
      'github','leetcode','codeforces','kaggle','linkedin',
      'resume','syllabus','certification_file','project_doc','notion'
    )
  );
exception
  when others then
    -- Table might not have named constraint or already updated
    null;
end $$;

-- 4. Enable Row Level Security
alter table public.user_integrations enable row level security;
alter table public.notion_synced_pages enable row level security;

-- Policies for user_integrations
drop policy if exists "Users can manage own integrations" on public.user_integrations;
create policy "Users can manage own integrations"
  on public.user_integrations for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Policies for notion_synced_pages
drop policy if exists "Users can manage own notion synced pages" on public.notion_synced_pages;
create policy "Users can manage own notion synced pages"
  on public.notion_synced_pages for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 5. Grants
grant select, insert, update, delete on public.user_integrations to anon, authenticated, service_role;
grant select, insert, update, delete on public.notion_synced_pages to anon, authenticated, service_role;

-- 6. Indexes
create index if not exists idx_user_integrations_user_provider on public.user_integrations (user_id, provider);
create index if not exists idx_notion_synced_pages_user on public.notion_synced_pages (user_id);
create index if not exists idx_notion_synced_pages_page_id on public.notion_synced_pages (page_id);

comment on table public.user_integrations is 'OAuth integration metadata and tokens (encrypted at rest) for third-party platforms like Notion.';
comment on table public.notion_synced_pages is 'Raw synchronized pages and extracted evidence records from authorized Notion workspaces.';
