-- INAURA P1.5: curriculum proposal reviews — Migration 033
-- Table: curriculum_proposal_reviews (append-only human decision ledger)
--
-- Design (mirrors the application_events precedent from 027):
--   * One row per human decision; rows are never updated or deleted through
--     the API, so who/what/when/previous/new/reason is preserved forever.
--   * The proposal itself is NOT duplicated here: proposal_id plus a small
--     snapshot (district/role/course/skill/action) references the
--     deterministic P1.2 projection, which remains the evidence source.
--   * APPROVAL NEVER IMPLEMENTS: no trigger or policy touches curriculum
--     tables; course_skills/course_modules change only through existing
--     curriculum APIs, never as a side effect of a review row.
--
-- RLS: authenticated users may read all rows (governance transparency) and
-- insert only their own decisions (reviewer_id = auth.uid()). No
-- authenticated UPDATE/DELETE policies: history is append-only; writes
-- beyond that are service-role only. No cross-table subqueries: non-recursive.
-- Rollback: drop table if exists curriculum_proposal_reviews.

create table if not exists public.curriculum_proposal_reviews (
  id uuid primary key default gen_random_uuid(),
  proposal_id text not null check (char_length(proposal_id) between 1 and 120),
  district text not null check (char_length(district) between 1 and 200),
  role text not null check (char_length(role) between 1 and 150),
  course_id uuid references public.courses(id) on delete cascade,
  institution_id uuid references public.institutions(id) on delete cascade,
  skill_slug text,
  action_type text check (action_type in ('ADD_SKILL', 'INCREASE_COVERAGE', 'ADD_PRACTICAL_ASSESSMENT', 'UPDATE_MODULE', 'REVIEW_CONTENT') or action_type is null),
  reviewer_id uuid references auth.users(id) on delete set null,
  from_status text,
  to_status text not null check (to_status in ('APPROVED', 'REJECTED', 'DEFERRED')),
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists idx_proposal_reviews_proposal
  on public.curriculum_proposal_reviews (proposal_id, created_at desc);
create index if not exists idx_proposal_reviews_course
  on public.curriculum_proposal_reviews (course_id);
create index if not exists idx_proposal_reviews_reviewer
  on public.curriculum_proposal_reviews (reviewer_id);
create index if not exists idx_proposal_reviews_district
  on public.curriculum_proposal_reviews (district);

alter table public.curriculum_proposal_reviews enable row level security;

drop policy if exists "Authenticated can read proposal reviews"
  on public.curriculum_proposal_reviews;
create policy "Authenticated can read proposal reviews"
  on public.curriculum_proposal_reviews for select
  using (auth.uid() is not null);

drop policy if exists "Users can record own proposal decisions"
  on public.curriculum_proposal_reviews;
create policy "Users can record own proposal decisions"
  on public.curriculum_proposal_reviews for insert
  with check (auth.uid() is not null and reviewer_id = auth.uid());

revoke all on public.curriculum_proposal_reviews from anon, public;
grant select, insert on public.curriculum_proposal_reviews to authenticated;
grant select, insert, update, delete on public.curriculum_proposal_reviews to service_role;

comment on table public.curriculum_proposal_reviews is 'P1.5 append-only human decision ledger for P1.2 curriculum proposals. Approval records a decision only; it never mutates curriculum tables.';
comment on column public.curriculum_proposal_reviews.from_status is 'Previous decision for this proposal (NULL for the first decision, i.e. from PENDING_REVIEW).';
