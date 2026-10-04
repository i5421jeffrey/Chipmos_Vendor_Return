-- Repair-create selectors based on Downloads/機台Model板件關係範本.xlsx.
-- This migration adds read-only reference data and enforces machine/model/board compatibility for new web repairs.
-- Run once in Supabase Dashboard > SQL Editor before deploying the matching page update.
begin;

create table if not exists public.repair_models (
  model text primary key check (model = trim(model) and model <> '')
);

create table if not exists public.repair_machine_models (
  machine_code text primary key check (machine_code = trim(machine_code) and machine_code <> ''),
  model text not null references public.repair_models(model) on update cascade on delete restrict
);

create table if not exists public.repair_model_boards (
  model text not null references public.repair_models(model) on update cascade on delete restrict,
  board_name text not null check (board_name = trim(board_name) and board_name <> ''),
  board_part_code text not null check (board_part_code = trim(board_part_code) and board_part_code <> ''),
  primary key (model, board_part_code),
  unique (model, board_name)
);

insert into public.repair_models (model) values
  ('T5377'), ('T5377S')
on conflict (model) do nothing;

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
on conflict (machine_code) do nothing;

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
  ('T5377S', 'DC', 'BGR-026902')
on conflict do nothing;

create index if not exists repair_model_boards_lookup_idx
  on public.repair_model_boards (model, board_name);

alter table public.repair_models enable row level security;
alter table public.repair_machine_models enable row level security;
alter table public.repair_model_boards enable row level security;

grant usage on schema public to anon, authenticated;
grant select on public.repair_models, public.repair_machine_models, public.repair_model_boards to anon, authenticated;

drop policy if exists "Public can read repair models" on public.repair_models;
create policy "Public can read repair models" on public.repair_models
  for select to anon, authenticated using (true);
drop policy if exists "Public can read repair machine models" on public.repair_machine_models;
create policy "Public can read repair machine models" on public.repair_machine_models
  for select to anon, authenticated using (true);
drop policy if exists "Public can read repair model boards" on public.repair_model_boards;
create policy "Public can read repair model boards" on public.repair_model_boards
  for select to anon, authenticated using (true);

create or replace function public.validate_new_web_repair_machine_board()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  v_model text;
begin
  if new.source_system = 'web' and new.retry_of_record_id is null then
    select model into v_model
    from public.repair_machine_models
    where machine_code = new.machine_code;
    if not found then
      raise exception '機台編號不在有效清單中';
    end if;
    if new.model is distinct from v_model then
      raise exception '機台編號與 Model 對應不正確';
    end if;
    if not exists (
      select 1 from public.repair_model_boards
      where model = v_model
        and board_name = new.description
        and board_part_code = new.board_part_code
    ) then
      raise exception '板件名稱或 Board Part Number 不屬於此 Model';
    end if;
    new.current_status := '待送修';
    new.order_status := '';
    new.is_opened := false;
    new.repair_month := '';
    new.item := '';
    new.area := '';
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_validate_new_machine_board on public.repair_records;
create trigger repair_records_validate_new_machine_board
before insert on public.repair_records
for each row execute function public.validate_new_web_repair_machine_board();

commit;
