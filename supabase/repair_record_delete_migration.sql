-- Enable deleting repair records from the unauthenticated static repair page.
-- WARNING: the existing application is public and has no login; anyone with
-- access to the page/API can permanently delete repair records.
-- Run once in Supabase Dashboard > SQL Editor.
begin;

grant delete on public.repair_records to anon, authenticated;

drop policy if exists "Public can delete repair records" on public.repair_records;
create policy "Public can delete repair records" on public.repair_records
  for delete to public using (true);

commit;
