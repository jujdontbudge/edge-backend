-- Edge schema — run in Supabase SQL Editor

-- Profiles (extends Supabase auth.users)
create table if not exists profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    display_name text,
    daily_goal integer not null default 7,
    attempt_limit integer not null default 3 check (attempt_limit between 1 and 99),
    target_firms text[] default '{}',
    interview_timeline text,
    onboarding_complete boolean not null default false,
    push_token text,
    reminder_time time default '19:00:00',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table profiles enable row level security;
create policy "Users read own profile" on profiles for select using (auth.uid() = id);
create policy "Users update own profile" on profiles for update using (auth.uid() = id);
create policy "Users insert own profile" on profiles for insert with check (auth.uid() = id);

-- Auto-create profile on signup
create or replace function handle_new_user()
returns trigger as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email)
    on conflict (id) do nothing;
    return new;
end;
$$ language plpgsql security definer set search_path = public;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure handle_new_user();

-- Questions
create table if not exists questions (
    id text primary key,
    prompt text not null,
    topic text not null,
    level integer not null check (level between 1 and 5),
    answer_type text not null check (answer_type in ('numeric', 'self_graded')),
    numeric_answer double precision,
    tolerance_percent double precision,
    tolerance_absolute double precision,
    is_exact_integer boolean not null default false,
    solution_steps jsonb not null default '[]',
    firm_style text,
    find_expression text,
    version integer not null default 1,
    created_at timestamptz not null default now()
);

-- Daily sets
create table if not exists daily_sets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    date date not null,
    question_ids text[] not null,
    created_at timestamptz not null default now(),
    unique(user_id, date)
);

alter table daily_sets enable row level security;
create policy "Users read own sets" on daily_sets for select using (auth.uid() = user_id);
create policy "Service inserts sets" on daily_sets for insert with check (true);

create index idx_daily_sets_user_date on daily_sets(user_id, date);

-- Attempts
create table if not exists attempts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    question_id text not null references questions(id),
    numeric_answer double precision,
    self_grade text check (self_grade in ('got_it', 'did_not_get_it')),
    submitted_answer text,
    is_correct boolean not null,
    solve_time_seconds integer not null default 0,
    attempts_used integer not null default 1 check (attempts_used between 1 and 99),
    attempt_limit integer not null default 1 check (attempt_limit between 1 and 99),
    revealed boolean not null default false,
    question_version integer not null default 1,
    created_at timestamptz not null default now()
);

alter table attempts enable row level security;
create policy "Users read own attempts" on attempts for select using (auth.uid() = user_id);
create policy "Service inserts attempts" on attempts for insert with check (true);

create index idx_attempts_user on attempts(user_id, created_at desc);
create index idx_attempts_question on attempts(question_id);

-- Streak freezes
create table if not exists streak_freezes (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    freeze_date date not null,
    created_at timestamptz not null default now(),
    unique(user_id, freeze_date)
);

alter table streak_freezes enable row level security;
create policy "Users read own freezes" on streak_freezes for select using (auth.uid() = user_id);

-- Tutor messages
create table if not exists tutor_messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    conversation_id uuid not null,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    created_at timestamptz not null default now()
);

alter table tutor_messages enable row level security;
create policy "Users read own messages" on tutor_messages for select using (auth.uid() = user_id);
create policy "Service inserts messages" on tutor_messages for insert with check (true);

create index idx_tutor_conv on tutor_messages(conversation_id, created_at);
create index idx_tutor_user_date on tutor_messages(user_id, created_at);

-- Subscription status (synced from RevenueCat webhooks)
create table if not exists subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    revenuecat_id text,
    entitlement text not null default 'free',
    product_id text,
    expires_at timestamptz,
    is_active boolean not null default false,
    updated_at timestamptz not null default now()
);

alter table subscriptions enable row level security;
create policy "Users read own sub" on subscriptions for select using (auth.uid() = user_id);

create unique index idx_sub_user on subscriptions(user_id);
