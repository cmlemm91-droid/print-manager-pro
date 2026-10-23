"""Datenbank-Zugriff, Schema-Migrationen und Einstellungen."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PRINT_MANAGER_DB", str(BASE_DIR / "print_manager.db")))
BACKUP_DIR = BASE_DIR / "backups"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"

DEFAULT_SETTINGS = {
    "company_name": "Mein 3D-Druck Service",
    "company_owner": "",
    "company_street": "Musterstraße 1",
    "company_zip": "12345",
    "company_city": "Musterstadt",
    "company_email": "info@example.com",
    "company_phone": "+49 123 456789",
    "company_web": "",
    "tax_id": "",
    "vat_id": "",
    "iban": "DE00 0000 0000 0000 0000 00",
    "bic": "ABCDEFF1XXX",
    "bank_name": "",
    "cad_hourly_rate": "20.0",
    "margin_percent": "30",
    "electricity_price": "0.35",
    "vat_rate": "19",
    "small_business": "0",
    "order_prefix": "AU",
    "invoice_prefix": "RE",
    "payment_days": "14",
    "invoice_note": "Vielen Dank für Ihren Auftrag!",
}

SCHEMA = {
    "customers": """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            company TEXT,
            email TEXT,
            phone TEXT,
            street TEXT,
            house_number TEXT,
            zip TEXT,
            city TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
    "inventory": """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material TEXT NOT NULL,
            color TEXT NOT NULL,
            weight REAL DEFAULT 0,
            price_per_kg REAL DEFAULT 0,
            min_weight REAL DEFAULT 200,
            supplier TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
    "printers": """
        CREATE TABLE IF NOT EXISTS printers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cost_per_hour REAL DEFAULT 0,
            power_watt REAL DEFAULT 150,
            purchase_price REAL DEFAULT 0,
            notes TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
    "orders": """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT,
            customer_id INTEGER,
            material_id INTEGER,
            printer_id INTEGER,
            model TEXT,
            quantity INTEGER DEFAULT 1,
            weight_used REAL DEFAULT 0,
            duration_hours REAL DEFAULT 0,
            cad_hours REAL DEFAULT 0,
            material_price_kg REAL DEFAULT 0,
            printer_cost_hour REAL DEFAULT 0,
            printer_power_watt REAL DEFAULT 0,
            cad_rate REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            machine_cost REAL DEFAULT 0,
            cad_cost REAL DEFAULT 0,
            energy_cost REAL DEFAULT 0,
            extra_cost REAL DEFAULT 0,
            extra_label TEXT DEFAULT 'Sonstiges',
            cost_total REAL DEFAULT 0,
            margin_percent REAL DEFAULT 30,
            price REAL DEFAULT 0,
            price_override INTEGER DEFAULT 0,
            status TEXT DEFAULT 'angebot',
            priority TEXT DEFAULT 'normal',
            due_date TEXT,
            notes TEXT,
            paid INTEGER DEFAULT 0,
            paid_at TEXT,
            invoice_number TEXT,
            invoiced_at TEXT,
            stock_deducted INTEGER DEFAULT 0,
            started_at TEXT,
            completed_at TEXT,
            delivered_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
        )""",
    "stock_movements": """
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER,
            change_g REAL,
            reason TEXT,
            order_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
    "settings": """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
}

MIGRATIONS = {
    "customers": [
        ("company", "TEXT"),
        ("phone", "TEXT"),
        ("notes", "TEXT"),
        ("created_at", "TEXT DEFAULT (datetime('now','localtime'))"),
    ],
    "inventory": [
        ("min_weight", "REAL DEFAULT 200"),
        ("supplier", "TEXT"),
        ("notes", "TEXT"),
        ("created_at", "TEXT DEFAULT (datetime('now','localtime'))"),
    ],
    "printers": [
        ("power_watt", "REAL DEFAULT 150"),
        ("purchase_price", "REAL DEFAULT 0"),
        ("notes", "TEXT"),
        ("active", "INTEGER DEFAULT 1"),
        ("created_at", "TEXT DEFAULT (datetime('now','localtime'))"),
    ],
    "orders": [
        ("order_number", "TEXT"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("material_price_kg", "REAL DEFAULT 0"),
        ("printer_cost_hour", "REAL DEFAULT 0"),
        ("printer_power_watt", "REAL DEFAULT 0"),
        ("cad_rate", "REAL DEFAULT 0"),
        ("material_cost", "REAL DEFAULT 0"),
        ("machine_cost", "REAL DEFAULT 0"),
        ("cad_cost", "REAL DEFAULT 0"),
        ("energy_cost", "REAL DEFAULT 0"),
        ("extra_cost", "REAL DEFAULT 0"),
        ("extra_label", "TEXT DEFAULT 'Sonstiges'"),
        ("cost_total", "REAL DEFAULT 0"),
        ("margin_percent", "REAL DEFAULT 30"),
        ("price_override", "INTEGER DEFAULT 0"),
        ("priority", "TEXT DEFAULT 'normal'"),
        ("due_date", "TEXT"),
        ("notes", "TEXT"),
        ("paid", "INTEGER DEFAULT 0"),
        ("paid_at", "TEXT"),
        ("invoice_number", "TEXT"),
        ("invoiced_at", "TEXT"),
        ("stock_deducted", "INTEGER DEFAULT 0"),
        ("started_at", "TEXT"),
        ("completed_at", "TEXT"),
        ("delivered_at", "TEXT"),
        ("updated_at", "TEXT"),
    ],
    "stock_movements": [],
    "settings": [],
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str):
    return [row["name"] for row in conn.execute("PRAGMA table_info(%s)" % table)]


def _backfill_order_numbers(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM orders WHERE order_number IS NULL OR order_number = '' ORDER BY id"
    ).fetchall()
    if not rows:
        return
    from services import next_number  # späte Importe vermeiden Zyklen

    year = datetime.now().year
    prefix = load_settings(conn).get("order_prefix", "AU").upper()
    seq = next_number(conn, prefix, year, "order_number", "orders")
    for row in rows:
        conn.execute(
            "UPDATE orders SET order_number = ? WHERE id = ?",
            (f"{prefix}-{year}-{seq:04d}", row["id"]),
        )
        seq += 1


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        for statement in SCHEMA.values():
            conn.execute(statement)

        for table, columns in MIGRATIONS.items():
            existing = _columns(conn, table)
            for name, definition in columns:
                if name not in existing:
                    conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, definition))

        # Alte Statuswerte übernehmen.
        conn.execute("UPDATE orders SET status = 'angebot' WHERE status = 'offen'")

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_inventory ON stock_movements(inventory_id)")
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_number ON orders(order_number)"
            )
        except sqlite3.IntegrityError:
            # Bei alten doppelten Nummern bleibt der Index einfach weg.
            conn.rollback()

        _backfill_order_numbers(conn)
        conn.commit()
        backup_daily(conn)
    finally:
        conn.close()


def backup_daily(conn: sqlite3.Connection) -> None:
    """Einmal pro Tag eine Sicherung anlegen, maximal 30 Stück behalten."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target = BACKUP_DIR / ("print_manager_%s.db" % datetime.now().strftime("%Y-%m-%d"))
        if target.exists():
            return
        with sqlite3.connect(str(target)) as destination:
            conn.backup(destination)
        files = sorted(BACKUP_DIR.glob("print_manager_????-??-??.db"), reverse=True)
        for old in files[30:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception as exc:  # Backup darf den Start nie verhindern
        print("Backup konnte nicht erstellt werden:", exc)


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = BACKUP_DIR / ("print_manager_%s.db" % stamp)
    conn = connect()
    try:
        with sqlite3.connect(str(target)) as destination:
            conn.backup(destination)
    finally:
        conn.close()
    return target


def load_settings(conn: sqlite3.Connection) -> dict:
    values = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"] if row["value"] is not None else ""
    return values


def save_settings(conn: sqlite3.Connection, values: dict) -> None:
    for key, value in values.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
    conn.commit()


def setting_number(settings: dict, key: str, fallback: float = 0.0) -> float:
    try:
        return float(str(settings.get(key, fallback)).replace(",", "."))
    except (TypeError, ValueError):
        return fallback
