-- Create standalone DBN records and the customer/product/station cascading list.
-- Run once in Supabase Dashboard > SQL Editor after reviewing public access policies.
begin;

create table if not exists public.dbn_customers (
  customer_code text primary key check (customer_code = trim(customer_code) and customer_code <> '')
);

create table if not exists public.dbn_valid_combinations (
  customer_code text not null references public.dbn_customers(customer_code) on update cascade on delete restrict,
  product_code text not null check (product_code = trim(product_code) and product_code <> '' and product_code <> '-'),
  station_code text not null check (station_code = trim(station_code) and station_code <> '' and station_code <> '-'),
  primary key (customer_code, product_code, station_code)
);

create table if not exists public.dbn_records (
  id uuid primary key default gen_random_uuid(),
  serial_no text not null check (serial_no ~ '^[0-9]{9}$'),
  customer_code text not null references public.dbn_customers(customer_code) on update cascade on delete restrict,
  product_code text,
  station_code text,
  created_at timestamptz not null default now(),
  constraint dbn_records_product_station_pair_check
    check ((product_code is null and station_code is null) or (product_code is not null and station_code is not null)),
  constraint dbn_records_valid_combination_fk
    foreign key (customer_code, product_code, station_code)
    references public.dbn_valid_combinations(customer_code, product_code, station_code)
    on update cascade on delete restrict
);

insert into public.dbn_customers (customer_code) values
  ('AB'), ('QR'), ('VB')
on conflict (customer_code) do nothing;

insert into public.dbn_valid_combinations (customer_code, product_code, station_code) values
  ('AB', 'JAA118', 'CP1'), ('AB', 'JAA118', 'CP2'),
  ('AB', 'GAA115', 'CP1'), ('AB', 'GAA115', 'CP2'),
  ('AB', 'JAA125', 'CP1'), ('AB', 'JAA125', 'CP2'),
  ('AB', 'JAA125', 'CP3'), ('AB', 'JAA125', 'CP4'),
  ('AB', 'CAA100', 'CP1'), ('AB', 'CAA100', 'CP2'),
  ('AB', 'CAA100', 'CP3'),
  ('AB', 'GAA098', 'CP1'), ('AB', 'GAA098', 'CP2'),
  ('AB', 'GAA112', 'CP1'), ('AB', 'GAA112', 'CP4'),
  ('AB', 'GAA112', 'CP20'),
  ('AB', 'GAA102', 'CP1'), ('AB', 'GAA102', 'CP2'),
  ('AB', 'GAA128', 'CP1'), ('AB', 'GAA128', 'CP2'),
  ('AB', 'GAA108', 'CP1'), ('AB', 'GAA108', 'CP2'),
  ('AB', 'GAA108', 'CP3'),
  ('AB', 'GAA110', 'CP1'), ('AB', 'GAA110', 'CP2'),
  ('AB', 'CAA099', 'CP1')
on conflict do nothing;

create index if not exists dbn_records_serial_created_idx
  on public.dbn_records (serial_no, created_at desc);
create index if not exists dbn_records_context_idx
  on public.dbn_records (customer_code, product_code, station_code, created_at desc);

alter table public.dbn_customers enable row level security;
alter table public.dbn_valid_combinations enable row level security;
alter table public.dbn_records enable row level security;

grant usage on schema public to anon, authenticated;
grant select on public.dbn_customers, public.dbn_valid_combinations to anon, authenticated;
grant select, insert on public.dbn_records to anon, authenticated;

drop policy if exists "Public can read DBN customers" on public.dbn_customers;
create policy "Public can read DBN customers" on public.dbn_customers
  for select to anon, authenticated using (true);
drop policy if exists "Public can read DBN valid combinations" on public.dbn_valid_combinations;
create policy "Public can read DBN valid combinations" on public.dbn_valid_combinations
  for select to anon, authenticated using (true);
drop policy if exists "Public can read DBN records" on public.dbn_records;
create policy "Public can read DBN records" on public.dbn_records
  for select to anon, authenticated using (true);
drop policy if exists "Public can create DBN records" on public.dbn_records;
create policy "Public can create DBN records" on public.dbn_records
  for insert to anon, authenticated with check (true);

commit;
