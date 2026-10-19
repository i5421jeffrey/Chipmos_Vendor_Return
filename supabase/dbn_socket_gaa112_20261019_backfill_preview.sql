-- Read-only preview. Run the GAA112 seed first, then review these counts.
-- No issue types or DUT values are inferred or changed.
with socket as (
  select id, dut_count, dut_pins from public.dbn_socket_files
  where product_code = 'GAA112' and is_active
    and id = '9c0479eb81bea6bba1a8529332a66ad9ca301058002f059b262c63fca98d4fb9'
), parsed as (
  select r.*, to_jsonb(r)->>'issue_type' as existing_issue_type,
    case when r.dut ~ '^[0-9]{1,4}(-[0-9]{1,4})?$'
      then split_part(r.dut, '-', 1)::integer end as first_dut,
    case when r.dut ~ '^[0-9]{1,4}(-[0-9]{1,4})?$'
      then split_part(r.dut, '-', case when position('-' in r.dut) > 0 then 2 else 1 end)::integer end as last_dut
  from public.dbn_records r where r.product_code = 'GAA112'
), eligible as (
  select p.*, s.id as target_id, pins.snapshot
  from parsed p cross join socket s
  cross join lateral (
    select jsonb_object_agg(n::text, s.dut_pins->n::text) as snapshot,
      count(*) filter (where jsonb_typeof(s.dut_pins->n::text) = 'array'
        and s.dut_pins->n::text <> '[]'::jsonb) as mapped_count
    from generate_series(p.first_dut, p.last_dut) n
    where p.first_dut >= 1 and p.last_dut between p.first_dut and s.dut_count
  ) pins
  where p.first_dut >= 1 and p.last_dut between p.first_dut and s.dut_count
    and (p.existing_issue_type is null or p.existing_issue_type in ('Group', 'Single Dut'))
    and (p.existing_issue_type is distinct from 'Group' or p.last_dut - p.first_dut + 1 <= 8)
    and (p.existing_issue_type is distinct from 'Single Dut' or position('-' in p.dut) = 0)
    and pins.mapped_count = p.last_dut - p.first_dut + 1
)
select
  exists(select 1 from socket) as expected_socket_active,
  (select count(*) from parsed) as gaa112_total,
  (select count(*) from eligible) as eligible_records,
  (select count(*) from eligible where socket_file_id is distinct from target_id
    or dut_pin_snapshot is distinct from snapshot) as records_to_update,
  (select count(*) from parsed) - (select count(*) from eligible) as skipped_records;
