-- Keep failure descriptions and Fail Logs specific to each consecutive repair attempt.
-- Run after repairs_setup.sql, repair_history_migration.sql,
-- repair_failure_tags_migration.sql, and serial_board_mapping_migration.sql.
begin;

-- A retry no longer inherits the previous attempt's description or attachment.
-- Its failure tag remains inherited when not explicitly supplied.
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

  if tg_op = 'INSERT' and new.retry_of_record_id is not null
    and new.failure_tag is null then
    select failure_tag into inherited_tag
    from public.repair_records
    where id = new.retry_of_record_id;
    if found then new.failure_tag := inherited_tag; end if;
  end if;

  if new.failure_tag is not null and new.failure_tag not in (
    'INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER',
    'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA'
  ) then
    raise exception '請選擇有效的異常標籤';
  end if;

  if tg_op = 'INSERT' and new.failure_tag is null then
    raise exception '新增送修資料必須選擇異常標籤';
  end if;
  if tg_op = 'UPDATE' and old.failure_tag is not null and new.failure_tag is null then
    raise exception '異常標籤不可清除';
  end if;

  if tg_op = 'INSERT' and new.failure_description = '' then
    allow_attached_log := coalesce(current_setting('app.repair_has_fail_log', true) = '1', false);
    if not allow_attached_log then
      raise exception '請填寫異常描述或上傳 Fail Log';
    end if;
  end if;

  if tg_op = 'UPDATE' and new.failure_description = '' then
    select exists (
      select 1 from public.repair_attachments
      where repair_record_id = new.id
    ) into current_has_attachment;
    if not current_has_attachment then
      raise exception '沒有 Fail Log 時必須填寫異常描述';
    end if;
  end if;

  return new;
end;
$$;

-- Add an overload that stores retry details atomically. Keep the existing
-- two-argument function for PASS verification and older clients.
create or replace function public.finish_repair_verification(
  p_record_id uuid,
  p_passed boolean,
  p_retry_record_id uuid,
  p_failure_description text,
  p_attachment jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_old public.repair_records%rowtype;
  v_description text := btrim(coalesce(p_failure_description, ''));
  v_path text;
  v_filename text;
  v_file_size integer;
  v_content_type text;
begin
  if p_passed is null then
    raise exception '必須選擇 PASS 或 FAIL';
  end if;

  select * into v_old
  from public.repair_records
  where id = p_record_id
  for update;
  if not found then raise exception '找不到送修案件'; end if;
  if v_old.current_status <> '取回驗證' then
    raise exception '只有「取回驗證」案件可以登錄 PASS／FAIL';
  end if;

  if p_passed then
    update public.repair_records
    set current_status = '結案（PASS）', closed_on = current_date
    where id = p_record_id;
    return null;
  end if;

  if coalesce(v_old.serial_no, '') !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '此案件缺少有效 S/N，無法建立再次送修案件';
  end if;
  if p_retry_record_id is null then
    raise exception '缺少下一筆送修案件編號';
  end if;
  if v_description = '' and p_attachment is null then
    raise exception '請填寫異常描述或上傳 Fail Log';
  end if;

  if p_attachment is not null then
    v_path := p_attachment->>'storage_path';
    v_filename := p_attachment->>'filename';
    v_file_size := nullif(p_attachment->>'file_size', '')::integer;
    v_content_type := coalesce(nullif(p_attachment->>'content_type', ''), 'text/plain');
    if v_path is null or v_path not like p_retry_record_id::text || '/%'
      or v_filename is null or v_filename !~* '\.(txt|asc)$'
      or v_file_size is null or v_file_size <= 0 or v_file_size > 5242880 then
      raise exception 'Fail Log 附件資訊不正確';
    end if;
    if not exists (
      select 1 from storage.objects
      where bucket_id = 'repair-fail-logs' and name = v_path
    ) then
      raise exception '找不到已上傳的 Fail Log 檔案';
    end if;
    perform set_config('app.repair_has_fail_log', '1', true);
  else
    perform set_config('app.repair_has_fail_log', '0', true);
  end if;

  update public.repair_records
  set current_status = '結案（FAIL）', closed_on = current_date
  where id = p_record_id;

  insert into public.repair_records (
    id, current_status, order_status, is_opened, repair_month, item, area,
    machine_code, model, tester_id, board_part_code, serial_no,
    description, failure_data, occurred_on, sent_on, returned_on,
    source_system, source_record_id, retry_of_record_id,
    failure_tag, failure_description
  ) values (
    p_retry_record_id, '待送修', v_old.order_status, v_old.is_opened,
    v_old.repair_month, v_old.item, v_old.area, v_old.machine_code,
    v_old.model, v_old.tester_id, v_old.board_part_code, v_old.serial_no,
    v_old.description, v_old.failure_data, v_old.occurred_on, null, null,
    'web', null, v_old.id, v_old.failure_tag, v_description
  );

  if p_attachment is not null then
    insert into public.repair_attachments (
      repair_record_id, storage_path, filename, file_size, content_type
    ) values (
      p_retry_record_id, v_path, v_filename, v_file_size, v_content_type
    );
  end if;

  return p_retry_record_id;
end;
$$;

grant execute on function public.finish_repair_verification(uuid, boolean, uuid, text, jsonb)
  to anon, authenticated;

commit;
