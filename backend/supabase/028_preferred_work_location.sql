-- INAURA preferred work location
-- Career preference only; this does not collect or infer physical location.
alter table public.profiles
  add column if not exists preferred_work_location text
    check (preferred_work_location is null or char_length(preferred_work_location) <= 160);

comment on column public.profiles.preferred_work_location is
  'Optional career preference for where the user wants to work; never GPS, IP, or browser location.';
