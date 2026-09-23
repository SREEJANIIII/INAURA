-- INAURA Notion Sync Fix — Migration 024
-- The sync orchestrator (app/services/notion_service.py) persists rich per-page
-- metadata (skills, headings, code_languages, word_count) but 023 never created
-- those columns. Every live-Supabase upsert therefore failed with:
--   column notion_synced_pages.<col> does not exist (42703)
-- The failure was swallowed at debug level and only the ephemeral in-memory
-- fallback was populated, so sync looked successful in-process but status/pages
-- returned 0 rows on the next request / restart / worker. This migration adds
-- the missing columns so persistence succeeds.

alter table public.notion_synced_pages
  add column if not exists skills jsonb not null default '[]'::jsonb;

alter table public.notion_synced_pages
  add column if not exists headings jsonb not null default '[]'::jsonb;

alter table public.notion_synced_pages
  add column if not exists code_languages jsonb not null default '[]'::jsonb;

alter table public.notion_synced_pages
  add column if not exists word_count integer not null default 0;

create index if not exists idx_notion_synced_pages_user_edited
  on public.notion_synced_pages (user_id, last_edited_time desc);

comment on column public.notion_synced_pages.skills is 'Canonical skill names detected on this page (jsonb list).';
comment on column public.notion_synced_pages.headings is 'Top headings extracted from page blocks (jsonb list, max 6).';
comment on column public.notion_synced_pages.code_languages is 'Programming languages seen in code blocks (jsonb list).';
comment on column public.notion_synced_pages.word_count is 'Word count of extracted page text.';
