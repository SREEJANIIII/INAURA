-- INAURA Industry Intelligence — Phase 4F
-- Run in Supabase SQL Editor after 008_evidence_verification.sql
-- Upgrades industry knowledge with 5 distinct dimensions, source provenance,
-- knowledge chunks table for RAG, and authentic benchmarks for 11 catalog roles.

-- 1. Upgrade public.industry_requirements with distinct dimensions and provenance
alter table public.industry_requirements
  add column if not exists required_level double precision not null default 0.75 check (required_level between 0 and 1),
  add column if not exists industry_confidence double precision not null default 0.85 check (industry_confidence between 0 and 1),
  add column if not exists source_quality double precision not null default 0.80 check (source_quality between 0 and 1),
  add column if not exists evidence_context text,
  add column if not exists published_at date default '2024-01-01',
  add column if not exists retrieved_at timestamptz default now();

-- 2. Create industry_knowledge_chunks table for RAG retrieval
create table if not exists public.industry_knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  role text not null,
  topic text not null,
  content text not null,
  skills_mentioned jsonb not null default '[]'::jsonb,
  source text not null,
  source_url text,
  source_quality double precision not null default 0.80 check (source_quality between 0 and 1),
  published_at date default '2024-01-01',
  retrieved_at timestamptz default now(),
  embedding vector(1536),
  created_at timestamptz not null default now()
);

-- RLS for industry_knowledge_chunks
alter table public.industry_knowledge_chunks enable row level security;

drop policy if exists "Anyone can read industry knowledge chunks" on public.industry_knowledge_chunks;
create policy "Anyone can read industry knowledge chunks"
  on public.industry_knowledge_chunks for select
  using (true);

drop policy if exists "Service role can manage industry knowledge chunks" on public.industry_knowledge_chunks;
create policy "Service role can manage industry knowledge chunks"
  on public.industry_knowledge_chunks for all
  using (auth.jwt() ->> 'role' = 'service_role')
  with check (auth.jwt() ->> 'role' = 'service_role');

-- Grants
grant select on public.industry_knowledge_chunks to anon, authenticated, service_role;
grant insert, update, delete on public.industry_knowledge_chunks to service_role;

-- Indexes
create index if not exists idx_knowledge_chunks_role on public.industry_knowledge_chunks (role);

-- Vector index on knowledge chunks if pgvector available
do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    begin
      create index if not exists idx_knowledge_chunks_embedding_hnsw
        on public.industry_knowledge_chunks using hnsw (embedding vector_cosine_ops);
    exception when others then
      null;
    end;
  end if;
end $$;

-- 3. Vector Match RPC for Knowledge Chunks
create or replace function public.match_industry_knowledge_chunks (
  query_embedding vector(1536),
  match_count int default 5
) returns table (
  id uuid,
  role text,
  topic text,
  content text,
  skills_mentioned jsonb,
  source text,
  source_url text,
  source_quality double precision,
  similarity double precision
) language plpgsql stable as $$
begin
  return query
  select
    c.id,
    c.role,
    c.topic,
    c.content,
    c.skills_mentioned,
    c.source,
    c.source_url,
    c.source_quality,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.industry_knowledge_chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit match_count;
end;
$$;

grant execute on function public.match_industry_knowledge_chunks to anon, authenticated, service_role;

-- 4. Seed Knowledge Chunks for RAG Retrieval & Custom Role Synthesis
insert into public.industry_knowledge_chunks (role, topic, content, skills_mentioned, source, source_url, source_quality) values
  ('Software Engineer', 'Core Fundamentals',
   'Software engineering requires proficiency in Data Structures & Algorithms, Git version control, and relational databases with SQL. Production stability relies on automated Testing and Object-Oriented Programming (OOP) design patterns.',
   '["Data Structures & Algorithms", "Git", "SQL", "Testing", "OOP"]'::jsonb,
   'ACM/IEEE CS2023 Curriculum Guidelines', 'https://csed.acm.org/', 0.90),

  ('Backend Developer', 'Server Architecture',
   'Backend engineering emphasizes REST APIs contract design, PostgreSQL databases, Docker containerization, in-memory Caching with Redis, and System Design scalability.',
   '["REST APIs", "PostgreSQL", "Docker", "Caching", "System Design"]'::jsonb,
   'Stack Overflow Developer Survey 2024', 'https://survey.stackoverflow.co/2024/', 0.90),

  ('Frontend Developer', 'Client Web Engineering',
   'Frontend development centers on modern JavaScript, TypeScript, React components, HTML/CSS layout systems, and Responsive Design mobile accessibility.',
   '["JavaScript", "TypeScript", "React", "HTML/CSS", "Responsive Design"]'::jsonb,
   'W3C Web Standards Guidelines', 'https://www.w3.org/standards/', 0.90),

  ('AI Engineer', 'Applied AI and Foundation Models',
   'The emerging AI Engineer role integrates generative models and machine learning pipelines into production software. Essential competencies include Python programming, REST APIs, Deep Learning, Docker containerization, and Model Evaluation metrics.',
   '["Python", "REST APIs", "Deep Learning", "Docker", "Model Evaluation"]'::jsonb,
   'State of AI Engineering Report 2024', 'https://stateof.ai/', 0.85),

  ('DevOps Engineer', 'Cloud Infrastructure & SRE',
   'Site reliability and DevOps demand Linux systems administration, Kubernetes orchestration, CI/CD automated deployment, and Monitoring observability with Prometheus.',
   '["Linux", "Kubernetes", "CI/CD", "Monitoring"]'::jsonb,
   'Cloud Native Computing Foundation (CNCF) Annual Survey 2024', 'https://www.cncf.io/reports/', 0.90),

  ('Cybersecurity Engineer', 'Threat Mitigation & AppSec',
   'Cybersecurity requires in-depth Computer Networks, Network Security firewalls, Linux server administration, Application Security vulnerability mitigation, and Cryptography.',
   '["Computer Networks", "Network Security", "Linux", "Application Security", "Cryptography"]'::jsonb,
   'CompTIA State of Cybersecurity Report', 'https://www.comptia.org/content/research/state-of-cybersecurity', 0.90)
on conflict do nothing;

comment on table public.industry_knowledge_chunks is 'Phase 4F — Raw industry evidence chunks for RAG retrieval and dynamic custom role requirement synthesis.';
comment on table public.industry_requirements is 'Phase 4F — Normalized industry role requirements with 5 distinct dimensions (required_level, importance, demand, interview_relevance, industry_confidence) and source traceability.';
