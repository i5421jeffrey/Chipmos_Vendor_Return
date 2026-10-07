-- User-confirmed Part Number for 2G Module: BGD-030184.
-- Run this before rerunning serial_board_mapping_catalog_migration.sql.
-- Keep the legacy board-name spelling so existing S/N mappings can be resolved
-- without renaming records or changing repair / DBN history.
begin;

update public.repair_model_boards
set board_part_code = 'BGD-030184'
where upper(btrim(board_name)) = '2G MODULE';

insert into public.repair_model_boards (model, board_name, board_part_code)
values ('T5377S', '2G Module', 'BGD-030184')
on conflict (model, board_name) do update
set board_part_code = excluded.board_part_code;

notify pgrst, 'reload schema';
commit;
