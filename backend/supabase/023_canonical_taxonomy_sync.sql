-- INAURA canonical taxonomy sync (Phase 8)
-- Safe/idempotent: canonical_name is the stable key, so existing skill UUIDs
-- and all foreign-key references are preserved.
-- The Python RAW_TAXONOMY remains the authoring source; this migration brings
-- the database representation up to date for the mobile skills that were
-- previously missing from 005/007.

insert into public.skills
  (canonical_name, display_name, category, aliases, description)
values
  ('android', 'Android', 'Mobile', array['android', 'android dev', 'android development', 'android sdk'], 'Native Android mobile application development and lifecycle management'),
  ('ios', 'iOS', 'Mobile', array['ios', 'ios dev', 'ios development', 'ios sdk', 'uikit', 'swiftui'], 'Native iOS mobile application development using Apple platforms'),
  ('flutter', 'Flutter', 'Mobile', array['flutter', 'dart', 'flutter dev', 'flutter development', 'flutter developer', 'cross-platform flutter'], 'Cross-platform UI toolkit by Google for mobile, web, and desktop'),
  ('react_native', 'React Native', 'Mobile', array['react native', 'react-native', 'react native development', 'react native developer', 'rn'], 'Cross-platform native mobile application framework based on React'),
  ('kotlin', 'Kotlin', 'Programming', array['kotlin', 'kotlinlang', 'kotlin programming'], 'Modern statically typed programming language for Android and server-side development'),
  ('swift', 'Swift', 'Programming', array['swift', 'swiftlang', 'swift programming'], 'Fast, safe, modern programming language for iOS, macOS, and beyond')
on conflict (canonical_name) do update set
  display_name = excluded.display_name,
  category = excluded.category,
  aliases = excluded.aliases,
  description = excluded.description,
  updated_at = now();

comment on table public.skills is
  'Canonical taxonomy synchronized from backend/app/services/skill_taxonomy.py; canonical_name is the stable slug and aliases are lookup-only.';
