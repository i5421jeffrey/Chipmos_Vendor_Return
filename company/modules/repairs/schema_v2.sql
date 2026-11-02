ALTER TABLE serial_board_mappings ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE dbn_customers (customer_code TEXT PRIMARY KEY);
CREATE TABLE dbn_valid_combinations (
    customer_code TEXT NOT NULL REFERENCES dbn_customers(customer_code),
    product_code TEXT NOT NULL, station_code TEXT NOT NULL,
    PRIMARY KEY (customer_code, product_code, station_code)
);
CREATE TABLE dbn_socket_files (
    id TEXT PRIMARY KEY, product_code TEXT NOT NULL UNIQUE,
    source_filename TEXT NOT NULL, dut_count INTEGER NOT NULL,
    dut_pins TEXT NOT NULL CHECK(json_valid(dut_pins))
);
CREATE TABLE dbn_records (
    id TEXT PRIMARY KEY, serial_no TEXT NOT NULL REFERENCES serial_board_mappings(serial_no),
    machine_code TEXT NOT NULL, model TEXT NOT NULL, board_name TEXT NOT NULL,
    board_part_code TEXT NOT NULL, customer_code TEXT NOT NULL REFERENCES dbn_customers(customer_code),
    product_code TEXT, station_code TEXT,
    issue_type TEXT NOT NULL CHECK(issue_type IN ('Group','Single Dut','RTE','Other')),
    dut TEXT, issue_description TEXT, socket_file_id TEXT,
    dut_pin_snapshot TEXT NOT NULL CHECK(json_valid(dut_pin_snapshot)),
    version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(customer_code, product_code, station_code)
      REFERENCES dbn_valid_combinations(customer_code, product_code, station_code)
);
CREATE INDEX dbn_serial_idx ON dbn_records(serial_no, created_at);
CREATE UNIQUE INDEX repair_retry_unique ON repair_records(retry_of_record_id) WHERE retry_of_record_id IS NOT NULL;
CREATE TABLE repair_attachments (
    id TEXT PRIMARY KEY, repair_record_id TEXT NOT NULL UNIQUE REFERENCES repair_records(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, content BLOB NOT NULL CHECK(length(content) BETWEEN 1 AND 5242880),
    sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
