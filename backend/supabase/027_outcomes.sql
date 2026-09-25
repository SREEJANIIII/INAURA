-- INAURA Person 2: Outcomes — Migration 027
-- Tables: applications (NO employer_id; employer derived via hiring_requirements),
-- application_events (append-only), employer_feedback (one per application),
-- employer_skill_feedback, qualification_alignments (optional evidence/cert grounding),
-- placement_outcomes.
-- Access: authenticated + service_role ONLY. No anon access.
-- Rollback (reverse order): drop table if exists placement_outcomes, qualification_alignments,
-- employer_skill_feedback, employer_feedback, application_events, applications.

create table if not exists public.applications (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references auth.users(id) on delete cascade,
  hiring_requirement_id uuid not null references public.hiring_requirements(id) on delete restrict,
  status text not null default 'saved' check (status in ('saved', 'applied', 'screening', 'interview', 'offer_received', 'selected', 'rejected', 'withdrawn')),
  outcome text check (outcome in ('pending', 'selected', 'rejected', 'withdrawn', 'declined_offer') or outcome is null),
  outcome_decided_at timestamptz,
  applied_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint applications_student_requirement_key unique (student_id, hiring_requirement_id)
);

create table if not exists public.application_events (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  from_status text,
  to_status text not null check (to_status in ('saved', 'applied', 'screening', 'interview', 'offer_received', 'selected', 'rejected', 'withdrawn')),
  actor uuid references auth.users(id) on delete set null,
  note text,
  created_at timestamptz not null default now()
);

create table if not exists public.employer_feedback (
  id uuid primary key default gen_random_uuid(),
  employer_id uuid not null references public.employers(id) on delete cascade,
  application_id uuid not null references public.applications(id) on delete cascade,
  student_id uuid not null references auth.users(id) on delete cascade,
  technical_ability smallint check (technical_ability is null or (technical_ability between 1 and 5)),
  communication smallint check (communication is null or (communication between 1 and 5)),
  problem_solving smallint check (problem_solving is null or (problem_solving between 1 and 5)),
  project_readiness smallint check (project_readiness is null or (project_readiness between 1 and 5)),
  role_readiness smallint check (role_readiness is null or (role_readiness between 1 and 5)),
  overall_rating smallint check (overall_rating is null or (overall_rating between 1 and 5)),
  interview_summary text,
  overall_comment text,
  status text not null default 'submitted' check (status in ('requested', 'submitted')),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint employer_feedback_application_key unique (application_id)
);

create table if not exists public.employer_skill_feedback (
  id uuid primary key default gen_random_uuid(),
  employer_feedback_id uuid not null references public.employer_feedback(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete restrict,
  expected_level numeric check (expected_level is null or (expected_level >= 0 and expected_level <= 1)),
  observed_level numeric check (observed_level is null or (observed_level >= 0 and observed_level <= 1)),
  comment text,
  created_at timestamptz not null default now(),
  constraint employer_skill_feedback_parent_skill_key unique (employer_feedback_id, skill_id)
);

create table if not exists public.qualification_alignments (
  id uuid primary key default gen_random_uuid(),
  hiring_requirement_id uuid not null references public.hiring_requirements(id) on delete cascade,
  course_name text not null check (char_length(course_name) between 2 and 200),
  qualification_name text,
  skill_id uuid references public.skills(id) on delete set null,
  coverage numeric check (coverage is null or (coverage >= 0 and coverage <= 1)),
  evidence_note text,
  evidence_id uuid references public.evidence(id) on delete set null,
  certification_id uuid references public.certifications(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint qualification_alignments_single_grounding check (
    not (evidence_id is not null and certification_id is not null)
  )
);

create table if not exists public.placement_outcomes (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references auth.users(id) on delete cascade,
  employer_id uuid not null references public.employers(id) on delete set null,
  application_id uuid references public.applications(id) on delete set null,
  role_title text not null check (char_length(role_title) between 2 and 200),
  location text,
  joining_date date,
  status text not null check (status in ('offer_accepted', 'selected', 'joined', 'declined', 'not_joined')),
  outcome_source text not null default 'student_reported' check (outcome_source in ('student_reported', 'employer_confirmed')),
  verification_status text not null default 'unverified' check (verification_status in ('unverified', 'verified', 'disputed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint placement_outcomes_application_key unique (application_id)
);

-- Updated-at triggers
drop trigger if exists set_updated_at on public.applications;
create trigger set_updated_at before update on public.applications
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at on public.employer_feedback;
create trigger set_updated_at before update on public.employer_feedback
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at on public.qualification_alignments;
create trigger set_updated_at before update on public.qualification_alignments
  for each row execute function public.handle_updated_at();

drop trigger if exists set_updated_at on public.placement_outcomes;
create trigger set_updated_at before update on public.placement_outcomes
  for each row execute function public.handle_updated_at();

-- Enable RLS
alter table public.applications enable row level security;
alter table public.application_events enable row level security;
alter table public.employer_feedback enable row level security;
alter table public.employer_skill_feedback enable row level security;
alter table public.qualification_alignments enable row level security;
alter table public.placement_outcomes enable row level security;

-- Applications: students own rows; employer members read via requirement join
drop policy if exists "Students manage own applications" on public.applications;
create policy "Students manage own applications"
  on public.applications for all
  using (auth.uid() is not null and student_id = auth.uid())
  with check (auth.uid() is not null and student_id = auth.uid());

drop policy if exists "Employer members view applications" on public.applications;
create policy "Employer members view applications"
  on public.applications for select
  using (
    auth.uid() is not null and exists (
      select 1 from public.hiring_requirements hr
      join public.employer_members m on m.employer_id = hr.employer_id
      where hr.id = applications.hiring_requirement_id and m.user_id = auth.uid()
    )
  );

-- Application events: read if own app or member; insert if own app or member; no update/delete
drop policy if exists "Read application events" on public.application_events;
create policy "Read application events"
  on public.application_events for select
  using (
    auth.uid() is not null and (
      exists (select 1 from public.applications a where a.id = application_events.application_id and a.student_id = auth.uid())
      or exists (
        select 1 from public.applications a
        join public.hiring_requirements hr on hr.id = a.hiring_requirement_id
        join public.employer_members m on m.employer_id = hr.employer_id
        where a.id = application_events.application_id and m.user_id = auth.uid()
      )
    )
  );

drop policy if exists "Append application events" on public.application_events;
create policy "Append application events"
  on public.application_events for insert
  with check (
    auth.uid() is not null and (
      exists (select 1 from public.applications a where a.id = application_events.application_id and a.student_id = auth.uid())
      or exists (
        select 1 from public.applications a
        join public.hiring_requirements hr on hr.id = a.hiring_requirement_id
        join public.employer_members m on m.employer_id = hr.employer_id
        where a.id = application_events.application_id and m.user_id = auth.uid()
      )
    )
  );

-- Employer feedback: members insert/select own employer; students select own
drop policy if exists "Employer members manage feedback" on public.employer_feedback;
create policy "Employer members manage feedback"
  on public.employer_feedback for all
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = employer_feedback.employer_id and m.user_id = auth.uid()
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = employer_feedback.employer_id and m.user_id = auth.uid()
    )
  );

drop policy if exists "Students view own feedback" on public.employer_feedback;
create policy "Students view own feedback"
  on public.employer_feedback for select
  using (auth.uid() is not null and student_id = auth.uid());

-- Employer skill feedback: via parent feedback visibility
drop policy if exists "Read skill feedback via parent" on public.employer_skill_feedback;
create policy "Read skill feedback via parent"
  on public.employer_skill_feedback for select
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_feedback f
      left join public.employer_members m on m.employer_id = f.employer_id and m.user_id = auth.uid()
      where f.id = employer_skill_feedback.employer_feedback_id
        and (f.student_id = auth.uid() or m.user_id = auth.uid())
    )
  );

drop policy if exists "Members insert skill feedback" on public.employer_skill_feedback;
create policy "Members insert skill feedback"
  on public.employer_skill_feedback for insert
  with check (
    auth.uid() is not null and exists (
      select 1 from public.employer_feedback f
      join public.employer_members m on m.employer_id = f.employer_id
      where f.id = employer_skill_feedback.employer_feedback_id and m.user_id = auth.uid()
    )
  );

-- Qualification alignments: members manage; students with an application read
drop policy if exists "Members manage alignments" on public.qualification_alignments;
create policy "Members manage alignments"
  on public.qualification_alignments for all
  using (
    auth.uid() is not null and exists (
      select 1 from public.hiring_requirements hr
      join public.employer_members m on m.employer_id = hr.employer_id
      where hr.id = qualification_alignments.hiring_requirement_id and m.user_id = auth.uid()
    )
  )
  with check (
    auth.uid() is not null and exists (
      select 1 from public.hiring_requirements hr
      join public.employer_members m on m.employer_id = hr.employer_id
      where hr.id = qualification_alignments.hiring_requirement_id and m.user_id = auth.uid()
    )
  );

drop policy if exists "Applicants view alignments" on public.qualification_alignments;
create policy "Applicants view alignments"
  on public.qualification_alignments for select
  using (
    auth.uid() is not null and exists (
      select 1 from public.applications a
      where a.hiring_requirement_id = qualification_alignments.hiring_requirement_id
        and a.student_id = auth.uid()
    )
  );

-- Placement outcomes: students own; members read own employer
drop policy if exists "Students manage own placements" on public.placement_outcomes;
create policy "Students manage own placements"
  on public.placement_outcomes for all
  using (auth.uid() is not null and student_id = auth.uid())
  with check (auth.uid() is not null and student_id = auth.uid());

drop policy if exists "Employer members view placements" on public.placement_outcomes;
create policy "Employer members view placements"
  on public.placement_outcomes for select
  using (
    auth.uid() is not null and exists (
      select 1 from public.employer_members m
      where m.employer_id = placement_outcomes.employer_id and m.user_id = auth.uid()
    )
  );

-- Grants: authenticated + service_role ONLY. Explicitly revoke anon/PUBLIC.
revoke all on public.applications from anon, public;
revoke all on public.application_events from anon, public;
revoke all on public.employer_feedback from anon, public;
revoke all on public.employer_skill_feedback from anon, public;
revoke all on public.qualification_alignments from anon, public;
revoke all on public.placement_outcomes from anon, public;
grant select, insert, update, delete on public.applications to authenticated, service_role;
grant select, insert on public.application_events to authenticated, service_role;
grant select, insert, update, delete on public.employer_feedback to authenticated, service_role;
grant select, insert on public.employer_skill_feedback to authenticated, service_role;
grant select, insert, update, delete on public.qualification_alignments to authenticated, service_role;
grant select, insert, update, delete on public.placement_outcomes to authenticated, service_role;

-- Indexes
create index if not exists idx_apps_student on public.applications (student_id);
create index if not exists idx_apps_requirement on public.applications (hiring_requirement_id);
create index if not exists idx_apps_status on public.applications (status);
create index if not exists idx_apps_applied_at on public.applications (applied_at);
create index if not exists idx_appevents_app_created on public.application_events (application_id, created_at);
create index if not exists idx_efb_app on public.employer_feedback (application_id);
create index if not exists idx_efb_employer on public.employer_feedback (employer_id);
create index if not exists idx_efb_student on public.employer_feedback (student_id);
create index if not exists idx_esfb_feedback on public.employer_skill_feedback (employer_feedback_id);
create index if not exists idx_esfb_skill on public.employer_skill_feedback (skill_id);
create index if not exists idx_qalign_req on public.qualification_alignments (hiring_requirement_id);
create index if not exists idx_qalign_skill on public.qualification_alignments (skill_id);
create index if not exists idx_place_student on public.placement_outcomes (student_id);
create index if not exists idx_place_employer on public.placement_outcomes (employer_id);

comment on table public.applications is 'Person 2: student application. No employer_id column; employer derived via hiring_requirements join (3NF). Status vs outcome separated.';
comment on table public.application_events is 'Person 2: append-only application history. No UPDATE/DELETE. applications.status caches latest event.';
comment on table public.employer_feedback is 'Person 2: one summative feedback per application (UNIQUE application_id). Independent signal; never written into skill_assessments/gaps.';
comment on table public.employer_skill_feedback is 'Person 2: per-skill employer-observed vs expected levels, FK skills.id. Independent signal.';
comment on table public.qualification_alignments is 'Person 2: requirement to course/qualification label edge. Optional grounding to own evidence/certification row only; not a qualification registry.';
comment on table public.placement_outcomes is 'Person 2: post-offer truth (selected/joined). Minimal PII: no salary/phone/address.';
