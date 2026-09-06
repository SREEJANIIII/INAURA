-- INAURA Skill Engine — Phase 4C
-- Run in Supabase SQL Editor after 004_analysis_state.sql
-- Creates canonical skill taxonomy and deterministic scoring tables

-- 1. Canonical skills taxonomy
create table if not exists public.skills (
  id uuid primary key default gen_random_uuid(),
  canonical_name text unique not null,
  display_name text not null,
  category text not null,
  aliases text[] not null default '{}',
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_skills on public.skills;
create trigger set_updated_at_skills
  before update on public.skills
  for each row execute function public.handle_updated_at();

alter table public.skills enable row level security;
drop policy if exists "Anyone can read skills" on public.skills;
create policy "Anyone can read skills" on public.skills for select using (true);
grant select on public.skills to anon, authenticated, service_role;
grant insert, update, delete on public.skills to service_role;

-- Seed prototype taxonomy from existing industry requirements (canonical)
insert into public.skills (canonical_name, display_name, category, aliases, description) values
  ('python', 'Python', 'Programming', array['py','python3'], 'General-purpose programming language'),
  ('java', 'Java', 'Programming', array['java8','java11'], 'Enterprise OOP language'),
  ('cpp', 'C++', 'Programming', array['c++','cpp'], 'Systems programming language'),
  ('dsa', 'Data Structures & Algorithms', 'Core CS', array['dsa','algorithms','data structures'], 'Problem solving and complexity'),
  ('git', 'Git', 'Tools', array['git','github','version control'], 'Version control'),
  ('sql', 'SQL', 'Database', array['sql','postgres','postgresql','mysql'], 'Relational querying'),
  ('rest_apis', 'REST APIs', 'Backend', array['rest','rest api','rest apis','api'], 'HTTP API design'),
  ('testing', 'Testing', 'Quality', array['testing','unit test','tdd'], 'Software testing'),
  ('system_design', 'System Design', 'Architecture', array['system design','system_design','architecture'], 'Scalability and design'),
  ('numpy', 'NumPy', 'Data', array['numpy'], 'Numerical computing'),
  ('pandas', 'Pandas', 'Data', array['pandas'], 'Data manipulation'),
  ('scikit_learn', 'Scikit-learn', 'Machine Learning', array['scikit-learn','sklearn'], 'Classical ML'),
  ('machine_learning', 'Machine Learning', 'Machine Learning', array['ml','machine learning'], 'ML concepts'),
  ('deep_learning', 'Deep Learning', 'AI', array['deep learning','dl'], 'Neural networks'),
  ('statistics', 'Statistics', 'Data Science', array['statistics','stats'], 'Statistical methods'),
  ('data_visualization', 'Data Visualization', 'Data Science', array['data viz','visualization'], 'Data storytelling'),
  ('communication', 'Communication', 'Soft', array['communication'], 'Explaining insights'),
  ('html_css', 'HTML/CSS', 'Frontend', array['html','css','html/css'], 'Markup and styling'),
  ('javascript', 'JavaScript', 'Frontend', array['js','javascript'], 'Frontend language'),
  ('react', 'React', 'Frontend', array['react','react.js','reactjs'], 'UI library'),
  ('typescript', 'TypeScript', 'Frontend', array['ts','typescript'], 'Typed JS'),
  ('responsive_design', 'Responsive Design', 'Frontend', array['responsive design','responsive'], 'Mobile-first design'),
  ('docker', 'Docker', 'DevOps', array['docker','container'], 'Containerization'),
  ('kubernetes', 'Kubernetes', 'DevOps', array['k8s','kubernetes'], 'Orchestration'),
  ('aws_gcp', 'AWS/GCP', 'Cloud', array['aws','gcp','cloud','aws/gcp'], 'Cloud platforms'),
  ('linux', 'Linux', 'Infra', array['linux','unix'], 'OS fundamentals'),
  ('cicd', 'CI/CD', 'DevOps', array['cicd','ci/cd','ci cd'], 'Pipelines'),
  ('networking', 'Networking', 'Infra', array['networking','network'], 'Networking fundamentals'),
  ('monitoring', 'Monitoring', 'Ops', array['monitoring','observability'], 'Monitoring'),
  ('caching', 'Caching', 'Backend', array['caching','cache','redis'], 'Caching strategies'),
  ('model_evaluation', 'Model Evaluation', 'ML', array['model evaluation','evaluation'], 'Metrics and validation'),
  ('deployment', 'Deployment', 'MLOps', array['deployment','mlops'], 'Model serving')
on conflict (canonical_name) do nothing;

-- 2. Add required_level to industry_requirements if not exists (heuristic, default from importance)
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='industry_requirements' and column_name='required_level') then
    alter table public.industry_requirements add column required_level double precision check (required_level between 0 and 1) default 0.75;
    -- Backfill from importance where null
    update public.industry_requirements set required_level = importance where required_level is null;
  end if;
end $$;

-- 3. Skill signals (evidence → skill)
create table if not exists public.skill_signals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete cascade,
  evidence_id uuid references public.evidence(id) on delete set null,
  project_id uuid references public.projects(id) on delete set null,
  certification_id uuid references public.certifications(id) on delete set null,
  source_type text not null check (source_type in ('github','leetcode','codeforces','kaggle','linkedin','resume','syllabus','certification','project','self_declared')),
  signal_value double precision not null check (signal_value between 0 and 1),
  source_reliability double precision not null check (source_reliability between 0 and 1),
  explanation text not null,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.skill_signals enable row level security;
drop policy if exists "Users can manage own signals" on public.skill_signals;
create policy "Users can manage own signals" on public.skill_signals for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.skill_signals to authenticated, service_role;
grant select on public.skill_signals to anon;

create index if not exists idx_signals_user_skill on public.skill_signals (user_id, skill_id);

-- 4. Skill assessments (per skill per analysis)
create table if not exists public.skill_assessments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete cascade,
  proficiency double precision not null check (proficiency between 0 and 1),
  confidence double precision not null check (confidence between 0 and 1),
  evidence_weight double precision not null,
  source_diversity double precision not null,
  evidence_count int not null,
  explanation text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_assessments on public.skill_assessments;
create trigger set_updated_at_assessments before update on public.skill_assessments for each row execute function public.handle_updated_at();
alter table public.skill_assessments enable row level security;
drop policy if exists "Users can manage own assessments" on public.skill_assessments;
create policy "Users can manage own assessments" on public.skill_assessments for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.skill_assessments to authenticated, service_role;
create index if not exists idx_assessments_user on public.skill_assessments (user_id);

-- 5. Analysis results (overall)
create table if not exists public.analysis_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  target_role text not null,
  skill_component double precision not null check (skill_component between 0 and 1),
  industry_component double precision not null check (industry_component between 0 and 1),
  evidence_component double precision not null check (evidence_component between 0 and 1),
  readiness_score double precision not null check (readiness_score between 0 and 1),
  assessment_count int not null,
  gap_count int not null,
  engine_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists set_updated_at_results on public.analysis_results;
create trigger set_updated_at_results before update on public.analysis_results for each row execute function public.handle_updated_at();
alter table public.analysis_results enable row level security;
drop policy if exists "Users can manage own results" on public.analysis_results;
create policy "Users can manage own results" on public.analysis_results for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.analysis_results to authenticated, service_role;
create index if not exists idx_results_user on public.analysis_results (user_id);

-- 6. Skill gaps (per skill per analysis)
create table if not exists public.skill_gaps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  analysis_result_id uuid not null references public.analysis_results(id) on delete cascade,
  skill_id uuid not null references public.skills(id) on delete cascade,
  target_role text not null,
  required_level double precision not null check (required_level between 0 and 1),
  current_proficiency double precision not null check (current_proficiency between 0 and 1),
  confidence double precision not null check (confidence between 0 and 1),
  gap double precision not null check (gap between 0 and 1),
  importance double precision not null,
  demand double precision not null,
  interview_relevance double precision not null,
  priority_score double precision not null,
  explanation text not null,
  created_at timestamptz not null default now()
);

alter table public.skill_gaps enable row level security;
drop policy if exists "Users can manage own gaps" on public.skill_gaps;
create policy "Users can manage own gaps" on public.skill_gaps for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert, update, delete on public.skill_gaps to authenticated, service_role;
create index if not exists idx_gaps_user on public.skill_gaps (user_id);
create index if not exists idx_gaps_result on public.skill_gaps (analysis_result_id);

comment on table public.skills is 'Phase 4C — canonical skill taxonomy';
comment on table public.skill_signals is 'Phase 4C — evidence-derived signals, traceable to evidence/project/cert';
comment on table public.skill_assessments is 'Phase 4C — per-skill proficiency/confidence';
comment on table public.analysis_results is 'Phase 4C — overall readiness, engine_version 4C-v1';
comment on table public.skill_gaps is 'Phase 4C — prioritized gaps';
