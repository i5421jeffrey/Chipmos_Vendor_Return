-- Add S/N-linked repair outcomes and automatic retry creation.
-- Run once in Supabase Dashboard > SQL Editor. Legacy closed records are marked PASS as requested.
begin;

alter table public.repair_records
  add column if not exists closed_on date,
  add column if not exists retry_of_record_id uuid references public.repair_records(id) on delete set null;
alter table public.repair_records alter column source_system set default 'web';

alter table public.repair_records
  drop constraint if exists repair_records_current_status_check;

update public.repair_records
set current_status = '結案（PASS）',
    closed_on = coalesce(returned_on, (updated_at at time zone 'Asia/Taipei')::date, (created_at at time zone 'Asia/Taipei')::date)
where current_status in ('已結案', '結案');
update public.repair_records
set closed_on = coalesce(returned_on, (updated_at at time zone 'Asia/Taipei')::date, (created_at at time zone 'Asia/Taipei')::date)
where current_status in ('結案（PASS）', '結案（FAIL）') and closed_on is null;

alter table public.repair_records
  add constraint repair_records_current_status_check
  check (current_status in ('待送修', '已送修', '取回驗證', '結案（PASS）', '結案（FAIL）'));
alter table public.repair_records
  drop constraint if exists repair_records_serial_no_format_check;
alter table public.repair_records
  add constraint repair_records_serial_no_format_check
  check (serial_no = '' or serial_no ~ '^[0-9]{9}$');

create index if not exists repair_records_serial_history_idx
  on public.repair_records (serial_no, closed_on, created_at);
create index if not exists repair_records_retry_idx
  on public.repair_records (retry_of_record_id);

create or replace function public.set_repair_closed_on()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.current_status in ('結案（PASS）', '結案（FAIL）') then
    new.closed_on := coalesce(new.closed_on, current_date);
  else
    new.closed_on := null;
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_set_closed_on on public.repair_records;
create trigger repair_records_set_closed_on
before insert or update on public.repair_records
for each row execute function public.set_repair_closed_on();

create or replace function public.require_serial_for_new_web_repairs()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if coalesce(new.source_system, 'web') not like 'repair-list-%'
     and coalesce(new.serial_no, '') !~ '^[0-9]{9}$' then
    raise exception '請輸入 9 位數字 S/N 才能建立新的送修資料';
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_require_serial on public.repair_records;
create trigger repair_records_require_serial
before insert on public.repair_records
for each row execute function public.require_serial_for_new_web_repairs();

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

  select * into v_old
  from public.repair_records
  where id = p_record_id
  for update;

  if not found then
    raise exception '找不到送修案件';
  end if;
  if v_old.current_status <> '取回驗證' then
    raise exception '只有「取回驗證」案件可以登錄 PASS／FAIL';
  end if;
  if not p_passed and coalesce(v_old.serial_no, '') !~ '^[0-9]{9}$' then
    raise exception '此案件缺少有效的 9 位數字 S/N，無法建立再次送修案件';
  end if;

  update public.repair_records
  set current_status = case when p_passed then '結案（PASS）' else '結案（FAIL）' end,
      closed_on = current_date
  where id = p_record_id;

  if p_passed then
    return null;
  end if;

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

commit;
