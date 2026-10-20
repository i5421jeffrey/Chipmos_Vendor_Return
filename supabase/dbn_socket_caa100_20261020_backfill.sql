-- Run the matching CAA100 seed, then backfill_preview.sql; review counts FIRST.
-- Fill completely empty PIN snapshots only. DUT/type and existing PINs unchanged.
-- Blank/invalid DUTs and RTE/Other are skipped; legacy types are not inferred.
-- Requires table-owner privileges (Supabase SQL Editor). Audit stays enabled.
begin;
set local lock_timeout = '10s';
lock table public.dbn_socket_files in share mode;
lock table public.dbn_records in access exclusive mode;

do $$
begin
  if not exists (
    select 1 from public.dbn_socket_files where product_code = 'CAA100'
      and id = 'a3b01af6549af1712dcd6638a0c695a88bb6e3c5553b5a1cc68d0ec1ad104139'
      and is_active and dut_count = 1024
  ) then
    raise exception 'Run dbn_socket_caa100_20261020_seed.sql first; expected active version missing';
  end if;
end;
$$;

create temporary table caa100_snapshot_updates on commit drop as
with socket as (
  select id, dut_count, dut_pins from public.dbn_socket_files
  where product_code = 'CAA100' and is_active and dut_count = 1024
    and id = 'a3b01af6549af1712dcd6638a0c695a88bb6e3c5553b5a1cc68d0ec1ad104139'
), parsed as (
  select r.*, to_jsonb(r)->>'issue_type' as existing_issue_type,
    case when r.dut ~ '^[0-9]{1,4}(-[0-9]{1,4})?$'
      then split_part(r.dut, '-', 1)::integer end as first_dut,
    case when r.dut ~ '^[0-9]{1,4}(-[0-9]{1,4})?$'
      then split_part(r.dut, '-', case when position('-' in r.dut) > 0 then 2 else 1 end)::integer end as last_dut
  from public.dbn_records r where r.product_code = 'CAA100'
), eligible as (
  select p.id, s.id as target_id, pins.snapshot
  from parsed p cross join socket s
  cross join lateral (
    select jsonb_object_agg(n::text, s.dut_pins->n::text) as snapshot,
      count(*) filter (where jsonb_typeof(s.dut_pins->n::text) = 'array'
        and s.dut_pins->n::text <> '[]'::jsonb) as mapped_count
    from generate_series(p.first_dut, p.last_dut) n
    where p.first_dut >= 1 and p.last_dut between p.first_dut and s.dut_count
  ) pins
  where (p.dut_pin_snapshot is null or p.dut_pin_snapshot = '{}'::jsonb)
    and p.first_dut >= 1 and p.last_dut between p.first_dut and s.dut_count
    and (p.existing_issue_type is null or p.existing_issue_type in ('Group', 'Single Dut'))
    and (p.existing_issue_type is distinct from 'Group' or p.last_dut - p.first_dut + 1 <= 8)
    and (p.existing_issue_type is distinct from 'Single Dut' or position('-' in p.dut) = 0)
    and pins.mapped_count = p.last_dut - p.first_dut + 1
)
select * from eligible;

-- Bypass only classification/snapshot-preservation triggers for this transaction.
-- Keep audit and other triggers enabled; restore original trigger modes below.
create temporary table caa100_saved_trigger_states on commit drop as
select tgname, tgenabled from pg_trigger
where tgrelid = 'public.dbn_records'::regclass and not tgisinternal
  and tgname in ('dbn_records_check_issue_type', 'dbn_records_prepare_dut_snapshot');
do $$
declare t record;
begin
  for t in select * from caa100_saved_trigger_states loop
    execute format('alter table public.dbn_records disable trigger %I', t.tgname);
  end loop;
end;
$$;

with updated as (
  update public.dbn_records r
  set socket_file_id = u.target_id, dut_pin_snapshot = u.snapshot
  from caa100_snapshot_updates u
  where r.id = u.id and r.product_code = 'CAA100'
    and (r.dut_pin_snapshot is null or r.dut_pin_snapshot = '{}'::jsonb)
  returning r.id
)
select count(*) as updated_records from updated;

do $$
declare t record;
begin
  for t in select * from caa100_saved_trigger_states loop
    execute format('alter table public.dbn_records %s trigger %I',
      case t.tgenabled when 'D' then 'disable' when 'R' then 'enable replica'
        when 'A' then 'enable always' else 'enable' end, t.tgname);
  end loop;
  if exists (
    select 1 from caa100_snapshot_updates u join public.dbn_records r on r.id = u.id
    where r.socket_file_id is distinct from u.target_id
      or r.dut_pin_snapshot is distinct from u.snapshot
  ) then
    raise exception 'Snapshot verification failed; roll back the entire transaction';
  end if;
end;
$$;
-- Any failure requires ROLLBACK; trigger DDL and updates roll back together.
commit;
