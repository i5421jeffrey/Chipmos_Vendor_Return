-- Run in Supabase Dashboard > SQL Editor.
-- Phase 1: private, read-only repair list for the GitHub Pages preview.
-- Add authorized users to repair_access and invite them in Authentication > Users.

create table if not exists public.repair_access (
  email text primary key check (email = lower(email))
);

create table if not exists public.repair_machines (
  machine_code text not null,
  tester_id text not null default '',
  model text not null default '',
  source_machine_number text not null,
  primary key (machine_code, tester_id)
);

create table if not exists public.repair_records (
  id uuid primary key default gen_random_uuid(),
  current_status text not null default '',
  order_status text not null default '',
  repair_month text not null default '',
  item text not null default '',
  area text not null default '',
  machine_code text not null default '',
  model text not null default '',
  tester_id text not null default '',
  board_part_code text not null default '',
  serial_no text not null default '',
  description text not null default '',
  failure_data text not null default '',
  occurred_on date,
  sent_on date,
  returned_on date,
  source_system text not null default 'repair-list',
  source_record_id text,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists repair_records_source_id_idx
  on public.repair_records (source_system, source_record_id)
  where source_record_id is not null;
create index if not exists repair_records_status_idx
  on public.repair_records (current_status, order_status);
create index if not exists repair_records_machine_idx
  on public.repair_records (machine_code, tester_id);
create index if not exists repair_records_dates_idx
  on public.repair_records (occurred_on desc);

alter table public.repair_access enable row level security;
alter table public.repair_machines enable row level security;
alter table public.repair_records enable row level security;

grant usage on schema public to authenticated;
grant select on public.repair_machines, public.repair_records to authenticated;
revoke all on public.repair_access from anon, authenticated;
revoke all on public.repair_machines, public.repair_records from anon;

create or replace function public.has_repair_access()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.repair_access a
    where a.email = lower(coalesce((select auth.jwt() ->> 'email'), ''))
  );
$$;

revoke all on function public.has_repair_access() from public;
grant execute on function public.has_repair_access() to authenticated;

drop policy if exists "Approved users can view repair machines" on public.repair_machines;
create policy "Approved users can view repair machines"
  on public.repair_machines for select to authenticated
  using ((select public.has_repair_access()));

drop policy if exists "Approved users can view repair records" on public.repair_records;
create policy "Approved users can view repair records"
  on public.repair_records for select to authenticated
  using ((select public.has_repair_access()));

-- Machine/tester pairs imported from 參考資料/machines.db.
-- Sxx entries are displayed as Fxx (T5377S); HQxx entries are T5833.
insert into public.repair_machines (machine_code, tester_id, model, source_machine_number) values
  ('HQ01', 'CMI1', 'T5833', 'HQ01'),
  ('HQ02', 'CMI2', 'T5833', 'HQ02'),
  ('HQ03', 'CMI3', 'T5833', 'HQ03'),
  ('HQ04', 'CMI4', 'T5833', 'HQ04'),
  ('HQ05', 'CMI5', 'T5833', 'HQ05'),
  ('HQ06', 'TERA1', 'T5833', 'HQ06'),
  ('HQ09', 'CM18', 'T5833', 'HQ09'),
  ('HQ10', 'CM19', 'T5833', 'HQ10'),
  ('R05', 'PMOS2', '', 'R05'),
  ('R07', 'SMIC2', '', 'R07'),
  ('R09', 'INF29', '', 'R09'),
  ('F14', 'YURA33', 'T5377S', 'S14'),
  ('F19', 'TAS05', 'T5377S', 'S19'),
  ('F20', 'TERA76', 'T5377S', 'S20'),
  ('F21', 'TERA43', 'T5377S', 'S21'),
  ('F22', 'C05M7T', 'T5377S', 'S22'),
  ('F28', 'TERA36', 'T5377S', 'S28'),
  ('F36', '', 'T5377S', 'S36'),
  ('F39', 'REX22', 'T5377S', 'S39'),
  ('F40', 'REX28', 'T5377S', 'S40'),
  ('F41', 'PSC132', 'T5377S', 'S41'),
  ('F42', 'PMOST32', 'T5377S', 'S42'),
  ('F45', 'PMOST11', 'T5377S', 'S45'),
  ('F46', 'C04M7T', 'T5377S', 'S46'),
  ('F47', 'TERA8', 'T5377S', 'S47'),
  ('F48', 'PSC112', 'T5377S', 'S48'),
  ('F49', 'PSC118', 'T5377S', 'S49'),
  ('F50', 'TERA62', 'T5377S', 'S50'),
  ('F51', 'TERA6', 'T5377S', 'S51'),
  ('F52', 'REX3', 'T5377S', 'S52'),
  ('F53', 'PSC104', 'T5377S', 'S53'),
  ('F54', 'PSC131', 'T5377S', 'S54'),
  ('F55', 'TERA93', 'T5377S', 'S55'),
  ('F56', 'TRA85', 'T5377S', 'S56'),
  ('F59', 'PMOST28', 'T5377S', 'S59'),
  ('F60', 'REX20', 'T5377S', 'S60'),
  ('F61', 'TERA98', 'T5377S', 'S61'),
  ('F62', 'REX21', 'T5377S', 'S62')
on conflict (machine_code, tester_id) do update set
  model = excluded.model,
  source_machine_number = excluded.source_machine_number;

-- Add authorized email(s), then invite the same addresses in Supabase Auth:
-- insert into public.repair_access (email)
-- values ('your-email@example.com')
-- on conflict (email) do nothing;
