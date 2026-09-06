-- INAURA Industry Knowledge — Phase 4B
-- Run in Supabase SQL Editor after 002_create_evidence.sql
-- Prototype industry knowledge + pgvector foundation for RAG

-- 1. Enable pgvector (if available on Supabase project)
-- Supabase supports pgvector; if not available, the rest still works without vector
create extension if not exists vector;

-- 2. Industry requirements table
create table if not exists public.industry_requirements (
  id uuid primary key default gen_random_uuid(),
  role text not null,
  skill text not null,
  skill_category text not null,
  importance double precision not null check (importance between 0 and 1),
  demand double precision not null check (demand between 0 and 1),
  interview_relevance double precision not null check (interview_relevance between 0 and 1),
  source text not null,
  source_url text,
  description text,
  version text not null default 'v1-prototype',
  metadata jsonb default '{}'::jsonb,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(role, skill)
);

-- Updated_at trigger (reuse handle_updated_at)
drop trigger if exists set_updated_at_industry on public.industry_requirements;
create trigger set_updated_at_industry
  before update on public.industry_requirements
  for each row execute function public.handle_updated_at();

-- RLS — globally readable for authenticated, writable only by service_role
alter table public.industry_requirements enable row level security;

drop policy if exists "Anyone can read industry requirements" on public.industry_requirements;
create policy "Anyone can read industry requirements"
  on public.industry_requirements for select
  using (true);

drop policy if exists "Service role can manage industry requirements" on public.industry_requirements;
create policy "Service role can manage industry requirements"
  on public.industry_requirements for all
  using (auth.jwt() ->> 'role' = 'service_role')
  with check (auth.jwt() ->> 'role' = 'service_role');

-- Grants — read for all, write for service_role (bypasses RLS anyway)
grant select on public.industry_requirements to anon, authenticated, service_role;
grant insert, update, delete on public.industry_requirements to service_role;
grant usage on schema public to anon, authenticated, service_role;

-- Indexes
create index if not exists idx_industry_role on public.industry_requirements (role);
create index if not exists idx_industry_skill on public.industry_requirements (skill);
create index if not exists idx_industry_role_skill on public.industry_requirements (role, skill);

-- Vector index — only if pgvector available and embedding populated
-- Use ivfflat with cosine; requires data before creation, so create as not valid initially and will be built after seed
do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    -- Create index concurrently if not exists (will be empty until embeddings filled)
    -- Use hnsw for better recall on small dataset if available, else ivfflat
    begin
      create index if not exists idx_industry_embedding_hnsw
        on public.industry_requirements using hnsw (embedding vector_cosine_ops);
    exception when others then
      begin
        create index if not exists idx_industry_embedding_ivfflat
          on public.industry_requirements using ivfflat (embedding vector_cosine_ops) with (lists = 100);
      exception when others then
        -- No vector index if pgvector version doesn't support
        null;
      end;
    end;
  end if;
end $$;

-- 3. Seed dataset — Prototype industry knowledge (heuristic values, not validated)
-- Marked as "Curated prototype dataset" — do not claim as full industry
insert into public.industry_requirements (role, skill, skill_category, importance, demand, interview_relevance, source, source_url, description, version) values
-- Software Engineer
  ('Software Engineer', 'Python', 'Programming', 0.85, 0.90, 0.75, 'Curated prototype dataset', null, 'Core programming language for backend and scripting', 'v1-prototype'),
  ('Software Engineer', 'Java', 'Programming', 0.75, 0.80, 0.70, 'Curated prototype dataset', null, 'Enterprise language, OOP fundamentals', 'v1-prototype'),
  ('Software Engineer', 'C++', 'Programming', 0.60, 0.55, 0.65, 'Curated prototype dataset', null, 'Systems programming and performance-critical code', 'v1-prototype'),
  ('Software Engineer', 'Data Structures & Algorithms', 'Core CS', 0.95, 0.90, 0.95, 'Curated prototype dataset', null, 'Problem solving, complexity, interview focus', 'v1-prototype'),
  ('Software Engineer', 'Git', 'Tools', 0.80, 0.85, 0.60, 'Curated prototype dataset', null, 'Version control and collaboration', 'v1-prototype'),
  ('Software Engineer', 'SQL', 'Data', 0.85, 0.88, 0.75, 'Curated prototype dataset', null, 'Relational data querying and schema design', 'v1-prototype'),
  ('Software Engineer', 'REST APIs', 'Backend', 0.82, 0.85, 0.70, 'Curated prototype dataset', null, 'HTTP APIs, design and integration', 'v1-prototype'),
  ('Software Engineer', 'Testing', 'Quality', 0.70, 0.75, 0.65, 'Curated prototype dataset', null, 'Unit, integration and system testing', 'v1-prototype'),
  ('Software Engineer', 'System Design fundamentals', 'Architecture', 0.75, 0.80, 0.75, 'Curated prototype dataset', null, 'Scalability, reliability, trade-offs', 'v1-prototype'),

  -- AI/ML Engineer
  ('AI/ML Engineer', 'Python', 'Programming', 0.90, 0.90, 0.75, 'Curated prototype dataset', null, 'Primary language for ML', 'v1-prototype'),
  ('AI/ML Engineer', 'NumPy', 'Data', 0.80, 0.75, 0.60, 'Curated prototype dataset', null, 'Numerical computing', 'v1-prototype'),
  ('AI/ML Engineer', 'Pandas', 'Data', 0.82, 0.80, 0.60, 'Curated prototype dataset', null, 'Data manipulation and analysis', 'v1-prototype'),
  ('AI/ML Engineer', 'Scikit-learn', 'ML', 0.85, 0.80, 0.70, 'Curated prototype dataset', null, 'Classical ML algorithms', 'v1-prototype'),
  ('AI/ML Engineer', 'Machine Learning', 'ML', 0.95, 0.90, 0.85, 'Curated prototype dataset', null, 'Supervised, unsupervised concepts', 'v1-prototype'),
  ('AI/ML Engineer', 'Deep Learning', 'ML', 0.80, 0.85, 0.70, 'Curated prototype dataset', null, 'Neural networks, frameworks', 'v1-prototype'),
  ('AI/ML Engineer', 'SQL', 'Data', 0.65, 0.70, 0.60, 'Curated prototype dataset', null, 'Data retrieval for ML', 'v1-prototype'),
  ('AI/ML Engineer', 'Git', 'Tools', 0.70, 0.75, 0.55, 'Curated prototype dataset', null, 'Version control', 'v1-prototype'),
  ('AI/ML Engineer', 'Model evaluation', 'ML', 0.78, 0.75, 0.68, 'Curated prototype dataset', null, 'Metrics, validation, overfitting', 'v1-prototype'),
  ('AI/ML Engineer', 'Deployment fundamentals', 'MLOps', 0.60, 0.65, 0.55, 'Curated prototype dataset', null, 'Model serving, basics', 'v1-prototype'),

  -- Data Scientist
  ('Data Scientist', 'Python', 'Programming', 0.88, 0.90, 0.75, 'Curated prototype dataset', null, 'Core for analysis', 'v1-prototype'),
  ('Data Scientist', 'SQL', 'Data', 0.90, 0.92, 0.80, 'Curated prototype dataset', null, 'Data extraction and warehousing', 'v1-prototype'),
  ('Data Scientist', 'Pandas', 'Data', 0.85, 0.85, 0.70, 'Curated prototype dataset', null, 'Data wrangling', 'v1-prototype'),
  ('Data Scientist', 'Statistics', 'Core', 0.90, 0.85, 0.80, 'Curated prototype dataset', null, 'Hypothesis testing, distributions', 'v1-prototype'),
  ('Data Scientist', 'Machine Learning', 'ML', 0.85, 0.80, 0.75, 'Curated prototype dataset', null, 'Predictive modeling', 'v1-prototype'),
  ('Data Scientist', 'Data Visualization', 'Communication', 0.75, 0.70, 0.60, 'Curated prototype dataset', null, 'Storytelling with data', 'v1-prototype'),
  ('Data Scientist', 'Git', 'Tools', 0.65, 0.70, 0.50, 'Curated prototype dataset', null, 'Versioning', 'v1-prototype'),
  ('Data Scientist', 'Communication', 'Soft', 0.70, 0.75, 0.65, 'Curated prototype dataset', null, 'Explaining insights', 'v1-prototype'),

  -- Frontend Developer
  ('Frontend Developer', 'HTML/CSS', 'Frontend', 0.90, 0.90, 0.75, 'Curated prototype dataset', null, 'Markup and styling', 'v1-prototype'),
  ('Frontend Developer', 'JavaScript', 'Frontend', 0.95, 0.95, 0.90, 'Curated prototype dataset', null, 'Core language', 'v1-prototype'),
  ('Frontend Developer', 'React', 'Frontend', 0.88, 0.90, 0.80, 'Curated prototype dataset', null, 'Component-based UI', 'v1-prototype'),
  ('Frontend Developer', 'TypeScript', 'Frontend', 0.75, 0.80, 0.65, 'Curated prototype dataset', null, 'Typed JS', 'v1-prototype'),
  ('Frontend Developer', 'Git', 'Tools', 0.75, 0.80, 0.55, 'Curated prototype dataset', null, 'Version control', 'v1-prototype'),
  ('Frontend Developer', 'REST APIs', 'Backend', 0.70, 0.75, 0.60, 'Curated prototype dataset', null, 'Consuming APIs', 'v1-prototype'),
  ('Frontend Developer', 'Testing', 'Quality', 0.60, 0.65, 0.55, 'Curated prototype dataset', null, 'Frontend testing', 'v1-prototype'),
  ('Frontend Developer', 'Responsive Design', 'Frontend', 0.78, 0.80, 0.60, 'Curated prototype dataset', null, 'Mobile-first, accessibility', 'v1-prototype'),

  -- Backend Developer
  ('Backend Developer', 'Python', 'Programming', 0.85, 0.85, 0.75, 'Curated prototype dataset', null, 'Backend language', 'v1-prototype'),
  ('Backend Developer', 'Java', 'Programming', 0.70, 0.75, 0.65, 'Curated prototype dataset', null, 'Alternative backend', 'v1-prototype'),
  ('Backend Developer', 'SQL', 'Data', 0.90, 0.90, 0.80, 'Curated prototype dataset', null, 'Database design and queries', 'v1-prototype'),
  ('Backend Developer', 'REST APIs', 'Backend', 0.92, 0.90, 0.80, 'Curated prototype dataset', null, 'API design', 'v1-prototype'),
  ('Backend Developer', 'Git', 'Tools', 0.75, 0.80, 0.55, 'Curated prototype dataset', null, 'Versioning', 'v1-prototype'),
  ('Backend Developer', 'System Design', 'Architecture', 0.80, 0.85, 0.75, 'Curated prototype dataset', null, 'Scalability and patterns', 'v1-prototype'),
  ('Backend Developer', 'Testing', 'Quality', 0.70, 0.75, 0.60, 'Curated prototype dataset', null, 'Backend testing', 'v1-prototype'),
  ('Backend Developer', 'Docker', 'DevOps', 0.65, 0.70, 0.55, 'Curated prototype dataset', null, 'Containerization', 'v1-prototype'),
  ('Backend Developer', 'Caching', 'Backend', 0.60, 0.65, 0.55, 'Curated prototype dataset', null, 'Redis, performance', 'v1-prototype'),

  -- DevOps / Cloud Engineer
  ('DevOps / Cloud Engineer', 'Linux', 'Infra', 0.85, 0.85, 0.70, 'Curated prototype dataset', null, 'OS fundamentals', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'Docker', 'Infra', 0.90, 0.90, 0.80, 'Curated prototype dataset', null, 'Containers', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'Kubernetes', 'Infra', 0.75, 0.80, 0.65, 'Curated prototype dataset', null, 'Orchestration', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'AWS/GCP', 'Cloud', 0.85, 0.88, 0.75, 'Curated prototype dataset', null, 'Cloud platforms', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'CI/CD', 'DevOps', 0.80, 0.85, 0.70, 'Curated prototype dataset', null, 'Pipelines and automation', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'Git', 'Tools', 0.75, 0.80, 0.55, 'Curated prototype dataset', null, 'Version control', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'Networking', 'Infra', 0.70, 0.75, 0.60, 'Curated prototype dataset', null, 'VPC, DNS, LB', 'v1-prototype'),
  ('DevOps / Cloud Engineer', 'Monitoring', 'Ops', 0.65, 0.70, 0.60, 'Curated prototype dataset', null, 'Logging and observability', 'v1-prototype')
on conflict (role, skill) do nothing;

comment on table public.industry_requirements is 'Phase 4B — Prototype industry knowledge (heuristic importance/demand/interview_relevance 0-1, not scientifically validated). Source traceability via source/source_url. Future: job postings, reports. Vector embedding for RAG.';
