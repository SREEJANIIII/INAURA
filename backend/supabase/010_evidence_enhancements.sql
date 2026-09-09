-- INAURA Evidence Intelligence Enhancements — Migration 010
-- Run in Supabase SQL Editor after 009_industry_intelligence.sql
-- Adds student_contribution column to projects table to support specific personal attribution

do $$
begin
  -- 1. student_contribution column on projects
  if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='projects' and column_name='student_contribution') then
    alter table public.projects add column student_contribution text;
  end if;
end $$;

-- Index github_url on projects for fast cross-source deduplication with evidence table
create index if not exists idx_projects_github_url on public.projects (github_url) where github_url is not null;

comment on column public.projects.student_contribution is 'Specific personal contributions, features engineered, or modules owned by the student in team or solo projects.';
