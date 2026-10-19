-- Run after dbn_dut_socket_migration.sql. Existing rows are not classified or rewritten.
begin;
alter table public.dbn_records
  add column if not exists issue_type text,
  add column if not exists issue_description text;

create or replace function public.validate_dbn_issue_type()
returns trigger language plpgsql set search_path = '' as $$
declare
  first_dut integer;
  last_dut integer;
begin
  if new.issue_type is null or new.issue_type not in ('Group', 'Single Dut', 'RTE', 'Other') then
    raise exception '請選擇 DBN 類型';
  end if;
  if new.issue_type in ('RTE', 'Other') then
    new.issue_description := nullif(regexp_replace(new.issue_description, '^\s+|\s+$', '', 'g'), '');
    if new.issue_description is null then
      raise exception '異常描述：此欄位必填';
    end if;
    new.dut := null;
    new.socket_file_id := null;
    new.dut_pin_snapshot := '{}'::jsonb;
    return new;
  end if;
  new.dut := nullif(regexp_replace(btrim(new.dut), '\s*-\s*', '-', 'g'), '');
  if new.dut is null then raise exception 'DUT：此欄位必填'; end if;
  if new.dut !~ '^[0-9]{1,4}(-[0-9]{1,4})?$' then
    raise exception 'DUT 請填寫單一編號或連續範圍';
  end if;
  first_dut := split_part(new.dut, '-', 1)::integer;
  last_dut := case when position('-' in new.dut) > 0
    then split_part(new.dut, '-', 2)::integer else first_dut end;
  if first_dut < 1 or last_dut < first_dut or last_dut > 2048 then
    raise exception 'DUT 須介於 1–2048，結束編號不得小於起始編號';
  end if;
  if new.issue_type = 'Single Dut' and position('-' in new.dut) > 0 then
    raise exception 'Single Dut 請填寫單一 DUT 編號';
  end if;
  if new.issue_type = 'Group' and last_dut - first_dut + 1 > 8 then
    raise exception 'Group 僅接受連續 1–8 個 DUT';
  end if;
  new.issue_description := null;
  return new;
end;
$$;
revoke all on function public.validate_dbn_issue_type() from public;
-- Alphabetical trigger order: classify/clear fields before PIN snapshot preparation.
drop trigger if exists dbn_records_check_issue_type on public.dbn_records;
create trigger dbn_records_check_issue_type before insert or update
on public.dbn_records for each row execute function public.validate_dbn_issue_type();
drop trigger if exists dbn_records_prepare_dut_snapshot on public.dbn_records;
create trigger dbn_records_prepare_dut_snapshot before insert or update
on public.dbn_records for each row execute function public.prepare_dbn_dut_snapshot();
notify pgrst, 'reload schema';
commit;
