-- Tutor conversation metadata for titles and manual renames.

create table if not exists tutor_conversations (
    id uuid primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    title text not null default 'Tutor chat',
    title_source text not null default 'auto' check (title_source in ('auto', 'manual')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table tutor_conversations enable row level security;
create policy "Users read own tutor conversations" on tutor_conversations for select using (auth.uid() = user_id);
create policy "Users update own tutor conversations" on tutor_conversations for update using (auth.uid() = user_id);
create policy "Users insert own tutor conversations" on tutor_conversations for insert with check (auth.uid() = user_id);

create index if not exists idx_tutor_conversations_user_updated
    on tutor_conversations(user_id, updated_at desc);
