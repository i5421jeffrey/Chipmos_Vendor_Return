-- Import SPMS_各板件維修金額填寫表.xlsx and reprice ALL existing attempts,
-- including closed PASS/FAIL cases. Blank cells remain NULL, never 1 or 0.
-- Workbook SHA256: f54d67dbb6be81ca12c0055e44b8c53e1b4f64c0ea96e7166fd054b888306255
-- Run after classification, serial catalog and record_change_history migrations.
-- Do not rerun the old amount-default migrations after this migration.
begin;
lock table public.repair_records in share row exclusive mode;

do $$
begin
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.repair_records'::regclass
      and tgname = 'repair_records_capture_changes' and tgenabled in ('O', 'A')
  ) then
    raise exception '請先執行 record_change_history_migration.sql，以保存歷史金額異動紀錄';
  end if;
end;
$$;

create table if not exists public.repair_board_prices (
  model text not null,
  board_name text not null,
  board_part_code text not null,
  board_repair_amount numeric(12, 2) check (board_repair_amount >= 0),
  external_repair_amount numeric(12, 2) check (external_repair_amount >= 0),
  contract_repair_amount numeric(12, 2) check (contract_repair_amount >= 0),
  warranty_repair_amount numeric(12, 2) check (warranty_repair_amount = 0),
  primary key (model, board_name, board_part_code)
);
alter table public.repair_board_prices enable row level security;
revoke all on public.repair_board_prices from public, anon, authenticated;
grant select on public.repair_board_prices to anon, authenticated;
drop policy if exists "Public can read repair board prices" on public.repair_board_prices;
create policy "Public can read repair board prices" on public.repair_board_prices
  for select to anon, authenticated using (true);

create temporary table imported_board_prices (like public.repair_board_prices including constraints)
on commit drop;
insert into imported_board_prices values
  ('T5377', '1G MODULE', 'BGD-030184', 274000, 274000, 0, 0),
  ('T5377', 'ALPG', 'BIR-030349', null, null, 0, 0),
  ('T5377', 'BLADE150', '-', null, null, 0, 0),
  ('T5377', 'BLADE1500', '-', 95000, 95000, 0, 0),
  ('T5377', 'CAL SIG', 'BGR-026746X02', 39000, 39000, 0, 0),
  ('T5377', 'DC', 'BGR-026902', 50987, 50987, 0, 0),
  ('T5377', 'DPU I/F', 'BGR-026901', null, null, 0, 0),
  ('T5377', 'DR PE', 'BIR-026805', 50987, 50987, 0, 0),
  ('T5377', 'FAIL MUX', 'BGR-026384X02', null, null, 0, 0),
  ('T5377', 'FM CONT', 'BGR-030181', 50987, 50987, 0, 0),
  ('T5377', 'FMRA', 'BGR-030182X02', 50987, 50987, 0, 0),
  ('T5377', 'I/O PE', 'BIR-030083', 50987, 50987, 0, 0),
  ('T5377', 'Main AC', 'WBL_H371329X06CONT', 58500, 58500, 0, 0),
  ('T5377', 'Mother Board X04', 'H7-0760X04', 50000, 50000, 0, 0),
  ('T5377', 'Mother Board X05', 'H7-0760X05', 50000, 50000, 0, 0),
  ('T5377', 'Mother Board X06', 'H7-0760X06', 50000, 50000, 0, 0),
  ('T5377', 'Mother Board X07', 'H7-0760X07', 50000, 50000, 0, 0),
  ('T5377', 'PDS', 'BIR-026380', 50987, 50987, 0, 0),
  ('T5377', 'PM', 'BIR-026383', null, null, 0, 0),
  ('T5377', 'PPS', 'BIR-026903', 50987, 50987, 0, 0),
  ('T5377', 'PS MONITOR', 'BGR-026815X02', 35000, 35000, 0, 0),
  ('T5377', 'TH IF', 'BGR-026378X04', 50987, 50987, 0, 0),
  ('T5377', 'TP6B CPU', 'WBL-H3610207CPU', 33800, 33800, 0, 0),
  ('T5377S', '2G MODULE', 'BGD-030184X02', 50987, 50987, 0, 0),
  ('T5377S', 'ALPG', 'BIR-030349', null, null, 0, 0),
  ('T5377S', 'BLADE150', '-', null, null, 0, 0),
  ('T5377S', 'BLADE1500', '-', 95000, 95000, 0, 0),
  ('T5377S', 'CAL SIG', 'BGR-026746X02', 39000, 39000, 0, 0),
  ('T5377S', 'DC', 'BGR-026902', 50987, 50987, 0, 0),
  ('T5377S', 'FAIL MUX', 'BGR-026384X02', null, null, 0, 0),
  ('T5377S', 'FM CONT X02', 'BGR-030181X02', 50987, 50987, 0, 0),
  ('T5377S', 'FMRA', 'BGR-030182X02', 50987, 50987, 0, 0),
  ('T5377S', 'HVDR PE', 'BPR-030837', 50987, 50987, 0, 0),
  ('T5377S', 'I/O PE', 'BIR-030083', 50987, 50987, 0, 0),
  ('T5377S', 'Main AC', '-', 58500, 58500, 0, 0),
  ('T5377S', 'Mother Board X04', 'H7-0760X04', 50000, 50000, 0, 0),
  ('T5377S', 'Mother Board X05', 'H7-0760X05', 50000, 50000, 0, 0),
  ('T5377S', 'Mother Board X06', 'H7-0760X06', 50000, 50000, 0, 0),
  ('T5377S', 'Mother Board X07', 'H7-0760X07', 50000, 50000, 0, 0),
  ('T5377S', 'PDS', 'BIR-026380', 50987, 50987, 0, 0),
  ('T5377S', 'PM', 'BIR-026383', null, null, 0, 0),
  ('T5377S', 'PPS', 'BIR-026903', 50987, 50987, 0, 0),
  ('T5377S', 'PS MONITOR', 'BGR-031487', 35000, 35000, 0, 0),
  ('T5377S', 'SYSTEM MONITOR', 'BGR-031566', null, null, 0, 0),
  ('T5377S', 'TH IF', 'BGR-026378X04', 50987, 50987, 0, 0),
  ('T5377S', 'TP6B CPU', 'WBL-H3610207CPU', 33800, 33800, 0, 0);

do $$
begin
  if exists (
    select 1 from imported_board_prices p
    where not exists (
      select 1 from public.repair_model_boards b
      where (b.model, b.board_name, b.board_part_code) = (p.model, p.board_name, p.board_part_code)
    )
  ) then
    raise exception 'Excel 板件與目前參考主檔不一致，請先確認 Model、板件名稱與 Part Number';
  end if;
end;
$$;

insert into public.repair_board_prices
select * from imported_board_prices
on conflict (model, board_name, board_part_code) do update set
  board_repair_amount = excluded.board_repair_amount,
  external_repair_amount = excluded.external_repair_amount,
  contract_repair_amount = excluded.contract_repair_amount,
  warranty_repair_amount = excluded.warranty_repair_amount;

create or replace function public.resolve_repair_amount(
  p_repair_type text, p_board_part_code text, p_board_name text, p_model text
)
returns numeric(12, 2)
language sql stable security definer set search_path = ''
as $$
  select case p_repair_type
    when '板修' then p.board_repair_amount
    when '外修' then p.external_repair_amount
    when '合約' then p.contract_repair_amount
    when '保固' then p.warranty_repair_amount
  end
  from public.repair_board_prices p
  where p.model = btrim(p_model) and p.board_name = btrim(p_board_name)
    and p.board_part_code = btrim(p_board_part_code);
$$;

-- Legacy callers without Model may only receive an unambiguous price.
-- Never guess when Models disagree or any matching row is unpriced.
create or replace function public.resolve_repair_amount(
  p_repair_type text, p_board_part_code text, p_board_name text
)
returns numeric(12, 2)
language sql stable security definer set search_path = ''
as $$
  select case when count(*) > 0 and count(amount) = count(*)
    and count(distinct amount) = 1 then min(amount) else null end
  from (
    select public.resolve_repair_amount(p_repair_type, p_board_part_code, p_board_name, p.model) as amount
    from public.repair_board_prices p
    where p.board_name = btrim(p_board_name) and p.board_part_code = btrim(p_board_part_code)
  ) prices;
$$;

alter table public.repair_records
  alter column repair_amount drop not null,
  alter column repair_amount drop default;

create or replace function public.validate_repair_accounting()
returns trigger
language plpgsql set search_path = ''
as $$
begin
  if new.repair_type is null or new.repair_type not in ('板修', '外修', '合約', '保固') then
    raise exception '請選擇有效的維修分類';
  end if;
  new.repair_amount := public.resolve_repair_amount(
    new.repair_type, new.board_part_code, new.description, new.model
  );
  if tg_op = 'INSERT' and new.repair_amount is null then
    raise exception '此 Model／板件／Part Number 的「%」金額尚未設定，請先補齊價格', new.repair_type;
  end if;
  return new;
end;
$$;
drop trigger if exists repair_records_validate_repair_accounting on public.repair_records;
drop trigger if exists repair_records_validate_repair_accounting_update on public.repair_records;
create trigger repair_records_validate_repair_accounting
before insert or update on public.repair_records
for each row execute function public.validate_repair_accounting();

-- Keep the first pre-import amount for rollback review. This private backup
-- has no foreign key so deleting a repair does not erase its original amount.
create table if not exists public.repair_price_import_backup_20261012 (
  repair_record_id uuid primary key,
  model text, board_name text, board_part_code text, repair_type text,
  previous_amount numeric(12, 2), imported_amount numeric(12, 2),
  backed_up_at timestamptz not null default now()
);
alter table public.repair_price_import_backup_20261012 enable row level security;
revoke all on public.repair_price_import_backup_20261012 from public, anon, authenticated;
insert into public.repair_price_import_backup_20261012
  (repair_record_id, model, board_name, board_part_code, repair_type, previous_amount, imported_amount)
select r.id, r.model, r.description, r.board_part_code, r.repair_type, r.repair_amount,
  public.resolve_repair_amount(r.repair_type, r.board_part_code, r.description, r.model)
from public.repair_records r
where r.repair_amount is distinct from public.resolve_repair_amount(r.repair_type, r.board_part_code, r.description, r.model)
on conflict (repair_record_id) do nothing;

-- Updating only repair_amount avoids triggering unrelated historical S/N or
-- description validation; the normal audit trigger remains enabled.
update public.repair_records r
set repair_amount = public.resolve_repair_amount(r.repair_type, r.board_part_code, r.description, r.model)
where r.repair_amount is distinct from public.resolve_repair_amount(r.repair_type, r.board_part_code, r.description, r.model);

notify pgrst, 'reload schema';
commit;

-- Final verification; unmatched legacy snapshots are also reported as unset.
select repair_type, count(*) as record_count,
  count(*) filter (where repair_amount is null) as unset_count,
  sum(repair_amount) as known_amount_total
from public.repair_records group by repair_type order by repair_type;
