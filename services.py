"""Geschäftslogik: Kalkulation, Lagerbuchungen, Nummernkreise."""
from __future__ import annotations

from datetime import datetime

from utils import (
    DONE_STATUSES,
    PRODUCTION_STATUSES,
    is_production,
    now_str,
    num,
    round_money,
)


# ---------------------------------------------------------------- Kalkulation
def calculate(data: dict, settings: dict) -> dict:
    """Berechnet Kosten und Verkaufspreis (netto) eines Auftrags."""
    material_price = num(data.get("material_price_kg"))
    printer_cost = num(data.get("printer_cost_hour"))
    power_watt = num(data.get("printer_power_watt"), 150.0)
    cad_rate = num(data.get("cad_rate"), num(settings.get("cad_hourly_rate"), 0))
    electricity = num(settings.get("electricity_price"), 0.35)

    weight = max(0.0, num(data.get("weight_used")))
    duration = max(0.0, num(data.get("duration_hours")))
    cad_hours = max(0.0, num(data.get("cad_hours")))
    extra = max(0.0, num(data.get("extra_cost")))

    material_cost = round_money((weight / 1000.0) * material_price)
    machine_cost = round_money(duration * printer_cost)
    cad_cost = round_money(cad_hours * cad_rate)
    energy_cost = round_money(duration * (power_watt / 1000.0) * electricity)
    cost_total = round_money(material_cost + machine_cost + cad_cost + energy_cost + extra)

    margin = num(data.get("margin_percent"), num(settings.get("margin_percent"), 30))
    override = 1 if num(data.get("price_override")) else 0
    price = round_money(num(data.get("price")))
    if not override:
        price = round_money(cost_total * (1 + margin / 100.0))
    price = max(0.0, price)

    profit = round_money(price - cost_total)
    effective_margin = round((profit / price) * 100, 1) if price > 0 else 0.0

    return {
        "material_cost": material_cost,
        "machine_cost": machine_cost,
        "cad_cost": cad_cost,
        "energy_cost": energy_cost,
        "extra_cost": extra,
        "cost_total": cost_total,
        "price": price,
        "price_override": override,
        "margin_percent": margin,
        "profit": profit,
        "effective_margin": effective_margin,
    }


def totals(price, settings: dict) -> dict:
    small_business = str(settings.get("small_business", "0")).lower() in ("1", "true", "on", "yes")
    vat_rate = 0.0 if small_business else num(settings.get("vat_rate"), 19.0)
    net = round_money(price)
    vat = round_money(net * vat_rate / 100.0)
    return {
        "net": net,
        "vat": vat,
        "vat_rate": vat_rate,
        "small_business": small_business,
        "gross": round_money(net + vat),
        "profit": 0.0,
    }


# ------------------------------------------------------------------- Nummern
def _sequences(conn, column: str, table: str, pattern: str):
    rows = conn.execute(
        "SELECT %s AS n FROM %s WHERE %s LIKE ?" % (column, table, column), (pattern,)
    ).fetchall()
    for row in rows:
        value = str(row["n"] or "")
        try:
            yield int(value.rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            continue


def _counter_key(kind: str, prefix: str, year: int) -> str:
    return "seq_%s_%s_%s" % (kind, prefix.upper(), year)


def _stored_counter(conn, kind: str, prefix: str, year: int) -> int:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (_counter_key(kind, prefix, year),)
    ).fetchone()
    try:
        return int(float(row["value"])) if row else 0
    except (TypeError, ValueError):
        return 0


def next_number(conn, prefix: str, year: int, column: str, table: str, kind: str | None = None) -> int:
    """Nächste freie Nummer. Mit ``kind`` wird sie dauerhaft fortgeschrieben,
    damit gelöschte Aufträge/Rechnungen ihre Nummer nicht erneut vergeben."""
    pattern = "%s-%s-%%" % (prefix, year)
    used = list(_sequences(conn, column, table, pattern))
    derived = (max(used) + 1) if used else 1
    if not kind:
        return derived
    sequence = max(derived, _stored_counter(conn, kind, prefix, year) + 1)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_counter_key(kind, prefix, year), str(sequence)),
    )
    return sequence


def next_order_number(conn) -> str:
    from database import load_settings

    settings = load_settings(conn)
    prefix = (settings.get("order_prefix") or "AU").upper()
    year = datetime.now().year
    seq = next_number(conn, prefix, year, "order_number", "orders", kind="order")
    return "%s-%s-%04d" % (prefix, year, seq)


def next_invoice_number(conn) -> str:
    from database import load_settings

    settings = load_settings(conn)
    prefix = (settings.get("invoice_prefix") or "RE").upper()
    year = datetime.now().year
    seq = next_number(conn, prefix, year, "invoice_number", "orders", kind="invoice")
    return "%s-%s-%04d" % (prefix, year, seq)


def ensure_invoice_number(conn, order) -> str:
    if order["invoice_number"]:
        return order["invoice_number"]
    number = next_invoice_number(conn)
    conn.execute(
        "UPDATE orders SET invoice_number = ?, invoiced_at = ? WHERE id = ?",
        (number, now_str(), order["id"]),
    )
    conn.commit()
    return number


# --------------------------------------------------------------------- Lager
def log_movement(conn, material_id, change, reason, order_id=None):
    conn.execute(
        "INSERT INTO stock_movements (inventory_id, change_g, reason, order_id) VALUES (?, ?, ?, ?)",
        (material_id, change, reason, order_id),
    )


def deduct_stock(conn, material_id, grams, reason, order_id=None):
    grams = float(grams or 0)
    if not material_id or grams <= 0:
        return
    conn.execute("UPDATE inventory SET weight = weight - ? WHERE id = ?", (grams, material_id))
    log_movement(conn, material_id, -grams, reason, order_id)


def restore_stock(conn, material_id, grams, reason, order_id=None):
    grams = float(grams or 0)
    if not material_id or grams <= 0:
        return
    conn.execute("UPDATE inventory SET weight = weight + ? WHERE id = ?", (grams, material_id))
    log_movement(conn, material_id, grams, reason, order_id)


# ------------------------------------------------------------- Statuswechsel
def set_status(conn, order, new_status: str) -> None:
    order_id = order["id"]
    deducted = int(order["stock_deducted"] or 0)
    producing = is_production(new_status)
    stock_flag = deducted

    if producing and not deducted:
        deduct_stock(
            conn, order["material_id"], order["weight_used"],
            "Druck gestartet – %s" % (order["order_number"] or ("Auftrag #%s" % order_id)),
            order_id,
        )
        stock_flag = 1
    elif not producing and deducted:
        restore_stock(
            conn, order["material_id"], order["weight_used"],
            "Storniert – %s" % (order["order_number"] or ("Auftrag #%s" % order_id)),
            order_id,
        )
        stock_flag = 0

    started = order["started_at"]
    completed = order["completed_at"]
    delivered = order["delivered_at"]
    now = now_str()

    if new_status == "druck":
        started = started or now
        completed = None
        delivered = None
    elif new_status == "fertig":
        started = started or now
        completed = now
        delivered = None
    elif new_status == "geliefert":
        started = started or now
        completed = completed or now
        delivered = now
    elif new_status in ("angebot", "bestaetigt"):
        started = None
        completed = None
        delivered = None

    conn.execute(
        """UPDATE orders SET status = ?, stock_deducted = ?, started_at = ?,
           completed_at = ?, delivered_at = ?, updated_at = ? WHERE id = ?""",
        (new_status, stock_flag, started, completed, delivered, now, order_id),
    )
    conn.commit()


def create_order(conn, payload: dict) -> int:
    payload["order_number"] = next_order_number(conn)
    payload["created_at"] = now_str()
    payload["updated_at"] = payload["created_at"]
    payload["stock_deducted"] = 0

    columns = ", ".join(payload.keys())
    placeholders = ", ".join(["?"] * len(payload))
    conn.execute(
        "INSERT INTO orders (%s) VALUES (%s)" % (columns, placeholders),
        tuple(payload.values()),
    )
    order_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    if is_production(payload.get("status")):
        deduct_stock(
            conn, payload.get("material_id"), payload.get("weight_used"),
            "Druck gestartet – %s" % payload["order_number"], order_id,
        )
        conn.execute("UPDATE orders SET stock_deducted = 1 WHERE id = ?", (order_id,))
    conn.commit()
    return order_id


def update_order(conn, order, payload: dict) -> None:
    order_id = order["id"]
    if int(order["stock_deducted"] or 0):
        restore_stock(
            conn, order["material_id"], order["weight_used"],
            "Auftrag bearbeitet – %s" % (order["order_number"] or ("#%s" % order_id)),
            order_id,
        )

    data = dict(payload)
    data["stock_deducted"] = 0
    data["updated_at"] = now_str()

    # Status-Zeitstempel beim Bearbeiten nicht zurücksetzen.
    assignments = ", ".join("%s = ?" % key for key in data.keys())
    conn.execute(
        "UPDATE orders SET %s WHERE id = ?" % assignments,
        tuple(data.values()) + (order_id,),
    )

    if is_production(data.get("status")):
        deduct_stock(
            conn, data.get("material_id"), data.get("weight_used"),
            "Auftrag bearbeitet – %s" % (order["order_number"] or ("#%s" % order_id)),
            order_id,
        )
        conn.execute("UPDATE orders SET stock_deducted = 1 WHERE id = ?", (order_id,))
    conn.commit()


def delete_order(conn, order) -> None:
    if int(order["stock_deducted"] or 0):
        restore_stock(
            conn, order["material_id"], order["weight_used"],
            "Auftrag gelöscht – %s" % (order["order_number"] or ("#%s" % order["id"])),
            order["id"],
        )
    conn.execute("DELETE FROM orders WHERE id = ?", (order["id"],))
    conn.commit()


def toggle_paid(conn, order) -> bool:
    paid = 0 if int(order["paid"] or 0) else 1
    conn.execute(
        "UPDATE orders SET paid = ?, paid_at = ?, updated_at = ? WHERE id = ?",
        (paid, now_str() if paid else None, now_str(), order["id"]),
    )
    conn.commit()
    return bool(paid)


# ---------------------------------------------------------------- Auswertung
def order_totals(order, settings: dict) -> dict:
    data = totals(order["price"], settings)
    data["profit"] = round_money(float(order["price"] or 0) - float(order["cost_total"] or 0))
    return data


def dashboard_stats(conn, settings: dict) -> dict:
    from utils import today_str

    today = today_str()
    month = datetime.now().strftime("%Y-%m")
    year = datetime.now().strftime("%Y")

    def scalar(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    revenue_month = scalar(
        """SELECT COALESCE(SUM(price), 0) FROM orders
           WHERE status IN ('fertig', 'geliefert')
             AND strftime('%Y-%m', COALESCE(completed_at, created_at)) = ?""",
        (month,),
    )
    profit_month = scalar(
        """SELECT COALESCE(SUM(price - cost_total), 0) FROM orders
           WHERE status IN ('fertig', 'geliefert')
             AND strftime('%Y-%m', COALESCE(completed_at, created_at)) = ?""",
        (month,),
    )
    revenue_year = scalar(
        """SELECT COALESCE(SUM(price), 0) FROM orders
           WHERE status IN ('fertig', 'geliefert')
             AND strftime('%Y', COALESCE(completed_at, created_at)) = ?""",
        (year,),
    )
    open_count = scalar(
        "SELECT COUNT(*) FROM orders WHERE status IN ('angebot', 'bestaetigt', 'druck')"
    )
    printing_count = scalar("SELECT COUNT(*) FROM orders WHERE status = 'druck'")
    unpaid = scalar(
        """SELECT COUNT(*) FROM orders
           WHERE status IN ('fertig', 'geliefert') AND COALESCE(paid, 0) = 0"""
    )
    unpaid_sum = scalar(
        """SELECT COALESCE(SUM(price), 0) FROM orders
           WHERE status IN ('fertig', 'geliefert') AND COALESCE(paid, 0) = 0"""
    )
    overdue = scalar(
        """SELECT COUNT(*) FROM orders
           WHERE due_date IS NOT NULL AND due_date <> '' AND due_date < ?
             AND status NOT IN ('fertig', 'geliefert', 'storniert')""",
        (today,),
    )
    stock_value = scalar("SELECT COALESCE(SUM(weight / 1000.0 * price_per_kg), 0) FROM inventory")
    low_stock = conn.execute(
        "SELECT * FROM inventory WHERE weight < min_weight ORDER BY weight ASC"
    ).fetchall()

    return {
        "revenue_month": revenue_month,
        "profit_month": profit_month,
        "revenue_year": revenue_year,
        "open_count": open_count,
        "printing_count": printing_count,
        "unpaid": unpaid,
        "unpaid_sum": unpaid_sum,
        "overdue": overdue,
        "stock_value": stock_value,
        "low_stock": low_stock,
    }
