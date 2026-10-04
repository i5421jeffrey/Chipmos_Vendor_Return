-- Refresh the repair board-name / part-number mapping from
-- Downloads/機台Model板件關係範本.xlsx (2026-10-04).
-- Run in Supabase SQL Editor after the original repair_board_mapping_migration.sql.
-- Board Part Number is not unique: Model + board name identifies a mapping.
begin;

-- Replace the previous Model + Part Number key, which prevented repeated or
-- placeholder Part Numbers from being stored for different board names.
alter table public.repair_model_boards
  drop constraint if exists repair_model_boards_pkey;
alter table public.repair_model_boards
  drop constraint if exists repair_model_boards_model_board_name_key;
alter table public.repair_model_boards
  add constraint repair_model_boards_pkey primary key (model, board_name);

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
  ('T5377', 'Main AC', '-')
on conflict (model, board_name) do update
set board_part_code = excluded.board_part_code;

commit;
