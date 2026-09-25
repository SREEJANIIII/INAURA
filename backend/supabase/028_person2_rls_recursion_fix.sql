-- INAURA Person 2: fix RLS infinite recursion — Migration 028
--
-- Defect found during live verification: 026/027 RLS policies query
-- public.employer_members from policies ON public.employer_members itself
-- ("Owners can manage memberships" FOR ALL ... EXISTS (SELECT ... FROM
-- employer_members ...)), and every child-table policy subqueries
-- employer_members too. Postgres aborts ALL authenticated/anon access to
-- Person 2 tables with 42P17 "infinite recursion detected in policy".
--
-- Fix: SECURITY DEFINER lookup functions (execute with table-owner rights,
-- bypass RLS, so no policy re-entry) + rewrite every policy that touched
-- employer_members to call the functions instead of subquerying it.
-- No table, column, constraint, or grant changes. Additive + re-runnable.
--
-- Rollback: re-apply backend/supabase/026_employers.sql and 027_outcomes.sql
-- (restores the recursive policies; only useful to reproduce the defect).

-- 1. Lookup functions (auth.uid() still returns the querying user inside
-- SECURITY DEFINER; only table access is elevated, so no policy re-entry).
create or replace function public.employer_role_of(p_employer_id uuid)
returns text
language sql
security definer
set search_path = public
as $$
  select m.role
  from public.employer_members m
  where m.employer_id = p_employer_id
    and m.user_id = auth.uid()
  limit 1;
$$;

create or replace function public.req_employer_role(p_requirement_id uuid)
returns text
language sql
security definer
set search_path = public
as $$
  select m.role
  from public.hiring_requirements hr
  join public.employer_members m on m.employer_id = hr.employer_id
  where hr.id = p_requirement_id
    and m.user_id = auth.uid()
  limit 1;
$$;

create or replace function public.app_employer_role(p_application_id uuid)
returns text
language sql
security definer
set search_path = public
as $$
  select m.role
  from public.applications a
  join public.hiring_requirements hr on hr.id = a.hiring_requirement_id
  join public.employer_members m on m.employer_id = hr.employer_id
  where a.id = p_application_id
    and m.user_id = auth.uid()
  limit 1;
$$;

create or replace function public.feedback_employer_role(p_feedback_id uuid)
returns text
language sql
security definer
set search_path = public
as $$
  select m.role
  from public.employer_feedback f
  join public.employer_members m on m.employer_id = f.employer_id
  where f.id = p_feedback_id
    and m.user_id = auth.uid()
  limit 1;
$$;

-- Functions: authenticated + service_role only, never anon/PUBLIC.
revoke all on function public.employer_role_of(uuid) from anon, public;
revoke all on function public.req_employer_role(uuid) from anon, public;
revoke all on function public.app_employer_role(uuid) from anon, public;
revoke all on function public.feedback_employer_role(uuid) from anon, public;
grant execute on function public.employer_role_of(uuid) to authenticated, service_role;
grant execute on function public.req_employer_role(uuid) to authenticated, service_role;
grant execute on function public.app_employer_role(uuid) to authenticated, service_role;
grant execute on function public.feedback_employer_role(uuid) to authenticated, service_role;

-- 2. employers — same semantics, recursion-free
drop policy if exists "Members can view employers" on public.employers;
drop policy if exists "Users can create employers" on public.employers;
drop policy if exists "Owners can update employers" on public.employers;
drop policy if exists "Owners can delete employers" on public.employers;

create policy "Members can view employers"
  on public.employers for select
  using (
    auth.uid() is not null and (
      created_by = auth.uid()
      or public.employer_role_of(id) is not null
    )
  );

create policy "Users can create employers"
  on public.employers for insert
  with check (auth.uid() is not null and created_by = auth.uid());

create policy "Owners can update employers"
  on public.employers for update
  using (public.employer_role_of(id) = 'owner')
  with check (public.employer_role_of(id) = 'owner');

create policy "Owners can delete employers"
  on public.employers for delete
  using (public.employer_role_of(id) = 'owner');

-- 3. employer_members — split per command, no self-subquery
drop policy if exists "Users can view own memberships" on public.employer_members;
drop policy if exists "Users can bootstrap own membership" on public.employer_members;
drop policy if exists "Owners can manage memberships" on public.employer_members;

create policy "Members can view memberships"
  on public.employer_members for select
  using (
    auth.uid() is not null and (
      user_id = auth.uid()
      or public.employer_role_of(employer_id) = 'owner'
    )
  );

create policy "Users can bootstrap own membership"
  on public.employer_members for insert
  with check (
    auth.uid() is not null and (
      user_id = auth.uid()
      or public.employer_role_of(employer_id) = 'owner'
    )
  );

create policy "Owners can update memberships"
  on public.employer_members for update
  using (public.employer_role_of(employer_id) = 'owner')
  with check (public.employer_role_of(employer_id) = 'owner');

create policy "Owners can delete memberships"
  on public.employer_members for delete
  using (public.employer_role_of(employer_id) = 'owner');

-- 4. hiring_requirements — membership via function
drop policy if exists "Members manage hiring requirements" on public.hiring_requirements;
create policy "Members manage hiring requirements"
  on public.hiring_requirements for all
  using (
    auth.uid() is not null
    and public.employer_role_of(employer_id) is not null
  )
  with check (
    auth.uid() is not null
    and public.employer_role_of(employer_id) is not null
  );

-- 5. hiring_requirement_skills — membership via requirement
drop policy if exists "Members manage requirement skills" on public.hiring_requirement_skills;
create policy "Members manage requirement skills"
  on public.hiring_requirement_skills for all
  using (
    auth.uid() is not null
    and public.req_employer_role(hiring_requirement_id) is not null
  )
  with check (
    auth.uid() is not null
    and public.req_employer_role(hiring_requirement_id) is not null
  );

-- 6. applications — student ownership unchanged; member read via function
drop policy if exists "Students manage own applications" on public.applications;
drop policy if exists "Employer members view applications" on public.applications;

create policy "Students manage own applications"
  on public.applications for all
  using (auth.uid() is not null and student_id = auth.uid())
  with check (auth.uid() is not null and student_id = auth.uid());

create policy "Employer members view applications"
  on public.applications for select
  using (
    auth.uid() is not null
    and public.req_employer_role(hiring_requirement_id) is not null
  );

-- 7. application_events — append-only; member access via function
drop policy if exists "Read application events" on public.application_events;
drop policy if exists "Append application events" on public.application_events;

create policy "Read application events"
  on public.application_events for select
  using (
    auth.uid() is not null and (
      exists (
        select 1 from public.applications a
        where a.id = application_events.application_id
          and a.student_id = auth.uid()
      )
      or public.app_employer_role(application_id) is not null
    )
  );

create policy "Append application events"
  on public.application_events for insert
  with check (
    auth.uid() is not null and (
      exists (
        select 1 from public.applications a
        where a.id = application_events.application_id
          and a.student_id = auth.uid()
      )
      or public.app_employer_role(application_id) is not null
    )
  );

-- 8. employer_feedback — member access via function; student read unchanged
drop policy if exists "Employer members manage feedback" on public.employer_feedback;
drop policy if exists "Students view own feedback" on public.employer_feedback;

create policy "Employer members manage feedback"
  on public.employer_feedback for all
  using (
    auth.uid() is not null
    and public.employer_role_of(employer_id) is not null
  )
  with check (
    auth.uid() is not null
    and public.employer_role_of(employer_id) is not null
  );

create policy "Students view own feedback"
  on public.employer_feedback for select
  using (auth.uid() is not null and student_id = auth.uid());

-- 9. employer_skill_feedback — parent access via function
drop policy if exists "Read skill feedback via parent" on public.employer_skill_feedback;
drop policy if exists "Members insert skill feedback" on public.employer_skill_feedback;

create policy "Read skill feedback via parent"
  on public.employer_skill_feedback for select
  using (
    auth.uid() is not null and (
      exists (
        select 1 from public.employer_feedback f
        where f.id = employer_skill_feedback.employer_feedback_id
          and f.student_id = auth.uid()
      )
      or public.feedback_employer_role(employer_feedback_id) is not null
    )
  );

create policy "Members insert skill feedback"
  on public.employer_skill_feedback for insert
  with check (
    auth.uid() is not null
    and public.feedback_employer_role(employer_feedback_id) is not null
  );

-- 10. qualification_alignments — member access via function; applicant read unchanged
drop policy if exists "Members manage alignments" on public.qualification_alignments;
drop policy if exists "Applicants view alignments" on public.qualification_alignments;

create policy "Members manage alignments"
  on public.qualification_alignments for all
  using (
    auth.uid() is not null
    and public.req_employer_role(hiring_requirement_id) is not null
  )
  with check (
    auth.uid() is not null
    and public.req_employer_role(hiring_requirement_id) is not null
  );

create policy "Applicants view alignments"
  on public.qualification_alignments for select
  using (
    auth.uid() is not null and exists (
      select 1 from public.applications a
      where a.hiring_requirement_id = qualification_alignments.hiring_requirement_id
        and a.student_id = auth.uid()
    )
  );

-- 11. placement_outcomes — student ownership unchanged; member read via function
drop policy if exists "Students manage own placements" on public.placement_outcomes;
drop policy if exists "Employer members view placements" on public.placement_outcomes;

create policy "Students manage own placements"
  on public.placement_outcomes for all
  using (auth.uid() is not null and student_id = auth.uid())
  with check (auth.uid() is not null and student_id = auth.uid());

create policy "Employer members view placements"
  on public.placement_outcomes for select
  using (
    auth.uid() is not null
    and public.employer_role_of(employer_id) is not null
  );

-- Re-assert table grants (idempotent; anon/PUBLIC stay revoked from 026/027).
grant select, insert, update, delete on public.employers to authenticated, service_role;
grant select, insert, update, delete on public.employer_members to authenticated, service_role;
grant select, insert, update, delete on public.hiring_requirements to authenticated, service_role;
grant select, insert, update, delete on public.hiring_requirement_skills to authenticated, service_role;
grant select, insert, update, delete on public.applications to authenticated, service_role;
grant select, insert on public.application_events to authenticated, service_role;
grant select, insert, update, delete on public.employer_feedback to authenticated, service_role;
grant select, insert on public.employer_skill_feedback to authenticated, service_role;
grant select, insert, update, delete on public.qualification_alignments to authenticated, service_role;
grant select, insert, update, delete on public.placement_outcomes to authenticated, service_role;
