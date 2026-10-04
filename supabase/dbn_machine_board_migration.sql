-- Add required machine / board snapshots to DBN records.
-- Existing DBN records remain valid with null machine/board fields.
-- New inserts are validated against repair_machine_models and repair_model_boards.
-- Run after the repair board-mapping migration in Supabase SQL Editor.
begin;

alter table public.dbn_records
  add column if not exists machine_code text,
  add column if not exists model text,
  add column if not exists board_name text,
  add column if not exists board_part_code text;

alter table public.dbn_records
  drop constraint if exists dbn_records_machine_board_all_or_none_check;
alter table public.dbn_records
  add constraint dbn_records_machine_board_all_or_none_check
  check (
    (machine_code is null and model is null and board_name is null and board_part_code is null)
    or (machine_code is not null and model is not null and board_name is not null and board_part_code is not null)
  );

create or replace function public.validate_dbn_machine_board()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  mapped_model text;
  mapped_part_number text;
begin
  if new.machine_code is null or new.machine_code = ''
    or new.model is null or new.model = ''
    or new.board_name is null or new.board_name = ''
    or new.board_part_code is null or new.board_part_code = '' then
    raise exception 'DBN 紀錄必須選擇機台與板件名稱';
  end if;

  select model into mapped_model
  from public.repair_machine_models
  where machine_code = new.machine_code;
  if not found then
    raise exception '機台編號不在有效清單中';
  end if;
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

drop trigger if exists dbn_records_validate_machine_board on public.dbn_records;
create trigger dbn_records_validate_machine_board
before insert or update on public.dbn_records
for each row execute function public.validate_dbn_machine_board();

commit;
