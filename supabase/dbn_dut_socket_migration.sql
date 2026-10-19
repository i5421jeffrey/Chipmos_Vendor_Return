-- Optional DUT and immutable per-record customer PIN snapshots.
begin;
create table if not exists public.dbn_socket_files (
  id text not null,
  product_code text not null,
  source_filename text not null,
  source_bytes bytea not null,
  dut_count integer not null check (dut_count between 1 and 2048),
  dut_pins jsonb not null check (jsonb_typeof(dut_pins) = 'object'),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (product_code, id)
);
create unique index if not exists dbn_socket_one_active_product
  on public.dbn_socket_files (product_code) where is_active;
alter table public.dbn_socket_files enable row level security;
revoke all on public.dbn_socket_files from public, anon, authenticated;
grant select on public.dbn_socket_files to anon, authenticated;
drop policy if exists "Public can read socket files" on public.dbn_socket_files;
create policy "Public can read socket files" on public.dbn_socket_files
  for select to anon, authenticated using (true);

alter table public.dbn_records
  add column if not exists dut text,
  add column if not exists socket_file_id text,
  add column if not exists dut_pin_snapshot jsonb not null default '{}'::jsonb;
-- No automatic backfill: old records stay blank until edited by the user.

create or replace function public.prepare_dbn_dut_snapshot()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare
  first_dut integer;
  last_dut integer;
  selected_file public.dbn_socket_files%rowtype;
begin
  new.dut := nullif(regexp_replace(btrim(new.dut), '\s*-\s*', '-', 'g'), '');
  if new.dut is null then
    new.socket_file_id := null;
    new.dut_pin_snapshot := '{}'::jsonb;
    return new;
  end if;
  if new.dut !~ '^[0-9]{1,4}(-[0-9]{1,4})?$' then
    raise exception 'DUT 請輸入單一編號或連續範圍，例如 39、21-28';
  end if;
  first_dut := split_part(new.dut, '-', 1)::integer;
  last_dut := case when position('-' in new.dut) > 0
    then split_part(new.dut, '-', 2)::integer else first_dut end;
  if first_dut < 1 or last_dut < first_dut or last_dut > 2048 then
    raise exception 'DUT 編號須介於 1–2048，結束編號不得小於起始編號';
  end if;
  new.dut := case when first_dut = last_dut then first_dut::text
    else first_dut::text || '-' || last_dut::text end;

  -- Unrelated edits retain the historical version, not the latest socket file.
  if tg_op = 'UPDATE' then
    if new.dut is not distinct from old.dut
       and new.product_code is not distinct from old.product_code
       and old.socket_file_id is not null then
      new.socket_file_id := old.socket_file_id;
      new.dut_pin_snapshot := old.dut_pin_snapshot;
      return new;
    end if;
  end if;
  select * into selected_file from public.dbn_socket_files
    where product_code = new.product_code and is_active;
  if not found then
    new.socket_file_id := null;
    new.dut_pin_snapshot := '{}'::jsonb;
    return new;
  end if;
  if last_dut > selected_file.dut_count then
    raise exception '此產品的 Socket File 僅定義 DUT1–DUT%', selected_file.dut_count;
  end if;
  new.socket_file_id := selected_file.id;
  select coalesce(jsonb_object_agg(dut_no::text, selected_file.dut_pins->dut_no::text order by dut_no), '{}'::jsonb)
    into new.dut_pin_snapshot
    from generate_series(first_dut, last_dut) as selection(dut_no)
    where selected_file.dut_pins ? dut_no::text;
  return new;
end;
$$;
revoke all on function public.prepare_dbn_dut_snapshot() from public;
drop trigger if exists dbn_records_prepare_dut_snapshot on public.dbn_records;
create trigger dbn_records_prepare_dut_snapshot
before insert or update of dut, product_code, socket_file_id, dut_pin_snapshot
on public.dbn_records for each row execute function public.prepare_dbn_dut_snapshot();
notify pgrst, 'reload schema';
commit;
