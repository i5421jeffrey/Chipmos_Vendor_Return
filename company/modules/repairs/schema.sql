CREATE TABLE repair_machine_models (
    machine_code TEXT PRIMARY KEY,
    model TEXT NOT NULL
);
CREATE TABLE repair_model_boards (
    model TEXT NOT NULL,
    board_name TEXT NOT NULL,
    board_part_code TEXT NOT NULL,
    PRIMARY KEY (model, board_name)
);
CREATE TABLE repair_board_prices (
    model TEXT NOT NULL,
    board_name TEXT NOT NULL,
    board_part_code TEXT NOT NULL,
    board_repair_cents INTEGER CHECK (board_repair_cents >= 0),
    external_repair_cents INTEGER CHECK (external_repair_cents >= 0),
    contract_repair_cents INTEGER CHECK (contract_repair_cents >= 0),
    warranty_repair_cents INTEGER CHECK (warranty_repair_cents = 0),
    PRIMARY KEY (model, board_name, board_part_code)
);
CREATE TABLE serial_board_mappings (
    serial_no TEXT PRIMARY KEY,
    board_name TEXT NOT NULL,
    board_part_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE repair_records (
    id TEXT PRIMARY KEY,
    serial_no TEXT NOT NULL REFERENCES serial_board_mappings(serial_no),
    machine_code TEXT NOT NULL,
    model TEXT NOT NULL,
    description TEXT NOT NULL,
    board_part_code TEXT NOT NULL,
    failure_tag TEXT NOT NULL,
    failure_description TEXT NOT NULL CHECK (length(trim(failure_description)) > 0),
    repair_type TEXT NOT NULL CHECK (repair_type IN ('板修', '外修', '合約', '保固')),
    repair_amount_cents INTEGER CHECK (repair_amount_cents >= 0),
    current_status TEXT NOT NULL CHECK (current_status IN ('待送修', '已送修', '取回驗證', '結案（PASS）', '結案（FAIL）')),
    is_opened INTEGER NOT NULL CHECK (is_opened IN (0, 1)),
    occurred_on TEXT NOT NULL,
    sent_on TEXT,
    returned_on TEXT,
    closed_on TEXT,
    retry_of_record_id TEXT REFERENCES repair_records(id),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX repair_records_serial_idx ON repair_records(serial_no);
CREATE INDEX repair_records_status_idx ON repair_records(current_status, occurred_on);
CREATE TABLE record_change_history (
    id TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    record_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    serial_no TEXT,
    board_name TEXT,
    changed_at TEXT NOT NULL,
    changes TEXT NOT NULL CHECK (json_valid(changes))
);
CREATE INDEX record_change_history_time_idx ON record_change_history(changed_at);
