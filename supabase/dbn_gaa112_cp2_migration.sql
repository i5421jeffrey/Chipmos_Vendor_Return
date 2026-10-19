-- Add a station option only; preserve CP20 and all existing DBN records.
begin;
insert into public.dbn_valid_combinations (customer_code, product_code, station_code)
values ('AB', 'GAA112', 'CP2')
on conflict (customer_code, product_code, station_code) do nothing;
commit;
