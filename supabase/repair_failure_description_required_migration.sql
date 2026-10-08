-- Require descriptions for new repairs, retries, and edits to descriptions.
-- Existing rows are not rewritten; unrelated status/catalog updates remain valid.
begin;

create or replace function public.require_repair_failure_description()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.failure_description is null
     or new.failure_description !~ '[^[:space:]]' then
    raise exception '異常描述為必填，附上 Fail Log 也必須填寫。'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_require_failure_description
  on public.repair_records;
create trigger repair_records_require_failure_description
before insert or update of failure_description on public.repair_records
for each row execute function public.require_repair_failure_description();

notify pgrst, 'reload schema';
commit;
