-- Add independently managed S/N -> model/board catalog entries.
-- Run after serial_board_mapping_migration.sql and the machine/model/board mappings.
begin;

alter table public.serial_board_mappings
  add column if not exists model text,
  add column if not exists board_part_code text;

-- Backfill only when existing repair/DBN history unambiguously identifies the
-- model and board. Part Number always comes from the canonical model/board map.
with known as (
  select
    public.normalize_board_serial(serial_no) as serial_no,
    nullif(btrim(model), '') as model,
    nullif(btrim(description), '') as board_name
  from public.repair_records
  where serial_no is not null and btrim(serial_no) <> ''
  union all
  select
    public.normalize_board_serial(serial_no),
    nullif(btrim(model), ''),
    nullif(btrim(board_name), '')
  from public.dbn_records
  where serial_no is not null and btrim(serial_no) <> ''
), unambiguous as (
  select serial_no, min(model) as model, min(board_name) as board_name
  from known
  where model is not null and board_name is not null
  group by serial_no
  having count(distinct model) = 1 and count(distinct board_name) = 1
)
update public.serial_board_mappings mapping
set model = unambiguous.model,
    board_part_code = boards.board_part_code,
    updated_at = now()
from unambiguous
join public.repair_model_boards boards
  on boards.model = unambiguous.model
 and boards.board_name = unambiguous.board_name
where mapping.serial_no = unambiguous.serial_no
  and mapping.board_name = unambiguous.board_name
  and boards.board_part_code <> '';

-- If history did not record a model, infer it only when this board name belongs
-- to exactly one model in the canonical reference table.
with unique_boards as (
  select min(model) as model, board_name, min(board_part_code) as board_part_code
  from public.repair_model_boards
  group by board_name
  having count(*) = 1
)
update public.serial_board_mappings mapping
set model = unique_boards.model,
    board_part_code = unique_boards.board_part_code,
    updated_at = now()
from unique_boards
where mapping.model is null
  and mapping.board_name = unique_boards.board_name
  and unique_boards.board_part_code <> ''
  and not exists (
    select 1
    from (
      select nullif(btrim(r.model), '') as model,
             nullif(btrim(r.description), '') as board_name
      from public.repair_records r
      where public.normalize_board_serial(r.serial_no) = mapping.serial_no
      union all
      select nullif(btrim(d.model), ''), nullif(btrim(d.board_name), '')
      from public.dbn_records d
      where public.normalize_board_serial(d.serial_no) = mapping.serial_no
    ) history
    where (history.model is not null and history.model <> unique_boards.model)
       or (history.board_name is not null and history.board_name <> unique_boards.board_name)
  );

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'serial_board_mappings_model_part_pair_check'
      and conrelid = 'public.serial_board_mappings'::regclass
  ) then
    alter table public.serial_board_mappings
      add constraint serial_board_mappings_model_part_pair_check
      check ((model is null and board_part_code is null)
        or (model is not null and board_part_code is not null));
  end if;
end;
$$;

-- Public clients can write through this validated RPC, but do not receive raw
-- INSERT/UPDATE/DELETE permissions on the catalog table.
drop function if exists public.save_serial_board_mapping(text, text, text);
drop function if exists public.save_serial_board_mapping(text, text, text, text);
create function public.save_serial_board_mapping(
  p_previous_serial_no text,
  p_serial_no text,
  p_model text,
  p_board_name text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_serial text;
  v_model text;
  v_board text;
  v_part text;
  v_previous_serial text;
  v_previous_exists boolean;
begin
  v_serial := public.normalize_board_serial(p_serial_no);
  v_previous_serial := case
    when nullif(btrim(p_previous_serial_no), '') is null then null
    else public.normalize_board_serial(p_previous_serial_no)
  end;
  v_model := nullif(btrim(p_model), '');
  v_board := nullif(btrim(p_board_name), '');

  if v_serial is null or v_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception 'S/N 格式不正確';
  end if;
  if v_previous_serial is not null and v_previous_serial !~ '^[^[:cntrl:]]{1,64}$' then
    raise exception '原 S/N 格式不正確';
  end if;
  if v_model is null or v_board is null then
    raise exception '請選擇 Model 與板件名稱';
  end if;

  select board_part_code into v_part
  from public.repair_model_boards
  where model = v_model and board_name = v_board;
  if not found or v_part is null or v_part = '' then
    raise exception '板件名稱不屬於所選 Model，或尚未設定 Part Number';
  end if;

  perform serial_no
  from public.serial_board_mappings
  where serial_no = v_serial or serial_no = v_previous_serial
  order by serial_no
  for update;

  if v_previous_serial is null then
    if exists (select 1 from public.serial_board_mappings where serial_no = v_serial) then
      raise exception '此 S/N 已有對應資料，請先搜尋並按「修改」';
    end if;
  elsif v_previous_serial <> v_serial then
    select exists (
      select 1 from public.serial_board_mappings where serial_no = v_previous_serial
    ) into v_previous_exists;
    if not v_previous_exists then
      raise exception '找不到要修改的原 S/N 對應，請重新搜尋後再試';
    end if;
    if exists (
      select 1 from public.repair_records r
      where public.normalize_board_serial(r.serial_no) = v_previous_serial
      union all
      select 1 from public.dbn_records d
      where public.normalize_board_serial(d.serial_no) = v_previous_serial
    ) then
      raise exception '原 S/N 已有送修或 DBN 歷史，為保留歷史關聯，無法更改 S/N';
    end if;
    if exists (select 1 from public.serial_board_mappings where serial_no = v_serial) then
      raise exception '新 S/N 已有對應資料，請先搜尋並確認是否為重複資料';
    end if;
    delete from public.serial_board_mappings where serial_no = v_previous_serial;
  else
    select exists (
      select 1 from public.serial_board_mappings where serial_no = v_previous_serial
    ) into v_previous_exists;
    if not v_previous_exists then
      raise exception '找不到要修改的 S/N 對應，請重新搜尋後再試';
    end if;
  end if;

  if exists (
    select 1
    from public.repair_records r
    where public.normalize_board_serial(r.serial_no) = v_serial
      and (
        (nullif(btrim(r.model), '') is not null and btrim(r.model) <> v_model)
        or (nullif(btrim(r.description), '') is not null and btrim(r.description) <> v_board)
        or (nullif(btrim(r.board_part_code), '') is not null and btrim(r.board_part_code) <> v_part)
      )
  ) then
    raise exception '此 S/N 的送修歷史與所選 Model／板件不一致，為避免修改歷史關聯，未儲存對應';
  end if;

  if exists (
    select 1
    from public.dbn_records d
    where public.normalize_board_serial(d.serial_no) = v_serial
      and (
        (nullif(btrim(d.model), '') is not null and btrim(d.model) <> v_model)
        or (nullif(btrim(d.board_name), '') is not null and btrim(d.board_name) <> v_board)
        or (nullif(btrim(d.board_part_code), '') is not null and btrim(d.board_part_code) <> v_part)
      )
  ) then
    raise exception '此 S/N 的 DBN 歷史與所選 Model／板件不一致，為避免修改歷史關聯，未儲存對應';
  end if;

  insert into public.serial_board_mappings (serial_no, board_name, model, board_part_code, updated_at)
  values (v_serial, v_board, v_model, v_part, now())
  on conflict (serial_no) do update
    set board_name = excluded.board_name,
        model = excluded.model,
        board_part_code = excluded.board_part_code,
        updated_at = excluded.updated_at;
end;
$$;

revoke all on function public.save_serial_board_mapping(text, text, text, text) from public;
grant execute on function public.save_serial_board_mapping(text, text, text, text) to anon, authenticated;

-- Keep independently maintained catalog entries authoritative: later repair
-- or DBN edits must not silently associate the same S/N with another model.
create or replace function public.enforce_serial_board_catalog_mapping()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_serial text;
  v_record_model text;
  v_record_board text;
  v_record_part text;
  v_mapping_model text;
  v_mapping_board text;
  v_mapping_part text;
begin
  v_serial := public.normalize_board_serial(new.serial_no);
  if v_serial is null or v_serial = '' then
    return new;
  end if;

  v_record_model := nullif(btrim(new.model), '');
  v_record_part := nullif(btrim(new.board_part_code), '');
  if tg_table_name = 'repair_records' then
    v_record_board := nullif(btrim(new.description), '');
  else
    v_record_board := nullif(btrim(new.board_name), '');
  end if;

  select model, board_name, board_part_code
    into v_mapping_model, v_mapping_board, v_mapping_part
  from public.serial_board_mappings
  where serial_no = v_serial;

  if not found or v_mapping_model is null then
    return new;
  end if;
  if v_record_model is distinct from v_mapping_model then
    raise exception 'S/N % 已登記為 Model %，不可新增或修改為 Model %',
      v_serial, v_mapping_model, v_record_model;
  end if;
  if v_record_board is distinct from v_mapping_board then
    raise exception 'S/N % 已登記為板件「%」，不可新增或修改為「%」',
      v_serial, v_mapping_board, v_record_board;
  end if;
  if v_record_part is distinct from v_mapping_part then
    raise exception 'S/N % 已登記為 Part Number %，不可新增或修改為 %',
      v_serial, v_mapping_part, v_record_part;
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_enforce_serial_catalog_mapping on public.repair_records;
create trigger repair_records_enforce_serial_catalog_mapping
before insert or update of serial_no, model, description, board_part_code
on public.repair_records
for each row execute function public.enforce_serial_board_catalog_mapping();

drop trigger if exists dbn_records_enforce_serial_catalog_mapping on public.dbn_records;
create trigger dbn_records_enforce_serial_catalog_mapping
before insert or update of serial_no, model, board_name, board_part_code
on public.dbn_records
for each row execute function public.enforce_serial_board_catalog_mapping();

notify pgrst, 'reload schema';
commit;
