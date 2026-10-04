-- Add standardized failure tags and short descriptions to repair records.
-- Existing records are intentionally left unclassified (NULL failure_tag).
-- Run in Supabase SQL Editor before using the updated repair form.
begin;

alter table public.repair_records
  add column if not exists failure_tag text,
  add column if not exists failure_description text not null default '';

alter table public.repair_records
  drop constraint if exists repair_records_failure_tag_check;
alter table public.repair_records
  add constraint repair_records_failure_tag_check
  check (
    failure_tag is null
    or failure_tag in (
      'INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER',
      'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA'
    )
  );

create or replace function public.prepare_repair_failure_fields()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  inherited_tag text;
  inherited_description text;
  inherited_has_attachment boolean := false;
  current_has_attachment boolean := false;
  allow_attached_log boolean := false;
begin
  new.failure_description := btrim(coalesce(new.failure_description, ''));

  if tg_op = 'INSERT' and new.retry_of_record_id is not null then
    select failure_tag, failure_description
      into inherited_tag, inherited_description
    from public.repair_records
    where id = new.retry_of_record_id;
    if found then
      if new.failure_tag is null then new.failure_tag := inherited_tag; end if;
      if btrim(new.failure_description) = '' then
        new.failure_description := coalesce(inherited_description, '');
      end if;
      select exists (
        select 1 from public.repair_attachments
        where repair_record_id = new.retry_of_record_id
      ) into inherited_has_attachment;
    end if;
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

  if tg_op = 'INSERT' and btrim(new.failure_description) = '' then
    allow_attached_log := current_setting('app.repair_has_fail_log', true) = '1';
    if not allow_attached_log and not inherited_has_attachment then
      raise exception '未附 Fail Log 時必須填寫異常描述';
    end if;
  end if;

  if tg_op = 'UPDATE' and btrim(new.failure_description) = '' then
    select exists (
      select 1 from public.repair_attachments
      where repair_record_id = new.id
    ) into current_has_attachment;
    if not current_has_attachment then
      raise exception '沒有 Fail Log 時必須保留異常描述';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists repair_records_prepare_failure_fields on public.repair_records;
create trigger repair_records_prepare_failure_fields
before insert or update of failure_tag, failure_description on public.repair_records
for each row execute function public.prepare_repair_failure_fields();

create or replace function public.protect_repair_attachment_delete()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_description text;
begin
  if pg_trigger_depth() > 1 then
    return old;
  end if;
  select failure_description into v_description
  from public.repair_records
  where id = old.repair_record_id;
  if found and btrim(coalesce(v_description, '')) = '' then
    raise exception '沒有異常描述時不能刪除最後一份 Fail Log';
  end if;
  return old;
end;
$$;

drop trigger if exists repair_attachments_protect_description on public.repair_attachments;
create trigger repair_attachments_protect_description
before delete on public.repair_attachments
for each row execute function public.protect_repair_attachment_delete();

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
  v_tag text;
  v_description text;
  v_path text;
  v_filename text;
  v_file_size integer;
  v_content_type text;
begin
  v_tag := nullif(btrim(p_payload->>'failure_tag'), '');
  v_description := btrim(coalesce(p_payload->>'failure_description', ''));
  if v_tag is null or v_tag not in (
    'INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER',
    'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA'
  ) then
    raise exception '請選擇有效的異常標籤';
  end if;

  if p_attachment is null then
    if v_description = '' then
      raise exception '未附 Fail Log 時必須填寫異常描述';
    end if;
  else
    v_path := p_attachment->>'storage_path';
    v_filename := p_attachment->>'filename';
    v_file_size := nullif(p_attachment->>'file_size', '')::integer;
    v_content_type := coalesce(nullif(p_attachment->>'content_type', ''), 'text/plain');
    if v_path is null or v_path not like p_record_id::text || '/%'
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
  end if;

  insert into public.repair_records (
    id, current_status, order_status, is_opened, repair_month, item, area,
    machine_code, model, board_part_code, serial_no, description,
    occurred_on, sent_on, returned_on, source_system, source_record_id,
    failure_tag, failure_description
  ) values (
    p_record_id, '待送修', '', false, '', '', '',
    p_payload->>'machine_code', p_payload->>'model', p_payload->>'board_part_code',
    p_payload->>'serial_no', p_payload->>'description',
    nullif(p_payload->>'occurred_on', '')::date, null, null, 'web', null,
    v_tag, v_description
  ) returning * into v_record;

  if p_attachment is not null then
    insert into public.repair_attachments (
      repair_record_id, storage_path, filename, file_size, content_type
    ) values (
      v_record.id, v_path, v_filename, v_file_size, v_content_type
    );
  end if;

  return next v_record;
  return;
end;
$$;
grant execute on function public.create_repair_record_with_failure_info(uuid, jsonb, jsonb) to anon, authenticated;

create or replace function public.save_repair_record_edit_with_failure_info(
  p_record_id uuid,
  p_payload jsonb
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_tag text;
  v_description text;
  v_has_attachment boolean;
begin
  v_tag := nullif(btrim(p_payload->>'failure_tag'), '');
  v_description := btrim(coalesce(p_payload->>'failure_description', ''));
  if v_tag is null or v_tag not in (
    'INIT/DIAG', 'RTE', 'PBDATA', 'CK', 'LEAK', 'OTHER',
    'AUTO SHUTDOWN', 'OVER HEAT', 'ZEBRA'
  ) then
    raise exception '請選擇有效的異常標籤';
  end if;
  select exists (
    select 1 from public.repair_attachments
    where repair_record_id = p_record_id
  ) into v_has_attachment;
  if not v_has_attachment and v_description = '' then
    raise exception '沒有 Fail Log 時必須填寫異常描述';
  end if;

  perform public.save_repair_record_edit(p_record_id, p_payload);
  update public.repair_records
  set failure_tag = v_tag,
      failure_description = v_description
  where id = p_record_id;
  if not found then raise exception '找不到送修案件'; end if;
end;
$$;
grant execute on function public.save_repair_record_edit_with_failure_info(uuid, jsonb) to anon, authenticated;

commit;
