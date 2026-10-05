-- Compatibility update for installations that already applied an older
-- repair_classification_statistics_migration.sql. The current initial
-- migration includes these changes; do not run both on a fresh installation.
begin;

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
  if new.repair_amount < 0 then
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

alter table public.repair_records
  alter column repair_amount set default 1,
  alter column repair_amount set not null;

commit;
