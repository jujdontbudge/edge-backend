-- Rename question difficulty to level for the public product language.

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_name = 'questions'
          and column_name = 'difficulty'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_name = 'questions'
          and column_name = 'level'
    ) then
        alter table questions rename column difficulty to level;
    end if;
end $$;

alter table questions
    drop constraint if exists questions_difficulty_check;

alter table questions
    drop constraint if exists questions_level_check;

alter table questions
    add constraint questions_level_check check (level between 1 and 5);
