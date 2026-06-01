-- Add focus_topics column to profiles for per-user topic filtering
alter table profiles add column if not exists focus_topics text[] default '{}';
