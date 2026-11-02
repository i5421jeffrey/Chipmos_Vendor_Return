CREATE TABLE legacy_import_batches (
    id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, source_description TEXT NOT NULL
);
CREATE TABLE legacy_source_files (
    batch_id TEXT NOT NULL REFERENCES legacy_import_batches(id),
    filename TEXT NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL,
    PRIMARY KEY(batch_id, filename)
);
CREATE TABLE legacy_source_rows (
    source_table TEXT NOT NULL, source_key TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES legacy_import_batches(id),
    original_json TEXT NOT NULL CHECK(json_valid(original_json)),
    warnings TEXT NOT NULL CHECK(json_valid(warnings)),
    PRIMARY KEY(source_table, source_key)
);
CREATE TABLE legacy_dbn_records (
    id TEXT PRIMARY KEY, serial_no TEXT NOT NULL REFERENCES serial_board_mappings(serial_no),
    machine_code TEXT NOT NULL, model TEXT NOT NULL, board_name TEXT NOT NULL,
    board_part_code TEXT NOT NULL, customer_code TEXT NOT NULL REFERENCES dbn_customers(customer_code),
    product_code TEXT, station_code TEXT, issue_type TEXT,
    dut TEXT, issue_description TEXT, socket_file_id TEXT,
    dut_pin_snapshot TEXT NOT NULL CHECK(json_valid(dut_pin_snapshot)),
    version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(customer_code, product_code, station_code)
      REFERENCES dbn_valid_combinations(customer_code, product_code, station_code)
);
CREATE VIEW all_dbn_records AS
    SELECT *, 0 AS legacy_incomplete FROM dbn_records
    UNION ALL SELECT *, 1 AS legacy_incomplete FROM legacy_dbn_records;
