-- Machine-directory import from 機台資料_20261003 (1).csv.
-- CSV machine number Sxx is the web/database code Fxx; R05/R07/R09 are normalized to R5/R7/R9.
-- Machine serial and machine name are stored as separate fields and are not rendered on the repair webpage.
-- Run once in Supabase Dashboard > SQL Editor. Safe to re-run; updates matching machines, does not delete rows absent from the CSV.
begin;

alter table public.repair_machines
  add column if not exists machine_serial text not null default '',
  add column if not exists machine_name text not null default '';

-- Update matches by original CSV machine number before changing names, avoiding stale duplicate rows.
update public.repair_machines as m
set machine_code = s.machine_code,
    tester_id = s.machine_name,
    machine_name = s.machine_name,
    machine_serial = s.machine_serial,
    model = s.model,
    source_machine_number = s.source_machine_number
from (values
  ('R5', '310108452', 'PMOS2', 'T5377', 'R05'),
  ('R7', '310178961', 'SMIC2', 'T5377', 'R07'),
  ('R9', '310352914', 'INF29', 'T5377', 'R09'),
  ('F14', '562100462', 'YURA33', 'T5377S', 'S14'),
  ('F19', '310379891', 'TAS05', 'T5377S', 'S19'),
  ('F20', '310294599', 'TERA76', 'T5377S', 'S20'),
  ('F21', '310263797', 'TERA43', 'T5377S', 'S21'),
  ('F22', '310334454', 'C05M7T', 'T5377S', 'S22'),
  ('F28', '310262653', 'TERA36', 'T5377S', 'S28'),
  ('F36', '310249705', 'TERA13', 'T5377S', 'S36'),
  ('F39', '310370600', 'REX22', 'T5377S', 'S39'),
  ('F40', '310373783', 'REX28', 'T5377S', 'S40'),
  ('F41', '310369292', 'PSC132', 'T5377S', 'S41'),
  ('F42', '310368425', 'PMOST32', 'T5377S', 'S42'),
  ('F45', '310280213', 'PMOST11', 'T5377S', 'S45'),
  ('F46', '310257563', 'C04M7T', 'T5377S', 'S46'),
  ('F47', '310248030', 'TERA8', 'T5377S', 'S47'),
  ('F48', '310345837', 'PSC112', 'T5377S', 'S48'),
  ('F49', '310356986', 'PSC118', 'T5377S', 'S49'),
  ('F50', '310291521', 'TERA62', 'T5377S', 'S50'),
  ('F51', '310245315', 'TERA6', 'T5377S', 'S51'),
  ('F52', '310358761', 'REX3', 'T5377S', 'S52'),
  ('F53', '310337692', 'PSC104', 'T5377S', 'S53'),
  ('F54', '310369249', 'PSC131', 'T5377S', 'S54'),
  ('F55', '310299788', 'TERA93', 'T5377S', 'S55'),
  ('F56', '310298066', 'TRA85', 'T5377S', 'S56'),
  ('F59', '310355334', 'PMOST28', 'T5377S', 'S59'),
  ('F60', '310370166', 'REX20', 'T5377S', 'S60'),
  ('F61', '310301512', 'TERA98', 'T5377S', 'S61'),
  ('F62', '310370599', 'REX21', 'T5377S', 'S62'),
  ('HQ01', '311978225', 'CMI1', 'T5833', 'HQ01'),
  ('HQ02', '311986552', 'CMI2', 'T5833', 'HQ02'),
  ('HQ03', '311986555', 'CMI3', 'T5833', 'HQ03'),
  ('HQ04', '311991295', 'CMI4', 'T5833', 'HQ04'),
  ('HQ05', '311995673', 'CMI5', 'T5833', 'HQ05'),
  ('HQ06', '310752021', 'TERA1', 'T5833', 'HQ06'),
  ('HQ09', '312076058', 'CMI8', 'T5833', 'HQ09'),
  ('HQ10', '312080942', 'CMI9', 'T5833', 'HQ10'),
  ('HQ11', '312080946', 'CMI10', 'T5833', 'HQ11')
) as s(machine_code, machine_serial, machine_name, model, source_machine_number)
where m.machine_code = s.machine_code or m.source_machine_number = s.source_machine_number;

insert into public.repair_machines (machine_code, tester_id, model, source_machine_number, machine_serial, machine_name)
values
  ('R5', '310108452', 'PMOS2', 'T5377', 'R05'),
  ('R7', '310178961', 'SMIC2', 'T5377', 'R07'),
  ('R9', '310352914', 'INF29', 'T5377', 'R09'),
  ('F14', '562100462', 'YURA33', 'T5377S', 'S14'),
  ('F19', '310379891', 'TAS05', 'T5377S', 'S19'),
  ('F20', '310294599', 'TERA76', 'T5377S', 'S20'),
  ('F21', '310263797', 'TERA43', 'T5377S', 'S21'),
  ('F22', '310334454', 'C05M7T', 'T5377S', 'S22'),
  ('F28', '310262653', 'TERA36', 'T5377S', 'S28'),
  ('F36', '310249705', 'TERA13', 'T5377S', 'S36'),
  ('F39', '310370600', 'REX22', 'T5377S', 'S39'),
  ('F40', '310373783', 'REX28', 'T5377S', 'S40'),
  ('F41', '310369292', 'PSC132', 'T5377S', 'S41'),
  ('F42', '310368425', 'PMOST32', 'T5377S', 'S42'),
  ('F45', '310280213', 'PMOST11', 'T5377S', 'S45'),
  ('F46', '310257563', 'C04M7T', 'T5377S', 'S46'),
  ('F47', '310248030', 'TERA8', 'T5377S', 'S47'),
  ('F48', '310345837', 'PSC112', 'T5377S', 'S48'),
  ('F49', '310356986', 'PSC118', 'T5377S', 'S49'),
  ('F50', '310291521', 'TERA62', 'T5377S', 'S50'),
  ('F51', '310245315', 'TERA6', 'T5377S', 'S51'),
  ('F52', '310358761', 'REX3', 'T5377S', 'S52'),
  ('F53', '310337692', 'PSC104', 'T5377S', 'S53'),
  ('F54', '310369249', 'PSC131', 'T5377S', 'S54'),
  ('F55', '310299788', 'TERA93', 'T5377S', 'S55'),
  ('F56', '310298066', 'TRA85', 'T5377S', 'S56'),
  ('F59', '310355334', 'PMOST28', 'T5377S', 'S59'),
  ('F60', '310370166', 'REX20', 'T5377S', 'S60'),
  ('F61', '310301512', 'TERA98', 'T5377S', 'S61'),
  ('F62', '310370599', 'REX21', 'T5377S', 'S62'),
  ('HQ01', '311978225', 'CMI1', 'T5833', 'HQ01'),
  ('HQ02', '311986552', 'CMI2', 'T5833', 'HQ02'),
  ('HQ03', '311986555', 'CMI3', 'T5833', 'HQ03'),
  ('HQ04', '311991295', 'CMI4', 'T5833', 'HQ04'),
  ('HQ05', '311995673', 'CMI5', 'T5833', 'HQ05'),
  ('HQ06', '310752021', 'TERA1', 'T5833', 'HQ06'),
  ('HQ09', '312076058', 'CMI8', 'T5833', 'HQ09'),
  ('HQ10', '312080942', 'CMI9', 'T5833', 'HQ10'),
  ('HQ11', '312080946', 'CMI10', 'T5833', 'HQ11')
on conflict (machine_code, tester_id) do update set
  model = excluded.model,
  source_machine_number = excluded.source_machine_number,
  machine_serial = excluded.machine_serial,
  machine_name = excluded.machine_name;

commit;
