-- Add attempt-limit metadata for multi-try question sessions.

alter table profiles
    add column if not exists attempt_limit integer not null default 3;

alter table profiles
    drop constraint if exists profiles_attempt_limit_check;

alter table profiles
    add constraint profiles_attempt_limit_check check (attempt_limit between 1 and 99);

alter table attempts
    add column if not exists submitted_answer text,
    add column if not exists attempts_used integer not null default 1,
    add column if not exists attempt_limit integer not null default 1,
    add column if not exists revealed boolean not null default false;

alter table attempts
    drop constraint if exists attempts_used_check;

alter table attempts
    drop constraint if exists attempts_limit_check;

alter table attempts
    add constraint attempts_used_check check (attempts_used between 1 and 99),
    add constraint attempts_limit_check check (attempt_limit between 1 and 99);

create index if not exists idx_attempts_user_revealed on attempts(user_id, revealed, created_at desc);
