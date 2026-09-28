-- INAURA P0 #2: Institution + Course + Curriculum supply model — Migration 031
-- Tables: institutions, courses, course_modules, course_skills, trainers, trainer_skills
--
-- Reference-data model: authenticated SELECT; writes go through the backend
-- service-role client only (same convention as 029 industry outcomes and 030
-- labour-market tables). No anon access. Policies reference no other tables,
-- so RLS cannot recurse.
--
-- Provenance reuses the repo-wide data_origin tiers
-- (source_data | inaura_derived | demo_seeded): real institutional records are
-- source_data; the deterministic demo seed is demo_seeded and must never be
-- presented as real institutional data.
--
-- Coverage scale (documented, no arbitrary scores):
--   introductory  — awareness + guided exercises (can follow a tutorial)
--   intermediate  — independent coursework application (can build with docs)
--   advanced      — production-grade / project ownership depth
-- Rollback (reverse order): drop table if exists trainer_skills, trainers,
--   course_skills, course_modules, courses, institutions.

create table if not exists public.institutions (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 200),
  code text,
  institution_type text not null default 'other'
    check (institution_type in ('iti', 'polytechnic', 'college', 'university',
                                'skill_training_centre', 'training_institute', 'other')),
  district text,
  state text,
  country text,
  city text,
  website text,
  description text,
  status text not null default 'active'
    check (status in ('active', 'suspended', 'archived')),
  data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_institutions_code
  on public.institutions (code) where code is not null;
-- Same name + same district/city is an accidental duplicate, not a new record.
create unique index if not exists uq_institutions_name_locale
  on public.institutions ((lower(name)), (coalesce(district, '')), (coalesce(city, '')));

create table if not exists public.courses (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 200),
  code text,
  description text,
  level text,
  duration_text text,
  delivery_mode text check (delivery_mode in ('online', 'offline', 'hybrid') or delivery_mode is null),
  status text not null default 'draft'
    check (status in ('draft', 'active', 'archived')),
  data_origin text not null default 'source_data'
    check (data_origin in ('source_data', 'inaura_derived', 'demo_seeded')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Same institution + same course name is an accidental duplicate.
create unique index if not exists uq_courses_institution_name
  on public.courses (institution_id, (lower(name)));
create unique index if not exists uq_courses_institution_code
  on public.courses (institution_id, code) where code is not null;

create table if not exists public.course_modules (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 200),
  code text,
  description text,
  sequence integer not null default 0 check (sequence >= 0),
  hours numeric check (hours is null or hours >= 0),
  status text not null default 'draft'
    check (status in ('draft', 'active', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Curriculum ordering slots are unique per course.
create unique index if not exists uq_modules_course_sequence
  on public.course_modules (course_id, sequence);

create table if not exists public.course_skills (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses(id) on delete cascade,
  module_id uuid references public.course_modules(id) on delete cascade,
  skill_id uuid references public.skills(id) on delete set null,
  canonical_skill_slug text,
  source_concept text not null check (char_length(source_concept) between 1 and 200),
  mapping_status text not null default 'unmapped'
    check (mapping_status in ('mapped', 'unmapped')),
  mapping_rationale text,
  coverage text check (coverage in ('introductory', 'intermediate', 'advanced') or coverage is null),
  importance text check (importance in ('required', 'preferred') or importance is null),
  evidence_source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- mapped rows always carry a slug; unmapped rows never do.
  constraint chk_course_skills_mapping check (
    (mapping_status = 'mapped') = (canonical_skill_slug is not null)
  )
);

-- No duplicate mapping for the same course + module + canonical skill.
-- module_id is nullable (course-level skills), so the module slot is
-- coalesced to '' inside the key. Mapped and raw-concept cells use separate
-- partial indexes so NULL semantics stay unambiguous.
create unique index if not exists uq_course_skills_mapped
  on public.course_skills (course_id, ((coalesce(module_id::text, ''))), canonical_skill_slug)
  where canonical_skill_slug is not null;
create unique index if not exists uq_course_skills_raw
  on public.course_skills (course_id, ((coalesce(module_id::text, ''))), (lower(source_concept)))
  where canonical_skill_slug is null;

create table if not exists public.trainers (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  name text not null check (char_length(name) between 2 and 200),
  email text,
  designation text,
  status text not null default 'active'
    check (status in ('active', 'inactive', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_trainers_institution_email
  on public.trainers (institution_id, (lower(email))) where email is not null;

create table if not exists public.trainer_skills (
  id uuid primary key default gen_random_uuid(),
  trainer_id uuid not null references public.trainers(id) on delete cascade,
  skill_id uuid references public.skills(id) on delete set null,
  canonical_skill_slug text not null,
  proficiency text check (proficiency in ('introductory', 'intermediate', 'advanced') or proficiency is null),
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One proficiency record per trainer + canonical skill.
create unique index if not exists uq_trainer_skills_trainer_skill
  on public.trainer_skills (trainer_id, canonical_skill_slug);

-- Updated-at triggers (reuse handle_updated_at from 001)
drop trigger if exists set_updated_at on public.institutions;
create trigger set_updated_at before update on public.institutions
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.courses;
create trigger set_updated_at before update on public.courses
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.course_modules;
create trigger set_updated_at before update on public.course_modules
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.course_skills;
create trigger set_updated_at before update on public.course_skills
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.trainers;
create trigger set_updated_at before update on public.trainers
  for each row execute function public.handle_updated_at();
drop trigger if exists set_updated_at on public.trainer_skills;
create trigger set_updated_at before update on public.trainer_skills
  for each row execute function public.handle_updated_at();

-- RLS: reference data. Authenticated SELECT; writes are service-role only
-- (backend API). No cross-table subqueries in any policy: non-recursive.
alter table public.institutions enable row level security;
alter table public.courses enable row level security;
alter table public.course_modules enable row level security;
alter table public.course_skills enable row level security;
alter table public.trainers enable row level security;
alter table public.trainer_skills enable row level security;

drop policy if exists "Authenticated can read institutions" on public.institutions;
create policy "Authenticated can read institutions"
  on public.institutions for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read courses" on public.courses;
create policy "Authenticated can read courses"
  on public.courses for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read course modules" on public.course_modules;
create policy "Authenticated can read course modules"
  on public.course_modules for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read course skills" on public.course_skills;
create policy "Authenticated can read course skills"
  on public.course_skills for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read trainers" on public.trainers;
create policy "Authenticated can read trainers"
  on public.trainers for select using (auth.uid() is not null);
drop policy if exists "Authenticated can read trainer skills" on public.trainer_skills;
create policy "Authenticated can read trainer skills"
  on public.trainer_skills for select using (auth.uid() is not null);

-- Grants: authenticated SELECT + service_role ALL. Explicitly revoke anon/PUBLIC.
revoke all on public.institutions from anon, public;
revoke all on public.courses from anon, public;
revoke all on public.course_modules from anon, public;
revoke all on public.course_skills from anon, public;
revoke all on public.trainers from anon, public;
revoke all on public.trainer_skills from anon, public;
grant select on public.institutions to authenticated;
grant select on public.courses to authenticated;
grant select on public.course_modules to authenticated;
grant select on public.course_skills to authenticated;
grant select on public.trainers to authenticated;
grant select on public.trainer_skills to authenticated;
grant select, insert, update, delete on public.institutions to service_role;
grant select, insert, update, delete on public.courses to service_role;
grant select, insert, update, delete on public.course_modules to service_role;
grant select, insert, update, delete on public.course_skills to service_role;
grant select, insert, update, delete on public.trainers to service_role;
grant select, insert, update, delete on public.trainer_skills to service_role;

-- Lookup indexes
create index if not exists idx_institutions_type on public.institutions (institution_type);
create index if not exists idx_institutions_district on public.institutions (district);
create index if not exists idx_institutions_state on public.institutions (state);
create index if not exists idx_institutions_status on public.institutions (status);
create index if not exists idx_courses_institution on public.courses (institution_id);
create index if not exists idx_courses_status on public.courses (status);
create index if not exists idx_modules_course on public.course_modules (course_id);
create index if not exists idx_course_skills_course on public.course_skills (course_id);
create index if not exists idx_course_skills_module on public.course_skills (module_id);
create index if not exists idx_course_skills_slug on public.course_skills (canonical_skill_slug);
create index if not exists idx_trainers_institution on public.trainers (institution_id);
create index if not exists idx_trainer_skills_trainer on public.trainer_skills (trainer_id);
create index if not exists idx_trainer_skills_slug on public.trainer_skills (canonical_skill_slug);

comment on table public.institutions is 'P0#2 training-supply root. District/state/city support future district aggregation. data_origin demo_seeded rows are synthetic demo data, never real institutional data.';
comment on table public.courses is 'P0#2 courses belonging to an institution. Unique per (institution, lower(name)). No alignment scoring lives here.';
comment on table public.course_modules is 'P0#2 curriculum units with ordering via sequence (unique per course).';
comment on table public.course_skills is 'P0#2 skills taught by a course/module. source_concept is the raw curriculum phrase; canonical_skill_slug resolves via the INAURA taxonomy; unmapped concepts preserved with mapping_status=unmapped. coverage uses the documented introductory/intermediate/advanced scale.';
comment on table public.trainers is 'P0#2 minimal trainer roster for future capacity analysis, not an HR system.';
comment on table public.trainer_skills is 'P0#2 trainer canonical skills with teaching-depth proficiency on the same introductory/intermediate/advanced scale.';
