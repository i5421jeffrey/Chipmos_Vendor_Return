-- Refresh the machine/model and model/board mapping from the supplied workbook.
-- Source: Downloads/機台Model板件關係範本.xlsx (2026-10-05).
-- Idempotent upsert: this script does not delete mappings absent from the workbook.
-- Run in Supabase SQL Editor after repair_board_mapping_migration.sql and
-- serial_board_mapping_migration.sql.
-- Nine-digit numeric S/N values are preserved as entered, regardless of prefix.
begin;

insert into public.repair_models (model) values
  ('T5377'),
  ('T5377S')
on conflict (model) do nothing;

-- Keep the board name as part of the key; Part Numbers may be shared by boards.
alter table public.repair_model_boards
  drop constraint if exists repair_model_boards_pkey;
alter table public.repair_model_boards
  drop constraint if exists repair_model_boards_model_board_name_key;
alter table public.repair_model_boards
  add constraint repair_model_boards_pkey primary key (model, board_name);

insert into public.repair_machine_models (machine_code, model) values
  ('F45', 'T5377S'),
  ('F46', 'T5377S'),
  ('F47', 'T5377S'),
  ('F48', 'T5377S'),
  ('F49', 'T5377S'),
  ('F50', 'T5377S'),
  ('F51', 'T5377S'),
  ('F52', 'T5377S'),
  ('F53', 'T5377S'),
  ('F54', 'T5377S'),
  ('F55', 'T5377S'),
  ('F56', 'T5377S'),
  ('F57', 'T5377S'),
  ('F58', 'T5377S'),
  ('F30', 'T5377S'),
  ('F79', 'T5377S'),
  ('F78', 'T5377S'),
  ('F07', 'T5377S'),
  ('F32', 'T5377S'),
  ('F13', 'T5377S'),
  ('F08', 'T5377S'),
  ('F09', 'T5377S'),
  ('F16', 'T5377S'),
  ('F11', 'T5377S'),
  ('F10', 'T5377S'),
  ('F35', 'T5377S'),
  ('F12', 'T5377S'),
  ('F36', 'T5377S'),
  ('F22', 'T5377S'),
  ('F66', 'T5377S'),
  ('F65', 'T5377S'),
  ('F64', 'T5377S'),
  ('F63', 'T5377S'),
  ('F67', 'T5377S'),
  ('F68', 'T5377S'),
  ('F31', 'T5377S'),
  ('F23', 'T5377S'),
  ('F38', 'T5377S'),
  ('F44', 'T5377S'),
  ('F24', 'T5377S'),
  ('F15', 'T5377S'),
  ('F26', 'T5377S'),
  ('F70', 'T5377S'),
  ('F69', 'T5377S'),
  ('F33', 'T5377S'),
  ('F25', 'T5377S'),
  ('F29', 'T5377S'),
  ('F37', 'T5377S'),
  ('F72', 'T5377S'),
  ('F71', 'T5377S'),
  ('F77', 'T5377S'),
  ('F76', 'T5377S'),
  ('F75', 'T5377S'),
  ('F74', 'T5377S'),
  ('F73', 'T5377S'),
  ('F18', 'T5377S'),
  ('F17', 'T5377S'),
  ('F34', 'T5377S'),
  ('F06', 'T5377S'),
  ('F27', 'T5377S'),
  ('R02', 'T5377'),
  ('R03', 'T5377'),
  ('R21', 'T5377'),
  ('F19', 'T5377S'),
  ('F42', 'T5377S'),
  ('F41', 'T5377S'),
  ('F14', 'T5377S'),
  ('F62', 'T5377S'),
  ('F40', 'T5377S'),
  ('F39', 'T5377S'),
  ('F59', 'T5377S'),
  ('F60', 'T5377S'),
  ('F61', 'T5377S'),
  ('F20', 'T5377S'),
  ('F28', 'T5377S'),
  ('F21', 'T5377S'),
  ('R05', 'T5377'),
  ('R07', 'T5377'),
  ('R09', 'T5377')
on conflict (machine_code) do update
set model = excluded.model;

insert into public.repair_model_boards (model, board_name, board_part_code) values
  ('T5377', 'CAL SIG', 'BGR-026746X02'),
  ('T5377', 'DR PE', 'BIR-026805'),
  ('T5377', 'PDS', 'BIR-026380'),
  ('T5377', 'DPU I/F', 'BGR-026901'),
  ('T5377', 'I/O PE', 'BIR-030083'),
  ('T5377', 'FMRA', 'BGR-030182X02'),
  ('T5377', 'PPS', 'BIR-026903'),
  ('T5377', 'DC', 'BGR-026902'),
  ('T5377', 'TP6B CPU', 'WBL-H3610207CPU'),
  ('T5377', 'FAIL MUX', 'BGR-026384X02'),
  ('T5377', 'FM CONT', 'BGR-030181'),
  ('T5377', 'PM', 'BIR-026383'),
  ('T5377', 'ALPG', 'BIR-030349'),
  ('T5377', 'TH IF', 'BGR-026378X04'),
  ('T5377', 'PS MONITOR', 'BGR-026815X02'),
  ('T5377S', 'HVDR PE', 'BPR-030837'),
  ('T5377S', 'FAIL MUX', 'BGR-026384X02'),
  ('T5377S', 'FM CONT X02', 'BGR-030181X02'),
  ('T5377S', 'PM', 'BIR-026383'),
  ('T5377S', 'ALPG', 'BIR-030349'),
  ('T5377S', 'PDS', 'BIR-026380'),
  ('T5377S', 'FMRA', 'BGR-030182X02'),
  ('T5377S', 'TH IF', 'BGR-026378X04'),
  ('T5377S', 'TP6B CPU', 'WBL-H3610207CPU'),
  ('T5377S', 'PPS', 'BIR-026903'),
  ('T5377S', 'CAL SIG', 'BGR-026746X02'),
  ('T5377S', 'I/O PE', 'BIR-030083'),
  ('T5377S', 'SYSTEM MONITOR', 'BGR-031566'),
  ('T5377S', 'PS MONITOR', 'BGR-031487'),
  ('T5377S', 'DC', 'BGR-026902'),
  ('T5377S', '2G MODULE', 'BGD-030184X02'),
  ('T5377', '1G MODULE', 'BGD-030184'),
  ('T5377S', 'BLADE1500', '-'),
  ('T5377', 'BLADE1500', '-'),
  ('T5377S', 'BLADE150', '-'),
  ('T5377', 'BLADE150', '-'),
  ('T5377S', 'Main AC', '-'),
  ('T5377', 'Main AC', 'WBL_H371329X06CONT'),
  ('T5377S', 'Mother Board X04', 'H7-0760X04'),
  ('T5377S', 'Mother Board X05', 'H7-0760X05'),
  ('T5377S', 'Mother Board X06', 'H7-0760X06'),
  ('T5377S', 'Mother Board X07', 'H7-0760X07'),
  ('T5377', 'Mother Board X04', 'H7-0760X04'),
  ('T5377', 'Mother Board X05', 'H7-0760X05'),
  ('T5377', 'Mother Board X06', 'H7-0760X06'),
  ('T5377', 'Mother Board X07', 'H7-0760X07')
on conflict (model, board_name) do update
set board_part_code = excluded.board_part_code;

-- Keep the database normalizer in sync with the page: arbitrary 9-digit S/Ns
-- (for example 400322395) stay unchanged; shorter numeric S/Ns are zero-padded.
create or replace function public.normalize_board_serial(p_serial text)
returns text
language sql
immutable
strict
set search_path = ''
as $$
  select case
    when btrim(p_serial) ~ '^[0-9]{9}$' then btrim(p_serial)
    when btrim(p_serial) ~ '^[0-9]{1,8}$' then lpad(btrim(p_serial), 9, '0')
    else upper(btrim(p_serial))
  end
$$;

commit;
