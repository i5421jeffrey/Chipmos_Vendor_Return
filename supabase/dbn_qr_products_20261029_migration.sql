-- Add 6 QR products, each with CP1/CP2/CP3/CP4/CP5/CP7/CP9 (42 combinations).
-- No Socket File, existing combinations, or DBN records are changed.
begin;
insert into public.dbn_customers (customer_code)
values ('QR') on conflict (customer_code) do nothing;

insert into public.dbn_valid_combinations (customer_code, product_code, station_code)
select 'QR', products.product_code, stations.station_code
from (values ('LB128E'), ('LB256K'), ('LB512M'), ('LE128E'), ('LE16E'), ('LE32D'))
  as products(product_code)
cross join (values ('CP1'), ('CP2'), ('CP3'), ('CP4'), ('CP5'), ('CP7'), ('CP9'))
  as stations(station_code)
on conflict (customer_code, product_code, station_code) do nothing;

notify pgrst, 'reload schema';
commit;
