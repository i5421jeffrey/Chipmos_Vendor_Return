-- Run this in Supabase Dashboard > SQL Editor.
-- Before inviting editors, add their exact email addresses to return_editors below.

create table if not exists public.return_topics (
  id text primary key,
  label text not null,
  title text not null,
  stance text not null,
  vendor text not null,
  reply text not null,
  sort_order integer not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists public.return_editors (
  email text primary key check (email = lower(email))
);

alter table public.return_topics enable row level security;
alter table public.return_editors enable row level security;

grant usage on schema public to anon, authenticated;
grant select on public.return_topics to anon, authenticated;
grant insert, update on public.return_topics to authenticated;
revoke all on public.return_editors from anon, authenticated;

drop policy if exists "Anyone can view return topics" on public.return_topics;
create policy "Anyone can view return topics"
  on public.return_topics for select to anon, authenticated
  using (true);

create or replace function public.is_return_editor()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.return_editors e
    where e.email = lower((select auth.jwt() ->> 'email'))
  );
$$;

revoke all on function public.is_return_editor() from public;
grant execute on function public.is_return_editor() to authenticated;

drop policy if exists "Editors can add return topics" on public.return_topics;
create policy "Editors can add return topics"
  on public.return_topics for insert to authenticated
  with check ((select public.is_return_editor()));

drop policy if exists "Editors can update return topics" on public.return_topics;
create policy "Editors can update return topics"
  on public.return_topics for update to authenticated
  using ((select public.is_return_editor()))
  with check ((select public.is_return_editor()));

-- Add each collaborator's email here (lowercase), then invite the same address
-- in Authentication > Users. Example:
-- insert into public.return_editors(email)
-- values ('you@example.com')
-- on conflict (email) do nothing;

-- Enable Realtime updates for collaborators currently viewing the page.
do $$
begin
  if not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'return_topics'
  ) then
    alter publication supabase_realtime add table public.return_topics;
  end if;
end;
$$;
