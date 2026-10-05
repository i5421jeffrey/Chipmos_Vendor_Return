-- Add repair classifications, per-attempt amounts, and statistics support.
-- Run after repairs_setup.sql, repair_history_migration.sql,
-- repair_failure_tags_migration.sql, and serial_board_mapping_migration.sql.
-- This migration includes the retry-details behavior; the older
-- repair_retry_details_migration.sql need not be run separately if still pending.
begin;

alter table public.repair_records
  add column if not exists repair_type text,
  add column if not exists repair_amount numeric(12, 2);

update public.repair_records
set repair_type = '板修'
where repair_type is null or btrim(repair_type) = '';

-- Centralize amount lookup so a future imported quote list can replace this
-- temporary category-based value without allowing client edits.
create or replace function public.resolve_repair_amount(
  p_repair_type text,
  p_board_part_code text,
  p_board_name text
)
returns numeric(12, 2)
language sql
stable
security definer
set search_path = public
as $$
  select case
    when p_repair_type = '保固' then 0::numeric
    when p_repair_type in ('板修', '外修', '合約') then 1::numeric
    else null
  end;
$$;

update public.repair_records
set repair_amount = public.resolve_repair_amount(repair_type, board_part_code, description)
where repair_amount is null;

alter table public.repair_records
  alter column repair_type set default '板修',
  alter column repair_type set not null,
  alter column repair_amount set default 1,
  alter column repair_amount set not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conrelid = 'public.repair_records'::regclass and conname = 'repair_records_repair_type_check') then
    alter table public.repair_records add constraint repair_records_repair_type_check check (repair_type in ('板修', '外修', '合約', '保固'));
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.repair_records'::regclass and conname = 'repair_records_repair_amount_check') then
    alter table public.repair_records add constraint repair_records_repair_amount_check check (repair_amount is null or repair_amount >= 0);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.repair_records'::regclass and conname = 'repair_records_warranty_amount_check') then
    alter table public.repair_records add constraint repair_records_warranty_amount_check check (repair_type <> '保固' or repair_amount is null or repair_amount = 0);
  end if;
end;
$$;

create or replace function public.validate_repair_accounting()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.repair_type is null or new.repair_type not in ('板修', '外修', '合約', '保固') then
    raise exception '請選擇有效的維修分類';
  end if;
  new.repair_amount := public.resolve_repair_amount(
    new.repair_type, new.board_part_code, new.description
  );
  if new.repair_amount is null or new.repair_amount < 0 then
    raise exception '每筆維修紀錄都必須填寫非負數金額';
  end if;
  if new.repair_type = '保固' and new.repair_amount <> 0 then
    raise exception '保固維修金額必須為 0';
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_validate_repair_accounting on public.repair_records;
drop trigger if exists repair_records_validate_repair_accounting_update on public.repair_records;
create trigger repair_records_validate_repair_accounting
before insert or update on public.repair_records
for each row execute function public.validate_repair_accounting();

-- Keep each attempt's description and attachment independent; inherit only its failure tag.
create or replace function public.prepare_repair_failure_fields()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  inherited_tag text;
  current_has_attachment boolean := false;
  allow_attached_log boolean := false;
begin
  new.failure_description := btrim(coalesce(new.failure_description, ''));
  if tg_op = 'INSERT' and new.retry_of_record_id is not null and new.failure_tag is null then
    select failure_tag into inherited_tag from public.repair_records where id = new.retry_of_record_id;
    if found then new.failure_tag := inherited_tag; end if;
  end if;
  if new.failure_tag is not null and new.failure_tag not in ('INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER', 'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA') then
    raise exception '請選擇有效的異常標籤';
  end if;
  if tg_op = 'INSERT' and new.failure_tag is null then raise exception '新增送修資料必須選擇異常標籤'; end if;
  if tg_op = 'UPDATE' and old.failure_tag is not null and new.failure_tag is null then raise exception '異常標籤不可清除'; end if;
  if tg_op = 'INSERT' and new.failure_description = '' then
    allow_attached_log := coalesce(current_setting('app.repair_has_fail_log', true) = '1', false);
    if not allow_attached_log then raise exception '請填寫異常描述或上傳 Fail Log'; end if;
  end if;
  if tg_op = 'UPDATE' and new.failure_description = '' then
    select exists (select 1 from public.repair_attachments where repair_record_id = new.id) into current_has_attachment;
    if not current_has_attachment then raise exception '沒有 Fail Log 時必須填寫異常描述'; end if;
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_prepare_failure_fields on public.repair_records;
create trigger repair_records_prepare_failure_fields
before insert or update of failure_tag, failure_description on public.repair_records
for each row execute function public.prepare_repair_failure_fields();

create or replace function public.create_repair_record_with_failure_info(
  p_record_id uuid,
  p_payload jsonb,
  p_attachment jsonb default null
)
returns setof public.repair_records
language plpgsql
security definer
set search_path = public
as $$
declare
  v_record public.repair_records%rowtype;
  v_tag text := nullif(btrim(p_payload->>'failure_tag'), '');
  v_description text := btrim(coalesce(p_payload->>'failure_description', ''));
  v_repair_type text := nullif(btrim(p_payload->>'repair_type'), '');
  v_repair_amount numeric(12, 2) := nullif(p_payload->>'repair_amount', '')::numeric;
  v_path text;
  v_filename text;
  v_file_size integer;
  v_content_type text;
begin
  if v_tag is null or v_tag not in ('INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER', 'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA') then
    raise exception '請選擇有效的異常標籤';
  end if;
  if v_repair_type is null or v_repair_type not in ('板修', '外修', '合約', '保固') then raise exception '請選擇有效的維修分類'; end if;
  if v_repair_amount is null or v_repair_amount < 0 then raise exception '請填寫非負數金額'; end if;
  if v_repair_type = '保固' and v_repair_amount <> 0 then raise exception '保固維修金額必須為 0'; end if;
  if p_attachment is null then
    if v_description = '' then raise exception '未附 Fail Log 時必須填寫異常描述'; end if;
    perform set_config('app.repair_has_fail_log', '0', true);
  else
    v_path := p_attachment->>'storage_path';
    v_filename := p_attachment->>'filename';
    v_file_size := nullif(p_attachment->>'file_size', '')::integer;
    v_content_type := coalesce(nullif(p_attachment->>'content_type', ''), 'text/plain');
    if v_path is null or v_path not like p_record_id::text || '/%' or v_filename is null or v_filename !~* '\.(txt|asc)$'
      or v_file_size is null or v_file_size <= 0 or v_file_size > 5242880 then
      raise exception 'Fail Log 附件資訊不正確';
    end if;
    if not exists (select 1 from storage.objects where bucket_id = 'repair-fail-logs' and name = v_path) then
      raise exception '找不到已上傳的 Fail Log 檔案';
    end if;
    perform set_config('app.repair_has_fail_log', '1', true);
  end if;
  insert into public.repair_records (
    id, current_status, order_status, is_opened, repair_month, item, area,
    machine_code, model, board_part_code, serial_no, description, occurred_on,
    sent_on, returned_on, source_system, source_record_id, failure_tag,
    failure_description, repair_type, repair_amount
  ) values (
    p_record_id, '待送修', '', false, '', '', '',
    p_payload->>'machine_code', p_payload->>'model', p_payload->>'board_part_code',
    p_payload->>'serial_no', p_payload->>'description', nullif(p_payload->>'occurred_on', '')::date,
    null, null, 'web', null, v_tag, v_description, v_repair_type, v_repair_amount
  ) returning * into v_record;
  if p_attachment is not null then
    insert into public.repair_attachments (repair_record_id, storage_path, filename, file_size, content_type)
    values (v_record.id, v_path, v_filename, v_file_size, v_content_type);
  end if;
  return next v_record;
  return;
end;
$$;
grant execute on function public.create_repair_record_with_failure_info(uuid, jsonb, jsonb) to anon, authenticated;

create or replace function public.save_repair_record_edit_with_failure_info(p_record_id uuid, p_payload jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_tag text := nullif(btrim(p_payload->>'failure_tag'), '');
  v_description text := btrim(coalesce(p_payload->>'failure_description', ''));
  v_repair_type text := nullif(btrim(p_payload->>'repair_type'), '');
  v_repair_amount numeric(12, 2) := nullif(p_payload->>'repair_amount', '')::numeric;
  v_has_attachment boolean;
begin
  if v_tag is null or v_tag not in ('INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER', 'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA') then
    raise exception '請選擇有效的異常標籤';
  end if;
  if v_repair_type is null or v_repair_type not in ('板修', '外修', '合約', '保固') then raise exception '請選擇有效的維修分類'; end if;
  if v_repair_amount is null or v_repair_amount < 0 then raise exception '請填寫非負數金額'; end if;
  if v_repair_type = '保固' and v_repair_amount <> 0 then raise exception '保固維修金額必須為 0'; end if;
  select exists (select 1 from public.repair_attachments where repair_record_id = p_record_id) into v_has_attachment;
  if not v_has_attachment and v_description = '' then raise exception '沒有 Fail Log 時必須填寫異常描述'; end if;
  perform public.save_repair_record_edit(p_record_id, p_payload);
  update public.repair_records
  set failure_tag = v_tag, failure_description = v_description,
      repair_type = v_repair_type, repair_amount = v_repair_amount
  where id = p_record_id;
  if not found then raise exception '找不到送修案件'; end if;
end;
$$;
grant execute on function public.save_repair_record_edit_with_failure_info(uuid, jsonb) to anon, authenticated;

-- Every failed attempt is closed and counted; its next linked attempt has its
-- own classification and amount. Selecting an external category converts the
-- chain from in-house board repair to external/contract/warranty repair.
drop function if exists public.finish_repair_verification(uuid, boolean, uuid, text, jsonb);
create or replace function public.finish_repair_verification(
  p_record_id uuid, p_passed boolean, p_retry_record_id uuid,
  p_failure_description text, p_attachment jsonb,
  p_retry_repair_type text, p_retry_repair_amount numeric
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_old public.repair_records%rowtype;
  v_description text := btrim(coalesce(p_failure_description, ''));
  v_repair_type text := nullif(btrim(p_retry_repair_type), '');
  v_repair_amount numeric(12, 2) := p_retry_repair_amount;
  v_path text;
  v_filename text;
  v_file_size integer;
  v_content_type text;
begin
  if p_passed is null then raise exception '必須選擇 PASS 或 FAIL'; end if;
  select * into v_old from public.repair_records where id = p_record_id for update;
  if not found then raise exception '找不到送修案件'; end if;
  if v_old.current_status <> '取回驗證' then raise exception '只有「取回驗證」案件可以登錄 PASS／FAIL'; end if;
  if v_old.repair_amount is null then raise exception '請先編輯並填寫本筆維修金額，再登錄驗證結果'; end if;
  if p_passed then
    update public.repair_records set current_status = '結案（PASS）', closed_on = current_date where id = p_record_id;
    return null;
  end if;
  if coalesce(v_old.serial_no, '') !~ '^[^[:cntrl:]]{1,64}$' then raise exception '此案件缺少有效 S/N，無法建立再次送修案件'; end if;
  if p_retry_record_id is null then raise exception '缺少下一筆送修案件編號'; end if;
  if v_description = '' and p_attachment is null then raise exception '請填寫異常描述或上傳 Fail Log'; end if;
  if v_repair_type is null or v_repair_type not in ('板修', '外修', '合約', '保固') then raise exception '請選擇有效的維修分類'; end if;
  if v_repair_amount is null or v_repair_amount < 0 then raise exception '請填寫非負數金額'; end if;
  if v_repair_type = '保固' and v_repair_amount <> 0 then raise exception '保固維修金額必須為 0'; end if;
  if p_attachment is not null then
    v_path := p_attachment->>'storage_path';
    v_filename := p_attachment->>'filename';
    v_file_size := nullif(p_attachment->>'file_size', '')::integer;
    v_content_type := coalesce(nullif(p_attachment->>'content_type', ''), 'text/plain');
    if v_path is null or v_path not like p_retry_record_id::text || '/%' or v_filename is null or v_filename !~* '\.(txt|asc)$'
      or v_file_size is null or v_file_size <= 0 or v_file_size > 5242880 then
      raise exception 'Fail Log 附件資訊不正確';
    end if;
    if not exists (select 1 from storage.objects where bucket_id = 'repair-fail-logs' and name = v_path) then
      raise exception '找不到已上傳的 Fail Log 檔案';
    end if;
    perform set_config('app.repair_has_fail_log', '1', true);
  else
    perform set_config('app.repair_has_fail_log', '0', true);
  end if;
  update public.repair_records set current_status = '結案（FAIL）', closed_on = current_date where id = p_record_id;
  insert into public.repair_records (
    id, current_status, order_status, is_opened, repair_month, item, area,
    machine_code, model, tester_id, board_part_code, serial_no, description,
    failure_data, occurred_on, sent_on, returned_on, source_system,
    source_record_id, retry_of_record_id, failure_tag, failure_description,
    repair_type, repair_amount
  ) values (
    p_retry_record_id, '待送修', v_old.order_status, v_old.is_opened,
    v_old.repair_month, v_old.item, v_old.area, v_old.machine_code,
    v_old.model, v_old.tester_id, v_old.board_part_code, v_old.serial_no,
    v_old.description, v_old.failure_data, v_old.occurred_on, null, null,
    'web', null, v_old.id, v_old.failure_tag, v_description,
    v_repair_type, v_repair_amount
  );
  if p_attachment is not null then
    insert into public.repair_attachments (repair_record_id, storage_path, filename, file_size, content_type)
    values (p_retry_record_id, v_path, v_filename, v_file_size, v_content_type);
  end if;
  return p_retry_record_id;
end;
$$;
grant execute on function public.finish_repair_verification(uuid, boolean, uuid, text, jsonb, text, numeric) to anon, authenticated;

-- Keep the existing two-argument PASS call for the page; reject legacy FAIL
-- calls which cannot provide a fresh per-attempt amount.
create or replace function public.finish_repair_verification(p_record_id uuid, p_passed boolean)
returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_record public.repair_records%rowtype;
begin
  if p_passed is null then raise exception '必須選擇 PASS 或 FAIL'; end if;
  if not p_passed then raise exception 'FAIL 請使用新版再次送修流程，填寫分類與金額'; end if;
  select * into v_record from public.repair_records where id = p_record_id for update;
  if not found then raise exception '找不到送修案件'; end if;
  if v_record.current_status <> '取回驗證' then raise exception '只有「取回驗證」案件可以登錄 PASS／FAIL'; end if;
  if v_record.repair_amount is null then raise exception '請先編輯並填寫本筆維修金額，再登錄 PASS'; end if;
  update public.repair_records set current_status = '結案（PASS）', closed_on = current_date where id = p_record_id;
  return null;
end;
$$;
grant execute on function public.finish_repair_verification(uuid, boolean) to anon, authenticated;

create index if not exists repair_records_repair_statistics_idx
  on public.repair_records (occurred_on, closed_on, repair_type);

commit;
