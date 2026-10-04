-- Phase 1 setup + import for the public repair-management preview.
-- WARNING: this intentionally allows unauthenticated public read/write/delete.
-- Anyone with the URL can view/change/delete records and upload/delete fail logs.
-- Run once in Supabase Dashboard > SQL Editor after reviewing this warning.
-- After setup, run supabase/repair_history_migration.sql once to enable PASS/FAIL verification and retries.

create table if not exists public.repair_machines (
  machine_code text not null,
  tester_id text not null default '',
  model text not null default '',
  source_machine_number text not null,
  machine_serial text not null default '',
  machine_name text not null default '',
  primary key (machine_code, tester_id)
);

create table if not exists public.repair_records (
  id uuid primary key default gen_random_uuid(),
  current_status text not null default '待送修',
  order_status text not null default '',
  is_opened boolean,
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
  closed_on date,
  retry_of_record_id uuid references public.repair_records(id) on delete set null,
  source_system text not null default 'web',
  source_record_id text,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.repair_records add column if not exists is_opened boolean;
alter table public.repair_records add column if not exists source_system text not null default 'repair-list';
alter table public.repair_records add column if not exists source_record_id text;
alter table public.repair_records add column if not exists version integer not null default 1;
alter table public.repair_records add column if not exists created_at timestamptz not null default now();
alter table public.repair_records add column if not exists updated_at timestamptz not null default now();
alter table public.repair_records add column if not exists closed_on date;
alter table public.repair_records add column if not exists retry_of_record_id uuid references public.repair_records(id) on delete set null;
alter table public.repair_records alter column source_system set default 'web';

-- Normalize statuses from the original sheet. Preserve the original order-status text.
alter table public.repair_records drop constraint if exists repair_records_current_status_check;
update public.repair_records
set current_status = case trim(coalesce(current_status, ''))
  when '' then '待送修'
  when '待送修' then '待送修'
  when '已送' then '已送修'
  when '已送修' then '已送修'
  when '取回驗證中' then '取回驗證'
  when '取回驗證' then '取回驗證'
  when '結案' then '結案（PASS）'
  when '已結案' then '結案（PASS）'
  when '結案（PASS）' then '結案（PASS）'
  when '結案（FAIL）' then '結案（FAIL）'
  else '待送修'
end;
update public.repair_records
set is_opened = (order_status = '已開單')
where is_opened is null;
alter table public.repair_records alter column current_status set default '待送修';
alter table public.repair_records alter column is_opened set default false;
alter table public.repair_records alter column is_opened set not null;

alter table public.repair_records
  add constraint repair_records_current_status_check
  check (current_status in ('待送修', '已送修', '取回驗證', '結案（PASS）', '結案（FAIL）'));
alter table public.repair_records
  drop constraint if exists repair_records_serial_no_format_check;
alter table public.repair_records
  add constraint repair_records_serial_no_format_check
  check (serial_no = '' or serial_no ~ '^[0-9]{9}$');

create table if not exists public.repair_attachments (
  id uuid primary key default gen_random_uuid(),
  repair_record_id uuid not null unique references public.repair_records(id) on delete cascade,
  storage_path text not null unique,
  filename text not null check (filename ~* '\.(txt|asc)$'),
  file_size integer not null check (file_size > 0 and file_size <= 5242880),
  content_type text not null default 'text/plain',
  created_at timestamptz not null default now()
);

create index if not exists repair_records_status_idx
  on public.repair_records (current_status, is_opened);
create index if not exists repair_records_machine_idx
  on public.repair_records (machine_code, tester_id);
create index if not exists repair_records_dates_idx
  on public.repair_records (occurred_on desc);
create index if not exists repair_records_serial_history_idx
  on public.repair_records (serial_no, closed_on, created_at);
create index if not exists repair_records_retry_idx
  on public.repair_records (retry_of_record_id);
create unique index if not exists repair_records_source_id_idx
  on public.repair_records (source_system, source_record_id)
  where source_record_id is not null;

create or replace function public.set_repair_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  new.version = old.version + 1;
  return new;
end;
$$;

drop trigger if exists repair_records_set_updated_at on public.repair_records;
create trigger repair_records_set_updated_at
before update on public.repair_records
for each row execute function public.set_repair_updated_at();

alter table public.repair_machines enable row level security;
alter table public.repair_records enable row level security;
alter table public.repair_attachments enable row level security;

grant usage on schema public to anon, authenticated;
grant select on public.repair_machines to anon, authenticated;
grant select, insert, update, delete on public.repair_records to anon, authenticated;
grant select, insert, delete on public.repair_attachments to anon, authenticated;

drop policy if exists "Approved users can view repair machines" on public.repair_machines;
drop policy if exists "Public can manage repair machines" on public.repair_machines;
create policy "Public can read repair machines" on public.repair_machines
  for select to public using (true);

drop policy if exists "Approved users can view repair records" on public.repair_records;
drop policy if exists "Public can manage repair records" on public.repair_records;
drop policy if exists "Public can read repair records" on public.repair_records;
drop policy if exists "Public can add repair records" on public.repair_records;
drop policy if exists "Public can update repair records" on public.repair_records;
create policy "Public can read repair records" on public.repair_records
  for select to public using (true);
create policy "Public can add repair records" on public.repair_records
  for insert to public with check (true);
create policy "Public can update repair records" on public.repair_records
  for update to public using (true) with check (true);
drop policy if exists "Public can delete repair records" on public.repair_records;
create policy "Public can delete repair records" on public.repair_records
  for delete to public using (true);

drop policy if exists "Public can manage repair attachments" on public.repair_attachments;
drop policy if exists "Public can read repair attachments" on public.repair_attachments;
drop policy if exists "Public can add repair attachments" on public.repair_attachments;
drop policy if exists "Public can delete repair attachments" on public.repair_attachments;
create policy "Public can read repair attachments" on public.repair_attachments
  for select to public using (true);
create policy "Public can add repair attachments" on public.repair_attachments
  for insert to public with check (
    filename ~* '\.(txt|asc)$'
    and file_size > 0
    and file_size <= 5242880
  );
create policy "Public can delete repair attachments" on public.repair_attachments
  for delete to public using (true);

-- A public bucket is required for no-login downloads. Its file size cap is also
-- enforced by Storage, not only by the page's client-side validation.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'repair-fail-logs',
  'repair-fail-logs',
  true,
  5242880,
  array['text/plain', 'application/octet-stream', 'text/x-asm', 'application/x-asm']::text[]
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Public can read repair fail logs" on storage.objects;
drop policy if exists "Public can upload repair fail logs" on storage.objects;
drop policy if exists "Public can delete repair fail logs" on storage.objects;
create policy "Public can read repair fail logs" on storage.objects
  for select to public using (bucket_id = 'repair-fail-logs');
create policy "Public can upload repair fail logs" on storage.objects
  for insert to public with check (
    bucket_id = 'repair-fail-logs'
    and name ~* '\.(txt|asc)$'
  );
create policy "Public can delete repair fail logs" on storage.objects
  for delete to public using (bucket_id = 'repair-fail-logs');

-- Machine/tester pairs from machines.db; Sxx is shown as Fxx for T5377S.
-- Run supabase/machine_data_20261003.sql after setup to populate machine serial/name from the CSV.
insert into public.repair_machines (machine_code, tester_id, model, source_machine_number) values
  ('HQ01', 'CMI1', 'T5833', 'HQ01'), ('HQ02', 'CMI2', 'T5833', 'HQ02'),
  ('HQ03', 'CMI3', 'T5833', 'HQ03'), ('HQ04', 'CMI4', 'T5833', 'HQ04'),
  ('HQ05', 'CMI5', 'T5833', 'HQ05'), ('HQ06', 'TERA1', 'T5833', 'HQ06'),
  ('HQ09', 'CM18', 'T5833', 'HQ09'), ('HQ10', 'CM19', 'T5833', 'HQ10'),
  ('R5', 'PMOS2', 'T5377', 'R05'), ('R7', 'SMIC2', 'T5377', 'R07'), ('R9', 'INF29', 'T5377', 'R09'),
  ('F14', 'YURA33', 'T5377S', 'S14'), ('F19', 'TAS05', 'T5377S', 'S19'),
  ('F20', 'TERA76', 'T5377S', 'S20'), ('F21', 'TERA43', 'T5377S', 'S21'),
  ('F22', 'C05M7T', 'T5377S', 'S22'), ('F28', 'TERA36', 'T5377S', 'S28'),
  ('F36', '', 'T5377S', 'S36'), ('F39', 'REX22', 'T5377S', 'S39'),
  ('F40', 'REX28', 'T5377S', 'S40'), ('F41', 'PSC132', 'T5377S', 'S41'),
  ('F42', 'PMOST32', 'T5377S', 'S42'), ('F45', 'PMOST11', 'T5377S', 'S45'),
  ('F46', 'C04M7T', 'T5377S', 'S46'), ('F47', 'TERA8', 'T5377S', 'S47'),
  ('F48', 'PSC112', 'T5377S', 'S48'), ('F49', 'PSC118', 'T5377S', 'S49'),
  ('F50', 'TERA62', 'T5377S', 'S50'), ('F51', 'TERA6', 'T5377S', 'S51'),
  ('F52', 'REX3', 'T5377S', 'S52'), ('F53', 'PSC104', 'T5377S', 'S53'),
  ('F54', 'PSC131', 'T5377S', 'S54'), ('F55', 'TERA93', 'T5377S', 'S55'),
  ('F56', 'TRA85', 'T5377S', 'S56'), ('F59', 'PMOST28', 'T5377S', 'S59'),
  ('F60', 'REX20', 'T5377S', 'S60'), ('F61', 'TERA98', 'T5377S', 'S61'),
  ('F62', 'REX21', 'T5377S', 'S62')
on conflict (machine_code, tester_id) do update set
  model = excluded.model,
  source_machine_number = excluded.source_machine_number;



-- Imported from 參考資料/送修清單.xlsx, worksheet 2026.
-- 46 records with at least one used field. Whitespace-only rows are skipped.
-- Blank current status -> 待送修; 已送 -> 已送修; 取回驗證中 -> 取回驗證; legacy closed -> 結案（PASS）.
-- is_opened is checked only for exact 已開單; order_status retains the original text.
insert into public.repair_records (
  current_status, order_status, is_opened, repair_month, item, area,
  machine_code, model, tester_id, board_part_code, serial_no, description,
  failure_data, occurred_on, sent_on, returned_on, source_system, source_record_id
) values
  ('結案（PASS）', '已開單', true, '', '', 'CP', '', '', '', 'BIR-030083', '2352846', 'I/O PE', 'RTE12367', NULL, '2026-03-23', '2026-04-17', 'repair-list-2026', '2026-row-2'),
  ('結案（PASS）', '已開單', true, '', '', 'CP', '', '', '', 'BIR-030083', '2650046', 'I/O PE', 'RTE12367', NULL, '2026-03-23', '2026-04-17', 'repair-list-2026', '2026-row-3'),
  ('取回驗證', '已開單', true, '202606', 'W24', 'CP', 'R9', 'T5377', 'INF29', 'BIR-030083', '2570821', 'I/O PE', '5602 TH(6) 97G5 FAIL', '2026-05-22', '2026-06-09', NULL, 'repair-list-2026', '2026-row-5'),
  ('取回驗證', '已開單', true, '202606', 'W24', 'CP', 'R9', 'T5377', 'INF29', 'BIR-030083', '2674288', 'I/O PE', '5605 TH(6) 49 H1 33G1 FAIL', '2026-05-22', '2026-06-09', NULL, 'repair-list-2026', '2026-row-6'),
  ('結案（PASS）', '已開單', true, '202606', 'W24', 'CP', 'R9', 'T5377', 'INF29', 'BGR-030182', '2779082', 'FMRA', '電容脫落', '2026-06-09', '2026-06-10', NULL, 'repair-list-2026', '2026-row-7'),
  ('結案（PASS）', '已開單', true, '202606', 'W24', 'CP', 'R9', 'T5377', 'INF29', 'BGR-030181', '2327350', 'FM CONT', '底部PIN腳變形', '2026-06-09', '2026-06-10', NULL, 'repair-list-2026', '2026-row-8'),
  ('已送修', '已開單', true, '202606', 'W24', 'CP', 'F47', 'T5377S', 'TERA8', 'BGR-026902', '2247045', 'DC BOARD', 'Diag DC CH63 SLOT3 FAIL', '2026-06-09', NULL, NULL, 'repair-list-2026', '2026-row-10'),
  ('已送修', '已開單', true, '202606', 'W24', 'CP', 'F49', 'T5377S', 'PSC11', 'WBL-H3610178TP6A', '2563178', 'TP6B', 'RTE 210, 無法進入test mode', '2026-06-10', NULL, NULL, 'repair-list-2026', '2026-row-11'),
  ('取回驗證', '已開單', true, '202606', 'W26', 'CP', 'F51', 'T5377S', 'TERA6', 'BIR-030083', '2594383', 'I/O PE', '12367, 103 STN1 F1', '2026-06-13', NULL, '2026-08-03', 'repair-list-2026', '2026-row-13'),
  ('取回驗證', '已開單', true, '202606', 'W26', 'CP', 'F51', 'T5377S', 'TERA6', 'BIR-030083', '2384849', 'I/O PE', '12367, 99 STN1 B5', '2026-06-16', NULL, '2026-08-03', 'repair-list-2026', '2026-row-14'),
  ('結案（PASS）', '已開單', true, '202606', 'W26', 'CP', 'F19', 'T5377S', 'TAS05', 'BPR-030837', '2736581', 'DR PE', '底部PIN腳變形', '2026-06-17', NULL, NULL, 'repair-list-2026', '2026-row-15'),
  ('取回驗證', '已開單', true, '202606', 'W26', 'CP', 'F19', 'T5377S', 'TAS05', 'BPR-030837', '2785113', 'DR PE', 'test 5307 th(3) PIN8 F5 1E5', '2026-06-17', NULL, '2026-08-03', 'repair-list-2026', '2026-row-16'),
  ('取回驗證', '已開單', true, '202606', 'W26', 'CP', 'F51', 'T5377S', 'TERA6', 'BIR-030083', '2778014', 'I/O PE', '12367, 103 STN1 G1', '2026-06-18', NULL, '2026-08-03', 'repair-list-2026', '2026-row-17'),
  ('結案（PASS）', '已開單', true, '202607', 'W27', 'CP', 'R7', 'T5377', 'SMIC2', 'BIR-026380', '2323398', 'PDS', '底部PIN腳變形', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-19'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'F49', 'T5377S', 'PSC118', 'BIR-030182', '2601415', 'FMRA', 'RTE 210, 無法進test mode', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-20'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'R7', 'T5377', 'SMIC2', 'BIR-026805', '2379829', 'DR PE', '5302 TH(3) 25 G1 FAIL', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-21'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'R9', 'T5377', 'INF29', 'BIR-026805', '2304465', 'DR PE', '快速接頭漏液', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-22'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'R9', 'T5377', 'INF29', 'BIR-026805', '2218339', 'DR PE', '快速接頭漏液', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-23'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR-026903', '2716515', 'PPS', '1-5-33 TEST 254 DPU(190) 189 Fail', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-24'),
  ('已送修', '已開單', true, '202607', 'W27', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR-026903', '2423361', 'PPS', 'Auto Shutdown AC2:20000032 heat sink alarm(PPS TH1)', '2026-07-02', '2026-07-02', NULL, 'repair-list-2026', '2026-row-25'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'F21', 'T5377S', 'TERA43', 'BPR-030837', '2530050', 'DR PE', 'TEST 5302 TH(3) DR 1G1 FAIL', '2026-07-10', NULL, NULL, 'repair-list-2026', '2026-row-27'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'R9', 'T5377', 'INF29', 'BIR-026805', '2292170', 'DR PE', '快速接頭漏液', '2026-07-10', NULL, NULL, 'repair-list-2026', '2026-row-28'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR-030083', '2808386', 'I/O PE', '12367, 98 STN1 A5', '2026-07-10', NULL, NULL, 'repair-list-2026', '2026-row-29'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'F54', 'T5377S', 'PSC131', 'BIR-030083', '2489871', 'I/O PE', 'TH(8) 33G5 FAIL', '2026-07-04', '2026-07-30', NULL, 'repair-list-2026', '2026-row-31'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'F20', 'T5377S', 'TERA76', 'BIR-030083', '2776191', 'I/O PE', '12367, 108 STN1 A7', '2026-07-22', '2026-07-30', NULL, 'repair-list-2026', '2026-row-32'),
  ('已送修', '已開單', true, '202607', '', 'CP', 'F47', 'T5377S', 'TERA8', 'BIR-030083', '2781849', 'I/O PE', '12367, 105 STN1 B5', '2026-07-23', '2026-07-30', NULL, 'repair-list-2026', '2026-row-33'),
  ('已送修', '已開單', true, '202608', '', 'CP', 'NA', 'NA', '', '', '', 'BLADE1500', '電容膨脹，無法開機', '2026-08-03', '2026-08-06', NULL, 'repair-list-2026', '2026-row-35'),
  ('取回驗證', '已開單', true, '202608', '', 'CP', 'NA', 'NA', '', '', '', 'BLADE1500(主板)', '電容膨脹，無法開機', '2026-08-03', '2026-08-06', NULL, 'repair-list-2026', '2026-row-36'),
  ('取回驗證', '已開單', true, '202609', '', 'CP', 'NA', 'T5377S', '', '', '', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-38'),
  ('取回驗證', '已開單', true, '202609', '', 'CP', 'NA', 'T5377S', '', '', '', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-39'),
  ('取回驗證', '已開單', true, '202609', '', 'CP', 'F19', 'T5377S', '', '', '', 'MainAC', 'short無法開電', NULL, NULL, NULL, 'repair-list-2026', '2026-row-41'),
  ('已送修', '已開單', true, '202609', '', 'CP', 'R5', 'T5377', 'PMOS2', 'BIR-030083', '2750323', 'I/O PE', 'ALPG(58)', '2026-08-26', '2026-09-10', NULL, 'repair-list-2026', '2026-row-43'),
  ('已送修', '已開單', true, '202609', '', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR-026903', '2716515', 'PPS', '1-5-33 TEST 254 DPU(190) 189', '2026-06-25', '2026-09-10', NULL, 'repair-list-2026', '2026-row-44'),
  ('已送修', '已開單', true, '202609', '', 'CP', 'F21', 'T5377S', 'TERA43', 'BIR-030083', '2570821', 'I/O PE', 'INIT 97,105CH Fail,TEST 5302TH(3) DR OFFSET&GAIN ADJUST CHECK', '2026-07-09', '2026-09-10', NULL, 'repair-list-2026', '2026-row-45'),
  ('待送修', '已開單', true, '202609', '', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR-026903', '2423361', 'PPS', '會導致tester auto shutdown (PPS過熱)', '2026-07-09', '2026-09-10', NULL, 'repair-list-2026', '2026-row-46'),
  ('待送修', '已開單', true, '202609', '', 'CP', 'F50', 'T5377S', 'TERA62', 'BIR030083', '2508384', 'I/O PE', '98 STN1 A5 (pbdata fail)', '2026-07-09', '2026-09-10', NULL, 'repair-list-2026', '2026-row-47'),
  ('待送修', '再度送修 先不簽', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2681404', '2G Module', '20260914_2681404', NULL, NULL, NULL, 'repair-list-2026', '2026-row-49'),
  ('待送修', 'fail log沒抓到', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2640889', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-50'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2778832', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-51'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2778815', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-52'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2828626', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-53'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2822060', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-54'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2703643', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-55'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2778796', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-56'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2778817', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-57'),
  ('待送修', '', false, '202609', '', 'CP', 'F59', 'T5377S', '', '', '2828465', '2G Module', '', NULL, NULL, NULL, 'repair-list-2026', '2026-row-58')
on conflict (source_system, source_record_id) where source_record_id is not null do update set
  current_status = excluded.current_status, order_status = excluded.order_status,
  is_opened = excluded.is_opened, repair_month = excluded.repair_month,
  item = excluded.item, area = excluded.area, machine_code = excluded.machine_code,
  model = excluded.model, tester_id = excluded.tester_id,
  board_part_code = excluded.board_part_code, serial_no = excluded.serial_no,
  description = excluded.description, failure_data = excluded.failure_data,
  occurred_on = excluded.occurred_on, sent_on = excluded.sent_on, returned_on = excluded.returned_on;
