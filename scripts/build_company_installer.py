"""Generate a self-contained, plain-text installer without zip or dependencies."""
import hashlib
import pprint
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026-11-05-restore-host-135"
FILES = (
    "README.md", "LAN_SETUP.md", "IMPLEMENTATION_STATUS.md", "server.py", "database.py", "errors.py", "maintenance.py", "import_data.py", "edit_access.py", "legacy_import.py",
    "test_server.py", "test_repairs.py", "test_features.py", "test_import_data.py", "test_edit_access.py", "test_legacy_import.py", "test_lan.py",
    "modules/__init__.py", "modules/repairs/__init__.py", "modules/repairs/catalog.json",
    "modules/repairs/schema.sql", "modules/repairs/schema_v2.sql", "modules/repairs/schema_legacy.sql", "modules/repairs/service.py",
    "modules/repairs/operations.py", "modules/repairs/attachments.py", "modules/repairs/dbn_catalog.json",
    "web/index.html", "web/app.js", "web/style.css", "web/repairs.html", "web/repairs.js", "web/repairs.css", "web/features.js",
    "web/original.css", "web/branding.json", "web/parity.css",
)


def build():
    files = {}
    for relative in FILES:
        content = (ROOT / "company" / relative).read_text(encoding="utf-8")
        files["company/" + relative] = {
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    template = (ROOT / "scripts/company_installer_template.py").read_text(encoding="utf-8")
    payload = pprint.pformat({"version": VERSION, "files": files}, sort_dicts=True, width=110)
    return template.replace("BUNDLE = {}  # BUILD_PAYLOAD", "BUNDLE = " + payload, 1)


if __name__ == "__main__":
    target = ROOT / "install_spms.py"
    target.write_bytes(build().encode("utf-8"))
    print(f"Built {target.name}: {target.stat().st_size} bytes, {len(FILES)} program files")
