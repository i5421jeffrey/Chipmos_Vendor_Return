-- Allow deleting a single DBN record from the public repair page.
-- This only affects DBN records; serial_board_mappings are deliberately kept.
begin;

grant delete on public.dbn_records to anon, authenticated;

drop policy if exists "Public can delete DBN records" on public.dbn_records;
create policy "Public can delete DBN records" on public.dbn_records
  for delete to anon, authenticated using (true);

commit;
