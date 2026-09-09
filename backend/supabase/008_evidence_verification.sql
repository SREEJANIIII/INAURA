-- INAURA Evidence Intelligence — Phase 5
-- Run in Supabase SQL Editor after 007_canonical_skills.sql
-- Adds verification status, verification message, verified_at, and provider tracking to evidence

do $$
begin
  -- 1. verification_status column
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='verification_status') then
    alter table public.evidence add column verification_status text not null default 'unverified' check (verification_status in ('unverified', 'verified', 'failed'));
  end if;

  -- 2. verification_message column
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='verification_message') then
    alter table public.evidence add column verification_message text;
  end if;

  -- 3. verified_at column
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='verified_at') then
    alter table public.evidence add column verified_at timestamptz;
  end if;

  -- 4. provider column
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='evidence' and column_name='provider') then
    alter table public.evidence add column provider text;
  end if;
end $$;

-- Add index for fast querying of verified evidence per user
create index if not exists idx_evidence_user_verification on public.evidence (user_id, verification_status);

comment on column public.evidence.verification_status is 'Evidence Intelligence verification status: unverified (submitted only), verified (independently inspected), failed (unavailable/private/error)';
comment on column public.evidence.verification_message is 'Summary of verification outcome or reason for failure';
comment on column public.evidence.verified_at is 'Timestamp when verification occurred';
comment on column public.evidence.provider is 'Name of provider that verified the evidence, e.g., github';
