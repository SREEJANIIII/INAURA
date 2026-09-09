-- INAURA Canonical Skills & Taxonomy Extension — Phase 4E
-- Run in Supabase SQL Editor after 006_roadmap.sql
-- Updates aliases for PostgreSQL, DSA, REST APIs, and inserts canonical skills

-- 1. Update SQL entry so PostgreSQL and MySQL have distinct canonical identities
update public.skills
set aliases = array['sql','relational database','relational databases','structured query language']
where canonical_name = 'sql';

-- 2. Insert new canonical skills
insert into public.skills (canonical_name, display_name, category, aliases, description) values
  ('postgresql', 'PostgreSQL', 'Databases', array['postgres','postgresql','psql','postgre'], 'Powerful open-source object-relational database'),
  ('mysql', 'MySQL', 'Databases', array['mysql','my-sql'], 'Open-source relational database management system'),
  ('mongodb', 'MongoDB', 'Databases', array['mongodb','mongo','nosql mongodb'], 'Document-oriented NoSQL database'),
  ('redis', 'Redis', 'Databases', array['redis','redis cache','in-memory store'], 'In-memory data store and cache'),
  ('nodejs', 'Node.js', 'Backend', array['node','node.js','nodejs','node js'], 'JavaScript runtime environment'),
  ('express', 'Express', 'Backend', array['express','express.js','expressjs'], 'Web application framework for Node.js'),
  ('spring_boot', 'Spring Boot', 'Backend', array['spring boot','springboot','spring-boot','spring'], 'Enterprise Java backend microservice framework'),
  ('nextjs', 'Next.js', 'Frontend', array['next.js','nextjs','next js','next'], 'Full-stack React framework'),
  ('html', 'HTML', 'Frontend', array['html','html5'], 'Hypertext markup language'),
  ('css', 'CSS', 'Frontend', array['css','css3','tailwind'], 'Cascading style sheets for web styling'),
  ('oop', 'OOP', 'Computer Science', array['oop','oops','object oriented programming','object-oriented programming'], 'Object-oriented programming concepts'),
  ('dbms', 'DBMS', 'Computer Science', array['dbms','database management','rdbms'], 'Database management systems and ACID transactions'),
  ('operating_systems', 'Operating Systems', 'Computer Science', array['operating systems','operating system','os fundamentals'], 'Operating systems and concurrency'),
  ('computer_networks', 'Computer Networks', 'Computer Science', array['computer networks','computer networking','tcp/ip','networking fundamentals'], 'Computer networks and protocols'),
  ('github_actions', 'GitHub Actions', 'DevOps/Cloud', array['github actions','gh actions','github action','gha'], 'CI/CD automation for GitHub repositories'),
  ('aws', 'AWS', 'DevOps/Cloud', array['aws','amazon web services'], 'Amazon Web Services cloud platform'),
  ('gcp', 'GCP', 'DevOps/Cloud', array['gcp','google cloud','google cloud platform'], 'Google Cloud Platform')
on conflict (canonical_name) do update set
  display_name = excluded.display_name,
  category = excluded.category,
  aliases = excluded.aliases,
  description = excluded.description,
  updated_at = now();

-- 3. Ensure React, DSA, REST APIs have clean aliases
update public.skills
set aliases = array['react','react.js','reactjs','react-js','react js'],
    display_name = 'React'
where canonical_name = 'react';

update public.skills
set aliases = array['dsa','algorithms','data structures','data structures & algorithms','data structures and algorithms'],
    display_name = 'Data Structures & Algorithms'
where canonical_name = 'dsa';

update public.skills
set aliases = array['rest','rest api','rest apis','api','restful','fastapi','fast_api'],
    display_name = 'REST APIs'
where canonical_name = 'rest_apis';

comment on table public.skills is 'Canonical skill taxonomy — single source of truth for normalized skill identities across INAURA.';
