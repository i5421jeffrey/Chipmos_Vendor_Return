-- Make S/N -> board name / Part Number the canonical mapping.
-- Run after serial_board_mapping_migration.sql, repair_board_mapping_migration.sql,
-- dbn_machine_board_migration.sql, and the repair classification migration.
begin;

alter table public.serial_board_mappings
  add column if not exists board_part_code text,
  add column if not exists updated_at timestamptz not null default now();

-- The previous catalog tied Model and Part Number with a paired-null check.
-- Drop it before backfilling Part Numbers for rows whose legacy Model is null.
alter table public.serial_board_mappings
  drop constraint if exists serial_board_mappings_model_part_pair_check;

-- Upgrade rows created by the previous catalog migration when they still have
-- the legacy Model column. Model is used only to backfill a Part Number here.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'serial_board_mappings'
      and column_name = 'model'
  ) then
    execute $sql$
      update public.serial_board_mappings mapping
      set board_part_code = boards.board_part_code,
          updated_at = now()
      from public.repair_model_boards boards
      where nullif(btrim(mapping.board_part_code), '') is null
        and mapping.model = boards.model
        and mapping.board_name = boards.board_name
    $sql$;
  end if;
end;
$$;

-- Use recorded Part Numbers first, and derive missing ones from the historical
-- machine Model + board pair. Model is only a backfill source, never catalog data.
with history as (
  select public.normalize_board_serial(r.serial_no) as serial_no,
         nullif(btrim(r.model), '') as model,
         nullif(btrim(r.description), '') as board_name,
         nullif(btrim(r.board_part_code), '') as board_part_code
  from public.repair_records r
  where nullif(btrim(r.serial_no), '') is not null
  union all
  select public.normalize_board_serial(d.serial_no),
         nullif(btrim(d.model), ''),
         nullif(btrim(d.board_name), ''),
         nullif(btrim(d.board_part_code), '')
  from public.dbn_records d
  where nullif(btrim(d.serial_no), '') is not null
), known as (
  select serial_no, board_name, board_part_code
  from history
  where board_part_code is not null
  union all
  select history.serial_no, history.board_name, boards.board_part_code
  from history
  join public.repair_model_boards boards
    on boards.model = history.model
   and boards.board_name = history.board_name
  where history.model is not null
    and history.board_name is not null
), unambiguous as (
  select serial_no, min(board_name) as board_name,
         min(board_part_code) as board_part_code
  from known
  where board_name is not null and board_part_code is not null
  group by serial_no
  having count(distinct board_name) = 1
     and count(distinct board_part_code) = 1
)
update public.serial_board_mappings mapping
set board_part_code = unambiguous.board_part_code,
    updated_at = now()
from unambiguous
where mapping.serial_no = unambiguous.serial_no
  and mapping.board_name = unambiguous.board_name
  and nullif(btrim(mapping.board_part_code), '') is null;

-- If history lacks a Part Number, infer it only when that board name has one
-- canonical Part Number across every Model in the reference table.
with unique_board_parts as (
  select board_name, min(board_part_code) as board_part_code
  from public.repair_model_boards
  group by board_name
  having count(distinct board_part_code) = 1
)
update public.serial_board_mappings mapping
set board_part_code = unique_board_parts.board_part_code,
    updated_at = now()
from unique_board_parts
where mapping.board_name = unique_board_parts.board_name
  and nullif(btrim(mapping.board_part_code), '') is null;

do $$
declare
  unresolved text;
begin
  select string_agg(serial_no, ', ' order by serial_no)
  into unresolved
  from (
    select serial_no
    from public.serial_board_mappings
    where nullif(btrim(board_part_code), '') is null
    order by serial_no
    limit 10
  ) missing;
  if unresolved is not null then
    raise exception '有 S/N 對應無法推定 Part Number，請先釐清並補齊後重跑遷移。前 10 筆：%', unresolved;
  end if;

  if exists (
    select 1
    from public.serial_board_mappings mapping
    where not exists (
      select 1
      from public.repair_model_boards boards
      where boards.board_name = mapping.board_name
        and boards.board_part_code = mapping.board_part_code
    )
  ) then
    raise exception '有 S/N 對應的板件名稱／Part Number 不在 repair_model_boards 參考資料中，請先釐清後重跑遷移';
  end if;
end;
$$;

alter table public.serial_board_mappings
  drop column if exists model;
alter table public.serial_board_mappings
  alter column board_part_code set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'serial_board_mappings_board_part_code_check'
      and conrelid = 'public.serial_board_mappings'::regclass
  ) then
    alter table public.serial_board_mappings
      add constraint serial_board_mappings_board_part_code_check
      check (board_part_code = btrim(board_part_code) and board_part_code <> '');
  end if;
end;
$$;

alter table public.serial_board_mappings enable row level security;
revoke all on public.serial_board_mappings from anon, authenticated;
grant select on public.serial_board_mappings to anon, authenticated;
drop policy if exists "Public can read S/N board mappings" on public.serial_board_mappings;
create policy "Public can read S/N board mappings" on public.serial_board_mappings
  for select to anon, authenticated using (true);

-- Preview counts shown before a mapping edit. A serial rename affects every
-- source-S/N history row; a board / Part Number change affects only mismatches.
create or replace function public.get_serial_board_mapping_impact(
  p_previous_serial_no text,
  p_serial_no text,
  p_board_name text,
  p_board_part_code text
)
returns table (repair_count bigint, dbn_count bigint)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_previous_serial text;
  v_serial text;
  v_board text;
  v_part text;
begin
  v_serial := public.normalize_board_serial(p_serial_no);
  v_previous_serial := case
    when nullif(btrim(p_previous_serial_no), '') is null then null
    else public.normalize_board_serial(p_previous_serial_no)
  end;
  v_board := nullif(btrim(p_board_name), '');
  v_part := nullif(btrim(p_board_part_code), '');
  if v_serial is null or v_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception 'S/N 格式不正確';
  end if;
  if v_previous_serial is not null and v_previous_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '原 S/N 格式不正確';
  end if;
  if v_board is null or v_part is null then
    raise exception '請選擇有效的板件名稱與 Part Number';
  end if;

  return query
  select
    (select count(*)::bigint
     from public.repair_records r
     where public.normalize_board_serial(r.serial_no) in (v_previous_serial, v_serial)
       and (public.normalize_board_serial(r.serial_no) is distinct from v_serial
         or nullif(btrim(r.description), '') is distinct from v_board
         or nullif(btrim(r.board_part_code), '') is distinct from v_part)),
    (select count(*)::bigint
     from public.dbn_records d
     where public.normalize_board_serial(d.serial_no) in (v_previous_serial, v_serial)
       and (public.normalize_board_serial(d.serial_no) is distinct from v_serial
         or nullif(btrim(d.board_name), '') is distinct from v_board
         or nullif(btrim(d.board_part_code), '') is distinct from v_part));
end;
$$;
revoke all on function public.get_serial_board_mapping_impact(text, text, text, text) from public;
grant execute on function public.get_serial_board_mapping_impact(text, text, text, text) to anon, authenticated;

-- Mapping changes and optional history synchronization are one transaction.
drop function if exists public.save_serial_board_mapping(text, text, text);
drop function if exists public.save_serial_board_mapping(text, text, text, text);
drop function if exists public.save_serial_board_mapping(text, text, text, text, boolean);
drop function if exists public.save_serial_board_mapping(text, text, text, text, boolean, bigint, bigint);
create function public.save_serial_board_mapping(
  p_previous_serial_no text,
  p_serial_no text,
  p_board_name text,
  p_board_part_code text,
  p_sync_history boolean,
  p_expected_repair_count bigint,
  p_expected_dbn_count bigint
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_previous_serial text;
  v_serial text;
  v_board text;
  v_part text;
  v_previous_exists boolean;
  v_repair_count bigint;
  v_dbn_count bigint;
begin
  v_serial := public.normalize_board_serial(p_serial_no);
  v_previous_serial := case
    when nullif(btrim(p_previous_serial_no), '') is null then null
    else public.normalize_board_serial(p_previous_serial_no)
  end;
  v_board := nullif(btrim(p_board_name), '');
  v_part := nullif(btrim(p_board_part_code), '');

  if v_serial is null or v_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception 'S/N 格式不正確';
  end if;
  if v_previous_serial is not null and v_previous_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '原 S/N 格式不正確';
  end if;
  if v_board is null or v_part is null then
    raise exception '請選擇有效的板件名稱與 Part Number';
  end if;
  if p_sync_history is null then
    raise exception '請選擇是否同步修正舊資料';
  end if;
  if p_expected_repair_count is null or p_expected_dbn_count is null then
    raise exception '請重新檢查受影響的歷史資料筆數';
  end if;
  if not exists (
    select 1 from public.repair_model_boards
    where board_name = v_board and board_part_code = v_part
  ) then
    raise exception '板件名稱與 Part Number 不在有效參考資料中';
  end if;

  perform serial_no
  from public.serial_board_mappings
  where serial_no in (v_serial, v_previous_serial)
  order by serial_no
  for update;

  if v_previous_serial is not null then
    select exists (
      select 1 from public.serial_board_mappings where serial_no = v_previous_serial
    ) into v_previous_exists;
    if not v_previous_exists then
      raise exception '找不到要修改的原 S/N 對應，請重新搜尋後再試';
    end if;
  end if;
  if v_previous_serial is null or v_previous_serial <> v_serial then
    if exists (select 1 from public.serial_board_mappings where serial_no = v_serial) then
      raise exception '新 S/N 已有對應資料，請先搜尋並修改該筆主檔';
    end if;
  end if;

  select impact.repair_count, impact.dbn_count
  into v_repair_count, v_dbn_count
  from public.get_serial_board_mapping_impact(
    v_previous_serial, v_serial, v_board, v_part
  ) impact;
  if v_repair_count <> p_expected_repair_count
     or v_dbn_count <> p_expected_dbn_count then
    raise exception '受影響歷史筆數已變動（目前 % 筆送修、% 筆 DBN）；請重新儲存以確認最新筆數',
      v_repair_count, v_dbn_count;
  end if;

  if v_previous_serial = v_serial then
    update public.serial_board_mappings
    set board_name = v_board,
        board_part_code = v_part,
        updated_at = now()
    where serial_no = v_serial;
  else
    if v_previous_serial is not null then
      delete from public.serial_board_mappings where serial_no = v_previous_serial;
    end if;
    -- A concurrent create for this S/N fails on the primary key instead of
    -- silently replacing the other writer's master entry.
    insert into public.serial_board_mappings (serial_no, board_name, board_part_code, updated_at)
    values (v_serial, v_board, v_part, now());
  end if;

  if p_sync_history then
    update public.repair_records r
    set serial_no = v_serial,
        description = v_board,
        board_part_code = v_part
    where public.normalize_board_serial(r.serial_no) in (v_previous_serial, v_serial)
      and (public.normalize_board_serial(r.serial_no) is distinct from v_serial
        or nullif(btrim(r.description), '') is distinct from v_board
        or nullif(btrim(r.board_part_code), '') is distinct from v_part);

    update public.dbn_records d
    set serial_no = v_serial,
        board_name = v_board,
        board_part_code = v_part
    where public.normalize_board_serial(d.serial_no) in (v_previous_serial, v_serial)
      and (public.normalize_board_serial(d.serial_no) is distinct from v_serial
        or nullif(btrim(d.board_name), '') is distinct from v_board
        or nullif(btrim(d.board_part_code), '') is distinct from v_part);
  end if;
end;
$$;
revoke all on function public.save_serial_board_mapping(text, text, text, text, boolean, bigint, bigint) from public;
grant execute on function public.save_serial_board_mapping(text, text, text, text, boolean, bigint, bigint) to anon, authenticated;

-- Auto-create missing mappings on successful repair / DBN writes and reject any
-- later record whose board name or Part Number conflicts with the master.
drop trigger if exists repair_records_enforce_serial_board on public.repair_records;
drop trigger if exists dbn_records_enforce_serial_board on public.dbn_records;
drop trigger if exists repair_records_enforce_serial_catalog_mapping on public.repair_records;
drop trigger if exists dbn_records_enforce_serial_catalog_mapping on public.dbn_records;
drop function if exists public.enforce_serial_board_mapping();
create or replace function public.enforce_serial_board_catalog_mapping()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_serial text;
  v_record_board text;
  v_record_part text;
  v_mapping_board text;
  v_mapping_part text;
begin
  v_serial := public.normalize_board_serial(new.serial_no);
  if v_serial is null or v_serial = '' then
    return new;
  end if;
  new.serial_no := v_serial;

  if tg_table_name = 'repair_records' then
    v_record_board := nullif(btrim(new.description), '');
  else
    v_record_board := nullif(btrim(new.board_name), '');
  end if;
  v_record_part := nullif(btrim(new.board_part_code), '');
  if v_record_board is null or v_record_part is null then
    select board_name, board_part_code
    into v_mapping_board, v_mapping_part
    from public.serial_board_mappings
    where serial_no = v_serial
    for update;
    if found and (
      v_record_board is distinct from v_mapping_board
      or v_record_part is distinct from v_mapping_part
    ) then
      raise exception 'S/N % 主檔已登記為「%」／Part Number %，紀錄缺少或不符合主檔資料；請先至 S/N 對應功能修正主檔',
        v_serial, v_mapping_board, v_mapping_part;
    end if;
    return new;
  end if;
  if not exists (
    select 1 from public.repair_model_boards
    where board_name = v_record_board and board_part_code = v_record_part
  ) then
    raise exception '板件名稱與 Part Number 不在有效參考資料中';
  end if;

  insert into public.serial_board_mappings (serial_no, board_name, board_part_code, updated_at)
  values (v_serial, v_record_board, v_record_part, now())
  on conflict (serial_no) do nothing;

  select board_name, board_part_code
  into v_mapping_board, v_mapping_part
  from public.serial_board_mappings
  where serial_no = v_serial
  for update;

  if v_record_board is distinct from v_mapping_board
     or v_record_part is distinct from v_mapping_part then
    raise exception 'S/N % 主檔已登記為「%」／Part Number %，不可新增或修改為「%」／Part Number %；請先至 S/N 對應功能修正主檔',
      v_serial, v_mapping_board, v_mapping_part, v_record_board, v_record_part;
  end if;
  return new;
end;
$$;

create trigger repair_records_enforce_serial_catalog_mapping
before insert or update of serial_no, model, description, board_part_code
on public.repair_records
for each row execute function public.enforce_serial_board_catalog_mapping();

create trigger dbn_records_enforce_serial_catalog_mapping
before insert or update of serial_no, model, board_name, board_part_code
on public.dbn_records
for each row execute function public.enforce_serial_board_catalog_mapping();

-- Editing one repair must not silently rewrite every historical row sharing its
-- S/N. The catalog RPC above is the only flow that offers explicit bulk sync.
create or replace function public.save_repair_record_edit(p_record_id uuid, p_payload jsonb)
returns void
language plpgsql
security definer
set search_path = ''
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

  select id into v_existing_id
  from public.repair_records
  where id = p_record_id
  for update;
  if not found then
    raise exception '找不到送修案件';
  end if;

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
      current_status = case
        when current_status in ('待送修', '已送修', '取回驗證')
          then coalesce(p_payload->>'current_status', current_status)
        else current_status
      end
  where id = p_record_id;
end;
$$;
revoke all on function public.save_repair_record_edit(uuid, jsonb) from public;
grant execute on function public.save_repair_record_edit(uuid, jsonb) to anon, authenticated;

notify pgrst, 'reload schema';
commit;
