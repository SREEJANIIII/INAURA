-- INAURA Notion per-page include/exclude — Migration 025
-- Lets users exclude copied / future-learning notes from career-readiness
-- scoring while keeping them visible as study links. Raw page + evidence rows
-- are preserved; scoring exclusion rides on the same is_excluded pattern used
-- by public.evidence (013), which signal_extractor already skips.

alter table public.notion_synced_pages
  add column if not exists is_excluded boolean not null default false;

create index if not exists idx_notion_synced_pages_user_excluded
  on public.notion_synced_pages (user_id, is_excluded);

comment on column public.notion_synced_pages.is_excluded is 'User excluded this Notion page from scoring (e.g. copied notes for future learning); raw page preserved, signals inactive.';
