-- Run in Supabase SQL Editor after the repair, DBN and serial catalog migrations.
-- No historical events are synthesized. Only committed future writes are logged.
begin;

create table if not exists public.record_change_history (
  id bigint generated always as identity primary key,
  changed_at timestamptz not null default clock_timestamp(),
  source_table text not null,
  record_key text not null,
  operation text not null check (operation in ('INSERT', 'UPDATE', 'DELETE')),
  serial_no text,
  board_name text,
  changes jsonb not null,
  search_text text generated always as (
    coalesce(serial_no, '') || ' ' || coalesce(board_name, '') || ' ' || changes::text
  ) stored
);
create index if not exists record_change_history_time_idx
  on public.record_change_history (changed_at desc, id desc);
alter table public.record_change_history enable row level security;
revoke all on public.record_change_history from public, anon, authenticated;
grant select on public.record_change_history to anon, authenticated;
drop policy if exists "Public can read change history" on public.record_change_history;
create policy "Public can read change history" on public.record_change_history
  for select to anon, authenticated using (true);

create or replace function public.capture_record_change_history()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  before_row jsonb := '{}'::jsonb;
  after_row jsonb := '{}'::jsonb;
  snapshot jsonb;
  differences jsonb;
begin
  if tg_op <> 'INSERT' then before_row := to_jsonb(old); end if;
  if tg_op <> 'DELETE' then after_row := to_jsonb(new); end if;
  snapshot := case when tg_op = 'DELETE' then before_row else after_row end;

  select coalesce(jsonb_object_agg(field, jsonb_build_object(
    'old', before_row->field, 'new', after_row->field
  )), '{}'::jsonb) into differences
  from (
    select jsonb_object_keys(before_row || after_row) as field
  ) fields
   where field not in ('id', 'created_at', 'updated_at', 'version', 'source_system', 'source_record_id')
    and before_row->field is distinct from after_row->field;

  if tg_op <> 'UPDATE' or differences <> '{}'::jsonb then
    -- Keep the complete DBN identity even when only one component changed.
    if tg_table_name = 'dbn_records' then
      differences := differences || jsonb_build_object('dbn_combination', jsonb_build_object(
        'old', case when tg_op = 'INSERT' then null else jsonb_build_array(
          before_row->>'customer_code', before_row->>'product_code', before_row->>'station_code'
        ) end,
        'new', case when tg_op = 'DELETE' then null else jsonb_build_array(
          after_row->>'customer_code', after_row->>'product_code', after_row->>'station_code'
        ) end
      ));
    end if;
    insert into public.record_change_history (
      source_table, record_key, operation, serial_no, board_name, changes
    ) values (
      tg_table_name,
      coalesce(snapshot->>'id', snapshot->>'serial_no'),
      tg_op,
      snapshot->>'serial_no',
      coalesce(snapshot->>'description', snapshot->>'board_name'),
      differences
    );
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end;
$$;
revoke all on function public.capture_record_change_history() from public;

drop trigger if exists repair_records_capture_changes on public.repair_records;
create trigger repair_records_capture_changes
after insert or update or delete on public.repair_records
for each row execute function public.capture_record_change_history();
drop trigger if exists dbn_records_capture_changes on public.dbn_records;
create trigger dbn_records_capture_changes
after insert or update or delete on public.dbn_records
for each row execute function public.capture_record_change_history();
drop trigger if exists serial_board_mappings_capture_changes on public.serial_board_mappings;
create trigger serial_board_mappings_capture_changes
after insert or update or delete on public.serial_board_mappings
for each row execute function public.capture_record_change_history();

notify pgrst, 'reload schema';
commit;
