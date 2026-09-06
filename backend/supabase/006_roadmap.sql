-- INAURA Personalized Roadmap Engine — Phase 4D
-- Run in Supabase SQL Editor after 005_skill_engine.sql
-- Creates roadmap, roadmap_items, roadmap_resources, roadmap_milestones

-- 1. Roadmaps (overall per generation)
create table if not exists public.roadmaps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  analysis_result_id uuid not null references public.analysis_results(id) on delete cascade,
  target_role text not null,
  title text not null,
  status text not null check (status in ('active','completed','archived')) default 'active',
  engine_version text not null default '4D-v1',
  total_estimated_hours double precision not null check (total_estimated_hours >= 0),
  estimated_weeks integer not null check (estimated_weeks >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_roadmaps on public.roadmaps;
create trigger set_updated_at_roadmaps
  before update on public.roadmaps
  for each row execute function public.handle_updated_at();

alter table public.roadmaps enable row level security;
drop policy if exists "Users can manage own roadmaps" on public.roadmaps;
create policy "Users can manage own roadmaps"
  on public.roadmaps for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
grant select, insert, update, delete on public.roadmaps to authenticated, service_role;
create index if not exists idx_roadmaps_user on public.roadmaps (user_id);
create index if not exists idx_roadmaps_user_created on public.roadmaps (user_id, created_at desc);

-- 2. Roadmap items (per skill gap, progression learn/practice/project/assessment)
create table if not exists public.roadmap_items (
  id uuid primary key default gen_random_uuid(),
  roadmap_id uuid not null references public.roadmaps(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete cascade,
  skill_gap_id uuid references public.skill_gaps(id) on delete set null,
  title text not null,
  description text not null,
  item_type text not null check (item_type in ('learn','practice','project','assessment')),
  priority integer not null,
  estimated_hours double precision not null check (estimated_hours >= 0),
  sequence_order integer not null,
  status text not null check (status in ('not_started','in_progress','completed')) default 'not_started',
  completion_percentage double precision not null check (completion_percentage between 0 and 100) default 0,
  why_it_matters text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_roadmap_items on public.roadmap_items;
create trigger set_updated_at_roadmap_items
  before update on public.roadmap_items
  for each row execute function public.handle_updated_at();

alter table public.roadmap_items enable row level security;
drop policy if exists "Users can manage own roadmap items" on public.roadmap_items;
create policy "Users can manage own roadmap items"
  on public.roadmap_items for all
  using (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()))
  with check (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()));
grant select, insert, update, delete on public.roadmap_items to authenticated, service_role;
create index if not exists idx_roadmap_items_roadmap on public.roadmap_items (roadmap_id);
create index if not exists idx_roadmap_items_skill on public.roadmap_items (skill_id);

-- 3. Roadmap resources (per item, curated prototype)
create table if not exists public.roadmap_resources (
  id uuid primary key default gen_random_uuid(),
  roadmap_item_id uuid not null references public.roadmap_items(id) on delete cascade,
  title text not null,
  resource_type text not null check (resource_type in ('course','documentation','tutorial','article','video','practice','project_reference')),
  url text not null,
  provider text,
  difficulty text check (difficulty in ('beginner','intermediate','advanced') or difficulty is null),
  estimated_hours double precision check (estimated_hours is null or estimated_hours >= 0),
  is_free boolean not null default true,
  description text not null,
  created_at timestamptz not null default now()
);

alter table public.roadmap_resources enable row level security;
drop policy if exists "Users can manage own roadmap resources" on public.roadmap_resources;
create policy "Users can manage own roadmap resources"
  on public.roadmap_resources for all
  using (exists (
    select 1 from public.roadmap_items ri
    join public.roadmaps r on r.id = ri.roadmap_id
    where ri.id = roadmap_item_id and r.user_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.roadmap_items ri
    join public.roadmaps r on r.id = ri.roadmap_id
    where ri.id = roadmap_item_id and r.user_id = auth.uid()
  ));
grant select, insert, update, delete on public.roadmap_resources to authenticated, service_role;
create index if not exists idx_roadmap_resources_item on public.roadmap_resources (roadmap_item_id);

-- 4. Roadmap milestones (grouped)
create table if not exists public.roadmap_milestones (
  id uuid primary key default gen_random_uuid(),
  roadmap_id uuid not null references public.roadmaps(id) on delete cascade,
  title text not null,
  description text not null,
  sequence_order integer not null,
  target_hours double precision not null check (target_hours >= 0),
  status text not null check (status in ('not_started','in_progress','completed')) default 'not_started',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_milestones on public.roadmap_milestones;
create trigger set_updated_at_milestones
  before update on public.roadmap_milestones
  for each row execute function public.handle_updated_at();

alter table public.roadmap_milestones enable row level security;
drop policy if exists "Users can manage own milestones" on public.roadmap_milestones;
create policy "Users can manage own milestones"
  on public.roadmap_milestones for all
  using (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()))
  with check (exists (select 1 from public.roadmaps r where r.id = roadmap_id and r.user_id = auth.uid()));
grant select, insert, update, delete on public.roadmap_milestones to authenticated, service_role;
create index if not exists idx_roadmap_milestones_roadmap on public.roadmap_milestones (roadmap_id);

comment on table public.roadmaps is 'Phase 4D — personalized roadmaps, engine_version 4D-v1, status active/completed/archived, total_estimated_hours, estimated_weeks = ceil(total / hours_per_week)';
comment on table public.roadmap_items is 'Phase 4D — per-skill roadmap items: learn/practice/project/assessment, priority, estimated_hours, why_it_matters explainability, status not_started/in_progress/completed, completion 0-100';
comment on table public.roadmap_resources is 'Phase 4D — curated prototype resources (not scraped): course/documentation/tutorial/article/video/practice/project_reference, provider/difficulty/is_free';
comment on table public.roadmap_milestones is 'Phase 4D — milestones grouping items: Strengthen Core Foundations / Build Practical Capability / Demonstrate Industry Readiness, target_hours, status';
