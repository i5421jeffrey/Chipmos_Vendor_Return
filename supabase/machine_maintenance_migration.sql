-- Create the independent machine-maintenance module.
-- The machine roster intentionally starts empty; import the user's new roster
-- only after it has been provided and reviewed.
begin;

create table if not exists public.machine_maintenance_machines (
  id uuid primary key default gen_random_uuid(),
  machine_code text not null check (machine_code = btrim(machine_code) and machine_code <> ''),
  machine_name text not null default '',
  machine_serial text not null default '',
  model text not null default '',
  area text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists machine_maintenance_machines_code_idx
  on public.machine_maintenance_machines (machine_code);

create table if not exists public.machine_maintenance_cases (
  id uuid primary key default gen_random_uuid(),
  machine_id uuid not null references public.machine_maintenance_machines(id) on update cascade on delete restrict,
  fault_date date,
  issue text not null check (btrim(issue) <> ''),
  description text not null default '',
  status text not null default '待處理' check (status in ('待處理', '維修中', '待確認', '已結案')),
  priority text not null default '一般' check (priority in ('一般', '高')),
  owner_vendor text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  closed_at timestamptz
);

create index if not exists machine_maintenance_cases_machine_date_idx
  on public.machine_maintenance_cases (machine_id, fault_date desc, created_at desc);
create index if not exists machine_maintenance_cases_status_updated_idx
  on public.machine_maintenance_cases (status, updated_at desc);

create table if not exists public.machine_maintenance_events (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.machine_maintenance_cases(id) on update cascade on delete cascade,
  event_type text not null check (event_type in ('created', 'status_changed')),
  from_status text,
  to_status text not null,
  created_at timestamptz not null default now()
);
create index if not exists machine_maintenance_events_case_date_idx
  on public.machine_maintenance_events (case_id, created_at desc);

create table if not exists public.machine_maintenance_attachments (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.machine_maintenance_cases(id) on update cascade on delete cascade,
  storage_path text not null unique,
  filename text not null,
  file_size bigint not null check (file_size > 0 and file_size <= 5242880),
  content_type text not null default 'application/octet-stream',
  created_at timestamptz not null default now(),
  check (filename ~* '\.(pdf|png|jpe?g|txt|asc)$')
);
create index if not exists machine_maintenance_attachments_case_idx
  on public.machine_maintenance_attachments (case_id, created_at);

create or replace function public.set_machine_maintenance_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at := now();
  if tg_table_name = 'machine_maintenance_cases' then
    if new.status = '已結案' then
      new.closed_at := coalesce(new.closed_at, now());
    else
      new.closed_at := null;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists machine_maintenance_machines_set_updated_at on public.machine_maintenance_machines;
create trigger machine_maintenance_machines_set_updated_at
before update on public.machine_maintenance_machines
for each row execute function public.set_machine_maintenance_updated_at();

drop trigger if exists machine_maintenance_cases_set_updated_at on public.machine_maintenance_cases;
create trigger machine_maintenance_cases_set_updated_at
before insert or update on public.machine_maintenance_cases
for each row execute function public.set_machine_maintenance_updated_at();

create or replace function public.log_machine_maintenance_case_event()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.machine_maintenance_events (case_id, event_type, to_status)
    values (new.id, 'created', new.status);
  elsif new.status is distinct from old.status then
    insert into public.machine_maintenance_events (case_id, event_type, from_status, to_status)
    values (new.id, 'status_changed', old.status, new.status);
  end if;
  return new;
end;
$$;

drop trigger if exists machine_maintenance_cases_log_created on public.machine_maintenance_cases;
create trigger machine_maintenance_cases_log_created
after insert on public.machine_maintenance_cases
for each row execute function public.log_machine_maintenance_case_event();

drop trigger if exists machine_maintenance_cases_log_status on public.machine_maintenance_cases;
create trigger machine_maintenance_cases_log_status
after update of status on public.machine_maintenance_cases
for each row execute function public.log_machine_maintenance_case_event();

alter table public.machine_maintenance_machines enable row level security;
alter table public.machine_maintenance_cases enable row level security;
alter table public.machine_maintenance_events enable row level security;
alter table public.machine_maintenance_attachments enable row level security;

grant usage on schema public to anon, authenticated;
grant select on public.machine_maintenance_machines to anon, authenticated;
grant select, insert, update on public.machine_maintenance_cases to anon, authenticated;
grant select on public.machine_maintenance_events to anon, authenticated;
grant select, insert on public.machine_maintenance_attachments to anon, authenticated;

drop policy if exists "Public can read maintenance machines" on public.machine_maintenance_machines;
create policy "Public can read maintenance machines" on public.machine_maintenance_machines
  for select to public using (true);

drop policy if exists "Public can read maintenance cases" on public.machine_maintenance_cases;
create policy "Public can read maintenance cases" on public.machine_maintenance_cases
  for select to public using (true);
drop policy if exists "Public can create maintenance cases" on public.machine_maintenance_cases;
create policy "Public can create maintenance cases" on public.machine_maintenance_cases
  for insert to public with check (true);
drop policy if exists "Public can update maintenance cases" on public.machine_maintenance_cases;
create policy "Public can update maintenance cases" on public.machine_maintenance_cases
  for update to public using (true) with check (true);

drop policy if exists "Public can read maintenance events" on public.machine_maintenance_events;
create policy "Public can read maintenance events" on public.machine_maintenance_events
  for select to public using (true);

drop policy if exists "Public can read maintenance attachments" on public.machine_maintenance_attachments;
create policy "Public can read maintenance attachments" on public.machine_maintenance_attachments
  for select to public using (true);
drop policy if exists "Public can add maintenance attachments" on public.machine_maintenance_attachments;
create policy "Public can add maintenance attachments" on public.machine_maintenance_attachments
  for insert to public with check (
    file_size > 0
    and file_size <= 5242880
    and filename ~* '\.(pdf|png|jpe?g|txt|asc)$'
  );

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'machine-maintenance-files',
  'machine-maintenance-files',
  true,
  5242880,
  array['application/pdf', 'image/png', 'image/jpeg', 'text/plain', 'application/octet-stream']::text[]
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Public can read machine maintenance files" on storage.objects;
create policy "Public can read machine maintenance files" on storage.objects
  for select to public using (bucket_id = 'machine-maintenance-files');
drop policy if exists "Public can upload machine maintenance files" on storage.objects;
create policy "Public can upload machine maintenance files" on storage.objects
  for insert to public with check (
    bucket_id = 'machine-maintenance-files'
    and name ~* '\.(pdf|png|jpe?g|txt|asc)$'
  );

commit;
