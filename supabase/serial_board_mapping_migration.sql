-- Canonical S/N -> board-name mapping shared by repair and DBN records.
-- Existing records are normalized and backfilled only when their S/N has one
-- unambiguous board name. Run after dbn_machine_board_migration.sql and the
-- repair board mapping migration.
begin;

create or replace function public.normalize_board_serial(p_serial text)
returns text
language sql
immutable
strict
set search_path = ''
as $$
  select case
    when btrim(p_serial) ~ '^[0-9]{1,9}$' then lpad(btrim(p_serial), 9, '0')
    else upper(btrim(p_serial))
  end
$$;

alter table public.repair_records
  drop constraint if exists repair_records_serial_no_format_check;

alter table public.dbn_records
  drop constraint if exists dbn_records_serial_no_check;
alter table public.dbn_records
  drop constraint if exists dbn_records_serial_no_format_check;

-- Preserve old DBN rows whose machine/board snapshot was not recorded. They
-- remain searchable, while new or populated snapshots are validated normally.
create or replace function public.validate_dbn_machine_board()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  mapped_model text;
  mapped_part_number text;
begin
  if tg_op = 'UPDATE'
    and new.machine_code is null and new.model is null then
    return new;
  end if;
  if new.machine_code is null or new.machine_code = ''
    or new.model is null or new.model = ''
    or new.board_name is null or new.board_name = ''
    or new.board_part_code is null or new.board_part_code = '' then
    raise exception 'DBN 紀錄必須選擇機台與板件名稱';
  end if;
  select model into mapped_model
  from public.repair_machine_models
  where machine_code = new.machine_code;
  if not found then raise exception '機台編號不在有效清單中'; end if;
  if new.model is distinct from mapped_model then
    raise exception '機台編號與 Model 對應不正確';
  end if;
  select board_part_code into mapped_part_number
  from public.repair_model_boards
  where model = new.model and board_name = new.board_name;
  if not found or new.board_part_code is distinct from mapped_part_number then
    raise exception '板件名稱或 Part Number 不屬於此 Model';
  end if;
  return new;
end;
$$;

update public.repair_records
set serial_no = public.normalize_board_serial(serial_no)
where serial_no <> '' and serial_no is distinct from public.normalize_board_serial(serial_no);
update public.dbn_records
set serial_no = public.normalize_board_serial(serial_no)
where serial_no is distinct from public.normalize_board_serial(serial_no);

alter table public.repair_records
  add constraint repair_records_serial_no_format_check
  check (serial_no = '' or serial_no ~ '^[^[:cntrl:]]{1,64}$');
alter table public.dbn_records
  add constraint dbn_records_serial_no_format_check
  check (serial_no ~ '^[^[:cntrl:]]{1,64}$');
alter table public.dbn_records
  drop constraint if exists dbn_records_machine_board_all_or_none_check;
alter table public.dbn_records
  add constraint dbn_records_machine_board_all_or_none_check
  check (
    (machine_code is null and model is null and
      ((board_name is null and board_part_code is null) or (board_name is not null and board_part_code is not null)))
    or (machine_code is not null and model is not null and board_name is not null and board_part_code is not null)
  );

create table if not exists public.serial_board_mappings (
  serial_no text primary key check (serial_no ~ '^[^[:cntrl:]]{1,64}$'),
  board_name text not null check (board_name = btrim(board_name) and board_name <> ''),
  updated_at timestamptz not null default now()
);
alter table public.serial_board_mappings enable row level security;
grant select on public.serial_board_mappings to anon, authenticated;
drop policy if exists "Public can read S/N board mappings" on public.serial_board_mappings;
create policy "Public can read S/N board mappings" on public.serial_board_mappings
  for select to anon, authenticated using (true);

do $$
begin
  if exists (
    select serial_no
    from (
      select public.normalize_board_serial(serial_no) as serial_no, nullif(btrim(description), '') as board_name
      from public.repair_records where serial_no <> ''
      union all
      select public.normalize_board_serial(serial_no), nullif(btrim(board_name), '')
      from public.dbn_records where serial_no <> ''
    ) known
    where board_name is not null
    group by serial_no
    having count(distinct board_name) > 1
  ) then
    raise exception '既有資料有 S/N 對應多種板件名稱；請先人工釐清後再執行此遷移';
  end if;
end;
$$;

insert into public.serial_board_mappings (serial_no, board_name)
select serial_no, min(board_name)
from (
  select public.normalize_board_serial(serial_no) as serial_no, nullif(btrim(description), '') as board_name
  from public.repair_records where serial_no <> ''
  union all
  select public.normalize_board_serial(serial_no), nullif(btrim(board_name), '')
  from public.dbn_records where serial_no <> ''
) known
where board_name is not null
group by serial_no
on conflict (serial_no) do nothing;

create or replace function public.enforce_serial_board_mapping()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  known_board text;
  record_board text;
begin
  new.serial_no := public.normalize_board_serial(new.serial_no);
  if new.serial_no is null or new.serial_no = '' then
    return new;
  end if;

  if tg_table_name = 'repair_records' then
    record_board := nullif(btrim(new.description), '');
  else
    record_board := nullif(btrim(new.board_name), '');
  end if;
  if record_board is null then
    return new;
  end if;

  insert into public.serial_board_mappings (serial_no, board_name)
  values (new.serial_no, record_board)
  on conflict (serial_no) do nothing;
  select board_name into known_board
  from public.serial_board_mappings
  where serial_no = new.serial_no
  for update;
  if known_board is distinct from record_board then
    raise exception 'S/N % 已登記為「%」，不可再對應「%」。若需修正，請透過編輯送修詳細資料更新對應。',
      new.serial_no, known_board, record_board;
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_enforce_serial_board on public.repair_records;
create trigger repair_records_enforce_serial_board
before insert or update of serial_no, description on public.repair_records
for each row execute function public.enforce_serial_board_mapping();

drop trigger if exists dbn_records_enforce_serial_board on public.dbn_records;
create trigger dbn_records_enforce_serial_board
before insert or update of serial_no, board_name on public.dbn_records
for each row execute function public.enforce_serial_board_mapping();

create or replace function public.require_serial_for_new_web_repairs()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if coalesce(new.source_system, 'web') not like 'repair-list-%'
    and coalesce(new.serial_no, '') !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '請輸入有效的 S/N（數字不足 9 位會補 0；其他 S/N 去除前後空白並轉大寫）';
  end if;
  return new;
end;
$$;

create or replace function public.save_repair_record_edit(p_record_id uuid, p_payload jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_serial text;
  v_machine text;
  v_model text;
  v_board text;
  v_part text;
  v_existing_id uuid;
begin
  v_serial := public.normalize_board_serial(p_payload->>'serial_no');
  v_machine := nullif(btrim(p_payload->>'machine_code'), '');
  v_board := nullif(btrim(p_payload->>'description'), '');
  if v_serial is null or v_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception 'S/N 格式不正確';
  end if;

  select model into v_model
  from public.repair_machine_models
  where machine_code = v_machine;
  if not found then
    raise exception '機台編號不在有效清單中';
  end if;
  select board_part_code into v_part
  from public.repair_model_boards
  where model = v_model and board_name = v_board;
  if not found then
    raise exception '板件名稱不屬於所選機台的 Model';
  end if;

  select id into v_existing_id from public.repair_records where id = p_record_id for update;
  if not found then
    raise exception '找不到送修案件';
  end if;

  insert into public.serial_board_mappings (serial_no, board_name)
  values (v_serial, v_board)
  on conflict (serial_no) do update
    set board_name = excluded.board_name, updated_at = now();

  update public.repair_records
  set description = v_board,
      board_part_code = coalesce((select b.board_part_code from public.repair_model_boards b where b.model = repair_records.model and b.board_name = v_board), v_part)
  where serial_no = v_serial;

  if exists (
    select 1
    from public.dbn_records d
    left join public.repair_machine_models mm on mm.machine_code = d.machine_code
    left join public.repair_model_boards b on b.model = mm.model and b.board_name = v_board
    where d.serial_no = v_serial and d.machine_code is not null
      and (mm.machine_code is null or b.board_name is null)
  ) then
    raise exception '此 S/N 有 DBN 紀錄無法依其機台同步板件「%」；請先補齊 DBN 機台資料或選擇可相容的板件', v_board;
  end if;
  update public.dbn_records d
  set board_name = v_board,
      model = mm.model,
      board_part_code = b.board_part_code
  from public.repair_machine_models mm
  join public.repair_model_boards b on b.model = mm.model and b.board_name = v_board
  where d.serial_no = v_serial and d.machine_code = mm.machine_code;
  update public.dbn_records
  set board_name = v_board,
      board_part_code = v_part
  where serial_no = v_serial and machine_code is null and model is null;

  update public.repair_records
  set is_opened = coalesce((p_payload->>'is_opened')::boolean, false),
      repair_month = coalesce(p_payload->>'repair_month', ''),
      item = coalesce(p_payload->>'item', ''),
      area = coalesce(p_payload->>'area', ''),
      machine_code = v_machine,
      model = v_model,
      board_part_code = v_part,
      serial_no = v_serial,
      description = v_board,
      occurred_on = nullif(p_payload->>'occurred_on', '')::date,
      sent_on = nullif(p_payload->>'sent_on', '')::date,
      returned_on = nullif(p_payload->>'returned_on', '')::date,
      current_status = case when current_status in ('待送修', '已送修', '取回驗證') then coalesce(p_payload->>'current_status', current_status) else current_status end
  where id = p_record_id;
end;
$$;

grant execute on function public.save_repair_record_edit(uuid, jsonb) to anon, authenticated;

create or replace function public.finish_repair_verification(p_record_id uuid, p_passed boolean)
returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_old public.repair_records%rowtype;
  v_new_id uuid;
begin
  if p_passed is null then
    raise exception '必須選擇 PASS 或 FAIL';
  end if;
  select * into v_old from public.repair_records where id = p_record_id for update;
  if not found then raise exception '找不到送修案件'; end if;
  if v_old.current_status <> '取回驗證' then
    raise exception '只有「取回驗證」案件可以登錄 PASS／FAIL';
  end if;
  if not p_passed and coalesce(v_old.serial_no, '') !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '此案件缺少有效 S/N，無法建立再次送修案件';
  end if;
  update public.repair_records
  set current_status = case when p_passed then '結案（PASS）' else '結案（FAIL）' end,
      closed_on = current_date
  where id = p_record_id;
  if p_passed then return null; end if;
  insert into public.repair_records (
    current_status, order_status, is_opened, repair_month, item, area,
    machine_code, model, tester_id, board_part_code, serial_no,
    description, failure_data, occurred_on, sent_on, returned_on,
    source_system, source_record_id, retry_of_record_id
  ) values (
    '待送修', v_old.order_status, v_old.is_opened, v_old.repair_month, v_old.item, v_old.area,
    v_old.machine_code, v_old.model, v_old.tester_id, v_old.board_part_code, v_old.serial_no,
    v_old.description, v_old.failure_data, v_old.occurred_on, null, null,
    'web', null, v_old.id
  ) returning id into v_new_id;
  return v_new_id;
end;
$$;
grant execute on function public.finish_repair_verification(uuid, boolean) to anon, authenticated;

grant update on public.dbn_records to anon, authenticated;
drop policy if exists "Public can update DBN records" on public.dbn_records;
create policy "Public can update DBN records" on public.dbn_records
  for update to anon, authenticated using (true) with check (true);

commit;
