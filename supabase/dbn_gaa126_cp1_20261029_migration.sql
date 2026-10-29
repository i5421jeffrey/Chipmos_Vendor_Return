-- Add the user-confirmed AB / GAA126 / CP1 option only.
-- Preserve all existing combinations and DBN records.
begin;
insert into public.dbn_customers (customer_code)
values ('AB') on conflict (customer_code) do nothing;
insert into public.dbn_valid_combinations (customer_code, product_code, station_code)
values ('AB', 'GAA126', 'CP1')
on conflict (customer_code, product_code, station_code) do nothing;
notify pgrst, 'reload schema';
commit;
