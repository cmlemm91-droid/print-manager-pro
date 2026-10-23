"""PrintManager Pro – Auftragsverwaltung für 3D-Druck.
Läuft auf Raspberry Pi (oder jedem Rechner) mit FastAPI + SQLite.
"""
from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import (
    BACKUP_DIR,
    BASE_DIR,
    DB_PATH,
    DEFAULT_SETTINGS,
    UPLOAD_DIR,
    connect,
    create_backup,
    get_db,
    init_db,
    load_settings,
    save_settings,
    setting_number,
)
from pdf_invoice import build_invoice_pdf, invoice_filename
from services import (
    calculate,
    create_order,
    dashboard_stats,
    delete_order,
    ensure_invoice_number,
    order_totals,
    set_status,
    toggle_paid,
    update_order,
)
from utils import (
    DONE_STATUSES,
    OPEN_STATUSES,
    PRIORITIES,
    STATUS,
    STATUS_ORDER,
    color_hex,
    date_value,
    days_until,
    flash_url,
    fmt_date,
    fmt_datetime,
    integer,
    is_overdue,
    money,
    now_str,
    num,
    number_text,
    percent,
    safe_filename,
    status_info,
    today_str,
)

STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(TEMPLATE_DIR).mkdir(parents=True, exist_ok=True)

GERMAN_MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PrintManager Pro", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

templates.env.filters["money"] = money
templates.env.filters["num"] = lambda value: number_text(value, 2)
templates.env.filters["num0"] = lambda value: number_text(value, 0)
templates.env.filters["num1"] = lambda value: number_text(value, 1)
templates.env.filters["date"] = fmt_date
templates.env.filters["datetime"] = fmt_datetime
templates.env.filters["date_value"] = date_value
templates.env.filters["color"] = color_hex
templates.env.globals["status_info"] = status_info
templates.env.globals["STATUS"] = STATUS
templates.env.globals["STATUS_ORDER"] = STATUS_ORDER
templates.env.globals["PRIORITIES"] = PRIORITIES
templates.env.globals["is_overdue"] = is_overdue
templates.env.globals["days_until"] = days_until


# --------------------------------------------------------------------- Basics
@app.middleware("http")
async def csrf_cookie(request: Request, call_next):
    token = request.cookies.get("pm_csrf") or secrets.token_hex(24)
    request.state.csrf_token = token
    response = await call_next(request)
    if request.cookies.get("pm_csrf") != token:
        response.set_cookie(
            "pm_csrf", token, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True
        )
    return response


def render(request: Request, conn, name: str, status_code: int = 200, **context):
    settings = load_settings(conn)
    context.setdefault("settings", settings)
    context["csrf_token"] = getattr(request.state, "csrf_token", "")
    context["flash"] = request.query_params.get("flash")
    context["active"] = request.url.path
    context["today"] = today_str()
    try:
        context.setdefault(
            "nav_open_count",
            conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status IN ('angebot', 'bestaetigt', 'druck')"
            ).fetchone()[0],
        )
    except Exception:
        context.setdefault("nav_open_count", 0)
    return templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )


async def read_form(request: Request):
    form = await request.form()
    token = form.get("_csrf")
    expected = getattr(request.state, "csrf_token", None)
    if not token or not expected or not secrets.compare_digest(str(token), str(expected)):
        raise HTTPException(status_code=403, detail="Formular abgelaufen. Bitte Seite neu laden.")
    return form


def form_text(form, key: str, default: str = "") -> str:
    value = form.get(key)
    if value is None:
        return default
    return str(value).strip()


def order_query(conn, where: str = "", params=(), order_by: str = "o.created_at DESC"):
    clause = (where.strip() + " ") if where and where.strip() else ""
    return conn.execute(
        """SELECT o.*, c.name AS customer_name, c.company AS customer_company,
                  m.material, m.color, p.name AS printer_name
           FROM orders o
           LEFT JOIN customers c ON c.id = o.customer_id
           LEFT JOIN inventory m ON m.id = o.material_id
           LEFT JOIN printers p ON p.id = o.printer_id
           %sORDER BY %s""" % (clause, order_by),
        params,
    ).fetchall()


def get_order(conn, order_id: int):
    row = conn.execute(
        """SELECT o.*, c.name AS customer_name, c.company AS customer_company,
                  c.email AS customer_email, c.street, c.house_number, c.zip, c.city,
                  c.phone AS customer_phone,
                  m.material, m.color, m.price_per_kg AS current_material_price,
                  p.name AS printer_name, p.cost_per_hour AS current_printer_cost
           FROM orders o
           LEFT JOIN customers c ON c.id = o.customer_id
           LEFT JOIN inventory m ON m.id = o.material_id
           LEFT JOIN printers p ON p.id = o.printer_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    return row


def build_order_payload(conn, form, settings, existing=None):
    customer_id = integer(form.get("customer_id"))
    material_id = integer(form.get("material_id"))
    printer_id = integer(form.get("printer_id"))

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        return None, "Bitte einen gültigen Kunden auswählen."
    material = conn.execute("SELECT * FROM inventory WHERE id = ?", (material_id,)).fetchone()
    if not material:
        return None, "Bitte ein gültiges Material auswählen."
    printer = conn.execute("SELECT * FROM printers WHERE id = ?", (printer_id,)).fetchone()
    if not printer:
        return None, "Bitte einen gültigen Drucker auswählen."

    model = form_text(form, "model")
    if not model:
        return None, "Bitte einen Modellnamen angeben."

    quantity = max(1, min(1000, integer(form.get("quantity"), 1)))
    weight = max(0.0, num(form.get("weight_used")))
    duration = max(0.0, num(form.get("duration_hours")))
    cad_hours = max(0.0, num(form.get("cad_hours")))
    extra = max(0.0, num(form.get("extra_cost")))
    margin = num(form.get("margin_percent"), setting_number(settings, "margin_percent", 30))
    margin = max(0.0, min(1000.0, margin))
    override = 1 if form.get("price_override") else 0
    manual_price = max(0.0, num(form.get("price")))

    if not override:
        manual_price = 0.0

    data = {
        "weight_used": weight,
        "duration_hours": duration,
        "cad_hours": cad_hours,
        "extra_cost": extra,
        "material_price_kg": setting_number({"v": material["price_per_kg"]}, "v"),
        "printer_cost_hour": float(printer["cost_per_hour"] or 0),
        "printer_power_watt": float(printer["power_watt"] or 150),
        "cad_rate": setting_number(settings, "cad_hourly_rate", 20),
        "margin_percent": margin,
        "price_override": override,
        "price": manual_price,
    }
    costs = calculate(data, settings)

    status = existing["status"] if existing else "angebot"
    if not existing:
        requested = form_text(form, "status", "angebot")
        if requested in STATUS and requested != "storniert":
            status = requested

    priority = form_text(form, "priority", "normal")
    if priority not in PRIORITIES:
        priority = "normal"

    due = form_text(form, "due_date")

    payload = {
        "customer_id": customer_id,
        "material_id": material_id,
        "printer_id": printer_id,
        "model": model,
        "quantity": quantity,
        "weight_used": weight,
        "duration_hours": duration,
        "cad_hours": cad_hours,
        "material_price_kg": data["material_price_kg"],
        "printer_cost_hour": data["printer_cost_hour"],
        "printer_power_watt": data["printer_power_watt"],
        "cad_rate": data["cad_rate"],
        "material_cost": costs["material_cost"],
        "machine_cost": costs["machine_cost"],
        "cad_cost": costs["cad_cost"],
        "energy_cost": costs["energy_cost"],
        "extra_cost": costs["extra_cost"],
        "extra_label": form_text(form, "extra_label", "Sonstiges") or "Sonstiges",
        "cost_total": costs["cost_total"],
        "margin_percent": costs["margin_percent"],
        "price": costs["price"],
        "price_override": costs["price_override"],
        "status": status,
        "priority": priority,
        "due_date": due or None,
        "notes": form_text(form, "notes") or None,
    }
    return payload, None


# ------------------------------------------------------------------ Dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db=Depends(get_db)):
    stats = dashboard_stats(db, load_settings(db))

    month_rows = db.execute(
        """SELECT strftime('%Y-%m', COALESCE(completed_at, created_at)) AS month,
                  COALESCE(SUM(price), 0) AS revenue,
                  COALESCE(SUM(price - cost_total), 0) AS profit
           FROM orders
           WHERE status IN ('fertig', 'geliefert')
           GROUP BY month"""
    ).fetchall()
    by_month = {row["month"]: row for row in month_rows}

    months = []
    cursor = date.today().replace(day=1)
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    chart = []
    peak = 0
    for month in months:
        key = month.strftime("%Y-%m")
        row = by_month.get(key)
        revenue = float(row["revenue"]) if row else 0.0
        peak = max(peak, revenue)
        chart.append({
            "label": "%s %s" % (GERMAN_MONTHS[month.month - 1], str(month.year)[2:]),
            "revenue": revenue,
            "profit": float(row["profit"]) if row else 0.0,
        })
    for item in chart:
        item["height"] = round((item["revenue"] / peak) * 100, 1) if peak else 0

    recent = order_query(db, "", (), "o.created_at DESC LIMIT 8")
    upcoming = order_query(
        db,
        """WHERE o.due_date IS NOT NULL AND o.due_date <> ''
             AND o.due_date <= ? AND o.status NOT IN ('fertig', 'geliefert', 'storniert')
             AND o.status IN ('angebot', 'bestaetigt', 'druck')""",
        ((date.today() + timedelta(days=14)).isoformat(),),
        "o.due_date ASC LIMIT 6",
    )
    top_customers = db.execute(
        """SELECT c.id, c.name, COUNT(o.id) AS order_count, COALESCE(SUM(o.price), 0) AS revenue
           FROM customers c JOIN orders o ON o.customer_id = c.id
           WHERE o.status IN ('fertig', 'geliefert')
           GROUP BY c.id ORDER BY revenue DESC LIMIT 5"""
    ).fetchall()

    return render(
        request, db, "dashboard.html",
        page_title="Dashboard",
        page_subtitle="Die aktuelle Lage in deinem 3D-Druck-Business.",
        stats=stats, chart=chart, chart_peak=peak,
        recent=recent, upcoming=upcoming, top_customers=top_customers,
    )


# --------------------------------------------------------------------- Orders
@app.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request, db=Depends(get_db)):
    status_filter = request.query_params.get("status", "open")
    q = (request.query_params.get("q") or "").strip()
    sort = request.query_params.get("sort", "neu")

    where = []
    params = []
    if status_filter == "open":
        where.append("o.status IN ('angebot', 'bestaetigt', 'druck')")
    elif status_filter in STATUS:
        where.append("o.status = ?")
        params.append(status_filter)
    if q:
        where.append("(o.model LIKE ? OR o.order_number LIKE ? OR c.name LIKE ?)")
        like = "%" + q + "%"
        params.extend([like, like, like])

    order_by = {
        "neu": "o.created_at DESC",
        "alt": "o.created_at ASC",
        "faellig": "CASE WHEN o.due_date IS NULL OR o.due_date = '' THEN 1 ELSE 0 END, o.due_date ASC",
        "preis": "o.price DESC",
        "nummer": "o.order_number DESC",
    }.get(sort, "o.created_at DESC")

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    orders = order_query(db, clause, tuple(params), order_by)

    counts = {row["status"]: row["c"] for row in db.execute(
        "SELECT status, COUNT(*) AS c FROM orders GROUP BY status"
    )}
    total = sum(counts.values())
    open_total = sum(counts.get(key, 0) for key in OPEN_STATUSES)

    return render(
        request, db, "orders.html",
        page_title="Aufträge",
        page_subtitle="Von der Anfrage bis zur Lieferung.",
        orders=orders, counts=counts, total=total, open_total=open_total,
        status_filter=status_filter, q=q, sort=sort,
    )


@app.get("/orders/new", response_class=HTMLResponse)
async def order_new(request: Request, db=Depends(get_db)):
    settings = load_settings(db)
    customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
    materials = db.execute("SELECT * FROM inventory ORDER BY material, color").fetchall()
    printers = db.execute("SELECT * FROM printers WHERE active = 1 ORDER BY name").fetchall()

    default_customer = integer(request.query_params.get("customer_id"))
    calc = {
        "materials": {str(m["id"]): float(m["price_per_kg"] or 0) for m in materials},
        "printers": {
            str(p["id"]): {"cost": float(p["cost_per_hour"] or 0), "power": float(p["power_watt"] or 150)}
            for p in printers
        },
        "settings": {
            "cad": setting_number(settings, "cad_hourly_rate", 20),
            "electricity": setting_number(settings, "electricity_price", 0.35),
            "margin": setting_number(settings, "margin_percent", 30),
            "vat": 0 if str(settings.get("small_business")) == "1" else setting_number(settings, "vat_rate", 19),
            "small_business": str(settings.get("small_business")) == "1",
        },
    }
    return render(
        request, db, "order_form.html",
        page_title="Neuer Auftrag",
        page_subtitle="Kalkulation inklusive – Preis wird automatisch berechnet.",
        order=None, customers=customers, materials=materials, printers=printers,
        default_customer=default_customer, calc_json=json.dumps(calc).replace("</", "<\\/"),
        default_margin=setting_number(settings, "margin_percent", 30),
        default_due=(date.today() + timedelta(days=7)).isoformat(),
    )


@app.post("/orders")
async def order_create(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    settings = load_settings(db)
    payload, error = build_order_payload(db, form, settings)
    if error:
        return RedirectResponse(flash_url("/orders/new", error), status_code=303)
    order_id = create_order(db, payload)
    return RedirectResponse(
        flash_url("/orders/%d" % order_id, "Auftrag %s wurde angelegt." % payload["order_number"]),
        status_code=303,
    )


@app.get("/orders/{order_id:int}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    settings = load_settings(db)
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    totals = order_totals(order, settings)
    movements = db.execute(
        """SELECT sm.*, i.material, i.color FROM stock_movements sm
           LEFT JOIN inventory i ON i.id = sm.inventory_id
           WHERE sm.order_id = ? ORDER BY sm.id DESC""",
        (order_id,),
    ).fetchall()

    return render(
        request, db, "order_detail.html",
        page_title=order["order_number"] or ("Auftrag #%d" % order_id),
        page_subtitle=order["model"] or "",
        order=order, customer=customer, totals=totals, movements=movements,
        next_status=status_info(order["status"])["next"],
        invoice_ready=bool(order["invoice_number"]),
    )


@app.get("/orders/{order_id:int}/edit", response_class=HTMLResponse)
async def order_edit(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    settings = load_settings(db)
    customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
    materials = db.execute("SELECT * FROM inventory ORDER BY material, color").fetchall()
    printers = db.execute("SELECT * FROM printers ORDER BY name").fetchall()

    calc = {
        "materials": {str(m["id"]): float(m["price_per_kg"] or 0) for m in materials},
        "printers": {
            str(p["id"]): {"cost": float(p["cost_per_hour"] or 0), "power": float(p["power_watt"] or 150)}
            for p in printers
        },
        "settings": {
            "cad": setting_number(settings, "cad_hourly_rate", 20),
            "electricity": setting_number(settings, "electricity_price", 0.35),
            "margin": setting_number(settings, "margin_percent", 30),
            "vat": 0 if str(settings.get("small_business")) == "1" else setting_number(settings, "vat_rate", 19),
            "small_business": str(settings.get("small_business")) == "1",
        },
    }
    return render(
        request, db, "order_form.html",
        page_title="Auftrag bearbeiten",
        page_subtitle=order["order_number"] or ("Auftrag #%d" % order_id),
        order=order, customers=customers, materials=materials, printers=printers,
        default_customer=order["customer_id"], calc_json=json.dumps(calc).replace("</", "<\\/"),
        default_margin=float(order["margin_percent"] or 0),
    )


@app.post("/orders/{order_id:int}")
async def order_update(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    form = await read_form(request)
    settings = load_settings(db)
    payload, error = build_order_payload(db, form, settings, existing=order)
    if error:
        return RedirectResponse(flash_url("/orders/%d/edit" % order_id, error), status_code=303)
    update_order(db, order, payload)
    return RedirectResponse(
        flash_url("/orders/%d" % order_id, "Änderungen gespeichert."), status_code=303
    )


@app.post("/orders/{order_id:int}/status")
async def order_status(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    form = await read_form(request)
    new_status = form_text(form, "status")
    if new_status not in STATUS:
        return RedirectResponse(flash_url("/orders/%d" % order_id, "Unbekannter Status."), status_code=303)
    set_status(db, order, new_status)
    message = "Status geändert: %s." % status_info(new_status)["label"]
    return RedirectResponse(flash_url("/orders/%d" % order_id, message), status_code=303)


@app.post("/orders/{order_id:int}/paid")
async def order_paid(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    await read_form(request)
    paid = toggle_paid(db, order)
    return RedirectResponse(
        flash_url("/orders/%d" % order_id, "Als bezahlt markiert." if paid else "Zahlung zurückgesetzt."),
        status_code=303,
    )


@app.post("/orders/{order_id:int}/duplicate")
async def order_duplicate(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    await read_form(request)
    payload = {
        "customer_id": order["customer_id"],
        "material_id": order["material_id"],
        "printer_id": order["printer_id"],
        "model": (order["model"] or "") + " (Kopie)",
        "quantity": order["quantity"],
        "weight_used": order["weight_used"],
        "duration_hours": order["duration_hours"],
        "cad_hours": order["cad_hours"],
        "material_price_kg": order["material_price_kg"],
        "printer_cost_hour": order["printer_cost_hour"],
        "printer_power_watt": order["printer_power_watt"],
        "cad_rate": order["cad_rate"],
        "material_cost": order["material_cost"],
        "machine_cost": order["machine_cost"],
        "cad_cost": order["cad_cost"],
        "energy_cost": order["energy_cost"],
        "extra_cost": order["extra_cost"],
        "extra_label": order["extra_label"],
        "cost_total": order["cost_total"],
        "margin_percent": order["margin_percent"],
        "price": order["price"],
        "price_override": order["price_override"],
        "status": "angebot",
        "priority": order["priority"],
        "due_date": date.today().isoformat(),
        "notes": order["notes"],
        "paid": 0,
    }
    new_id = create_order(db, payload)
    return RedirectResponse(
        flash_url("/orders/%d" % new_id, "Auftrag als Kopie angelegt."), status_code=303
    )


@app.post("/orders/{order_id:int}/delete")
async def order_delete(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    await read_form(request)
    delete_order(db, order)
    return RedirectResponse(flash_url("/orders", "Auftrag gelöscht."), status_code=303)


# ------------------------------------------------------------------- Rechnung
@app.get("/orders/{order_id:int}/invoice")
async def order_invoice(request: Request, order_id: int, db=Depends(get_db)):
    order = get_order(db, order_id)
    if order["status"] == "storniert":
        return RedirectResponse(
            flash_url("/orders/%d" % order_id, "Für stornierte Aufträge kann keine Rechnung erstellt werden."),
            status_code=303,
        )
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    if not customer:
        return RedirectResponse(flash_url("/orders/%d" % order_id, "Kunde fehlt."), status_code=303)

    settings = load_settings(db)
    number = ensure_invoice_number(db, order)
    order = get_order(db, order_id)
    pdf = build_invoice_pdf(settings, customer, order, number, order["invoiced_at"])
    filename = invoice_filename(number, customer["name"])
    disposition = "attachment" if request.query_params.get("download") else "inline"
    headers = {
        "Content-Disposition": "%s; filename=\"%s\"; filename*=UTF-8''%s"
        % (disposition, filename.encode("ascii", "ignore").decode() or "rechnung.pdf", quote(filename))
    }
    return Response(content=pdf, media_type="application/pdf", headers=headers)


@app.get("/invoices", response_class=HTMLResponse)
async def invoices_page(request: Request, db=Depends(get_db)):
    settings = load_settings(db)
    rows = db.execute(
        """SELECT o.*, c.name AS customer_name FROM orders o
           LEFT JOIN customers c ON c.id = o.customer_id
           WHERE o.invoice_number IS NOT NULL AND o.invoice_number <> ''
           ORDER BY o.invoiced_at DESC, o.id DESC"""
    ).fetchall()
    rows = [dict(row, totals=order_totals(row, settings)) for row in rows]
    summary = {
        "count": len(rows),
        "net": sum(float(r["price"] or 0) for r in rows),
        "gross": sum(r["totals"]["gross"] for r in rows),
        "open": sum(float(r["price"] or 0) for r in rows if not int(r["paid"] or 0)),
    }
    return render(
        request, db, "invoices.html",
        page_title="Rechnungen", page_subtitle="Alle erstellten Rechnungen im Überblick.",
        invoices=rows, summary=summary,
    )


# ------------------------------------------------------------------ Kunden
@app.get("/customers", response_class=HTMLResponse)
async def customers_page(request: Request, db=Depends(get_db)):
    q = (request.query_params.get("q") or "").strip()
    where = ""
    params = ()
    if q:
        where = "WHERE c.name LIKE ? OR c.company LIKE ? OR c.email LIKE ? OR c.city LIKE ?"
        like = "%" + q + "%"
        params = (like, like, like, like)
    customers = db.execute(
        """SELECT c.*, COUNT(o.id) AS order_count,
                  COALESCE(SUM(CASE WHEN o.status IN ('fertig', 'geliefert') THEN o.price ELSE 0 END), 0) AS revenue,
                  COALESCE(SUM(CASE WHEN o.status IN ('angebot', 'bestaetigt', 'druck') THEN 1 ELSE 0 END), 0) AS open_count
           FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
           %s GROUP BY c.id ORDER BY c.name COLLATE NOCASE""" % where,
        params,
    ).fetchall()
    return render(
        request, db, "customers.html",
        page_title="Kunden", page_subtitle="Kontaktdaten und Auftragshistorie.",
        customers=customers, q=q,
    )


@app.get("/customers/new", response_class=HTMLResponse)
async def customer_new(request: Request, db=Depends(get_db)):
    return render(
        request, db, "customer_form.html",
        page_title="Neuer Kunde", page_subtitle="Kontaktdaten erfassen.",
        customer=None,
    )


@app.post("/customers")
async def customer_create(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    name = form_text(form, "name")
    if not name:
        return RedirectResponse(flash_url("/customers/new", "Bitte einen Namen angeben."), status_code=303)
    db.execute(
        """INSERT INTO customers (name, company, email, phone, street, house_number, zip, city, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name, form_text(form, "company") or None, form_text(form, "email") or None,
            form_text(form, "phone") or None, form_text(form, "street") or None,
            form_text(form, "house_number") or None, form_text(form, "zip") or None,
            form_text(form, "city") or None, form_text(form, "notes") or None,
        ),
    )
    db.commit()
    customer_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return RedirectResponse(
        flash_url("/customers/%d" % customer_id, "Kunde wurde angelegt."), status_code=303
    )


@app.get("/customers/{customer_id:int}", response_class=HTMLResponse)
async def customer_detail(request: Request, customer_id: int, db=Depends(get_db)):
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    settings = load_settings(db)
    orders = order_query(db, "WHERE o.customer_id = ?", (customer_id,), "o.created_at DESC")
    revenue = sum(float(o["price"] or 0) for o in orders if o["status"] in DONE_STATUSES)
    open_count = sum(1 for o in orders if o["status"] in OPEN_STATUSES)
    return render(
        request, db, "customer_detail.html",
        page_title=customer["name"], page_subtitle="Kundenprofil und Historie.",
        customer=customer, orders=orders, revenue=revenue, open_count=open_count,
        invoice_count=sum(1 for o in orders if o["invoice_number"]),
    )


@app.get("/customers/{customer_id:int}/edit", response_class=HTMLResponse)
async def customer_edit(request: Request, customer_id: int, db=Depends(get_db)):
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return render(
        request, db, "customer_form.html",
        page_title="Kunde bearbeiten", page_subtitle=customer["name"],
        customer=customer,
    )


@app.post("/customers/{customer_id:int}")
async def customer_update(request: Request, customer_id: int, db=Depends(get_db)):
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    form = await read_form(request)
    name = form_text(form, "name")
    if not name:
        return RedirectResponse(
            flash_url("/customers/%d/edit" % customer_id, "Bitte einen Namen angeben."), status_code=303
        )
    db.execute(
        """UPDATE customers SET name = ?, company = ?, email = ?, phone = ?, street = ?,
           house_number = ?, zip = ?, city = ?, notes = ? WHERE id = ?""",
        (
            name, form_text(form, "company") or None, form_text(form, "email") or None,
            form_text(form, "phone") or None, form_text(form, "street") or None,
            form_text(form, "house_number") or None, form_text(form, "zip") or None,
            form_text(form, "city") or None, form_text(form, "notes") or None, customer_id,
        ),
    )
    db.commit()
    return RedirectResponse(
        flash_url("/customers/%d" % customer_id, "Kundendaten gespeichert."), status_code=303
    )


@app.post("/customers/{customer_id:int}/delete")
async def customer_delete(request: Request, customer_id: int, db=Depends(get_db)):
    await read_form(request)
    count = db.execute("SELECT COUNT(*) AS c FROM orders WHERE customer_id = ?", (customer_id,)).fetchone()["c"]
    if count:
        return RedirectResponse(
            flash_url("/customers/%d" % customer_id,
                      "Kunde kann nicht gelöscht werden – es gibt noch %d Aufträge." % count),
            status_code=303,
        )
    db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    db.commit()
    return RedirectResponse(flash_url("/customers", "Kunde gelöscht."), status_code=303)


# -------------------------------------------------------------------- Lager
@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request, db=Depends(get_db)):
    inventory = db.execute("SELECT * FROM inventory ORDER BY material, color").fetchall()
    movements = db.execute(
        """SELECT sm.*, i.material, i.color FROM stock_movements sm
           LEFT JOIN inventory i ON i.id = sm.inventory_id
           ORDER BY sm.id DESC LIMIT 40"""
    ).fetchall()
    value = sum((float(i["weight"] or 0) / 1000) * float(i["price_per_kg"] or 0) for i in inventory)
    low = [i for i in inventory if float(i["weight"] or 0) < float(i["min_weight"] or 0)]
    edit_id = integer(request.query_params.get("edit"))
    edit_item = db.execute("SELECT * FROM inventory WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render(
        request, db, "inventory.html",
        page_title="Lager", page_subtitle="Filament, Bestände und Wareneingänge.",
        inventory=inventory, movements=movements, stock_value=value, low=low, edit_item=edit_item,
    )


@app.post("/inventory")
async def inventory_create(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    material = form_text(form, "material")
    color = form_text(form, "color")
    if not material or not color:
        return RedirectResponse(flash_url("/inventory", "Material und Farbe sind Pflichtfelder."), status_code=303)
    weight = max(0.0, num(form.get("weight")))
    db.execute(
        """INSERT INTO inventory (material, color, weight, price_per_kg, min_weight, supplier, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            material, color, weight, max(0.0, num(form.get("price_per_kg"))),
            max(0.0, num(form.get("min_weight"), 200)), form_text(form, "supplier") or None,
            form_text(form, "notes") or None,
        ),
    )
    item_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    if weight:
        db.execute(
            "INSERT INTO stock_movements (inventory_id, change_g, reason) VALUES (?, ?, ?)",
            (item_id, weight, "Anfangsbestand"),
        )
    db.commit()
    return RedirectResponse(flash_url("/inventory", "Material angelegt."), status_code=303)


@app.post("/inventory/{item_id:int}")
async def inventory_update(request: Request, item_id: int, db=Depends(get_db)):
    item = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Material nicht gefunden")
    form = await read_form(request)
    new_weight = max(0.0, num(form.get("weight")))
    db.execute(
        """UPDATE inventory SET material = ?, color = ?, weight = ?, price_per_kg = ?,
           min_weight = ?, supplier = ?, notes = ? WHERE id = ?""",
        (
            form_text(form, "material", item["material"]), form_text(form, "color", item["color"]),
            new_weight, max(0.0, num(form.get("price_per_kg"))),
            max(0.0, num(form.get("min_weight"), 200)), form_text(form, "supplier") or None,
            form_text(form, "notes") or None, item_id,
        ),
    )
    difference = new_weight - float(item["weight"] or 0)
    if abs(difference) >= 0.01:
        db.execute(
            "INSERT INTO stock_movements (inventory_id, change_g, reason) VALUES (?, ?, ?)",
            (item_id, difference, "Bestand korrigiert"),
        )
    db.commit()
    return RedirectResponse(flash_url("/inventory", "Material gespeichert."), status_code=303)


@app.post("/inventory/{item_id:int}/stock")
async def inventory_stock(request: Request, item_id: int, db=Depends(get_db)):
    form = await read_form(request)
    amount = num(form.get("amount"))
    if amount <= 0:
        return RedirectResponse(flash_url("/inventory", "Bitte eine Menge größer als 0 angeben."), status_code=303)
    db.execute("UPDATE inventory SET weight = weight + ? WHERE id = ?", (amount, item_id))
    db.execute(
        "INSERT INTO stock_movements (inventory_id, change_g, reason) VALUES (?, ?, ?)",
        (item_id, amount, form_text(form, "reason", "Wareneingang") or "Wareneingang"),
    )
    db.commit()
    return RedirectResponse(flash_url("/inventory", "Wareneingang gebucht."), status_code=303)


@app.post("/inventory/{item_id:int}/delete")
async def inventory_delete(request: Request, item_id: int, db=Depends(get_db)):
    await read_form(request)
    count = db.execute("SELECT COUNT(*) AS c FROM orders WHERE material_id = ?", (item_id,)).fetchone()["c"]
    if count:
        return RedirectResponse(
            flash_url("/inventory", "Material wird noch in %d Aufträgen verwendet." % count),
            status_code=303,
        )
    db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    db.execute("DELETE FROM stock_movements WHERE inventory_id = ?", (item_id,))
    db.commit()
    return RedirectResponse(flash_url("/inventory", "Material gelöscht."), status_code=303)


# ------------------------------------------------------------------ Drucker
@app.get("/printers", response_class=HTMLResponse)
async def printers_page(request: Request, db=Depends(get_db)):
    printers = db.execute(
        """SELECT p.*, COUNT(o.id) AS order_count,
                  COALESCE(SUM(CASE WHEN o.status IN ('druck', 'fertig', 'geliefert') THEN o.duration_hours ELSE 0 END), 0) AS hours,
                  COALESCE(SUM(CASE WHEN o.status IN ('fertig', 'geliefert') THEN o.price ELSE 0 END), 0) AS revenue,
                  COALESCE(SUM(CASE WHEN o.status = 'druck' THEN 1 ELSE 0 END), 0) AS active_jobs
           FROM printers p LEFT JOIN orders o ON o.printer_id = p.id
           GROUP BY p.id ORDER BY p.active DESC, p.name COLLATE NOCASE"""
    ).fetchall()
    edit_id = integer(request.query_params.get("edit"))
    edit_item = db.execute("SELECT * FROM printers WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render(
        request, db, "printers.html",
        page_title="Drucker", page_subtitle="Maschinen, Stundensätze und Auslastung.",
        printers=printers, edit_item=edit_item,
        active_count=sum(1 for p in printers if p["active"]),
        total_hours=sum(float(p["hours"] or 0) for p in printers),
        total_revenue=sum(float(p["revenue"] or 0) for p in printers),
        active_jobs=sum(int(p["active_jobs"] or 0) for p in printers),
    )


@app.post("/printers")
async def printer_create(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    name = form_text(form, "name")
    if not name:
        return RedirectResponse(flash_url("/printers", "Bitte einen Namen angeben."), status_code=303)
    db.execute(
        """INSERT INTO printers (name, cost_per_hour, power_watt, purchase_price, notes, active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (
            name, max(0.0, num(form.get("cost_per_hour"))),
            max(0.0, num(form.get("power_watt"), 150)),
            max(0.0, num(form.get("purchase_price"))), form_text(form, "notes") or None,
        ),
    )
    db.commit()
    return RedirectResponse(flash_url("/printers", "Drucker angelegt."), status_code=303)


@app.post("/printers/{printer_id:int}")
async def printer_update(request: Request, printer_id: int, db=Depends(get_db)):
    printer = db.execute("SELECT * FROM printers WHERE id = ?", (printer_id,)).fetchone()
    if not printer:
        raise HTTPException(status_code=404, detail="Drucker nicht gefunden")
    form = await read_form(request)
    db.execute(
        """UPDATE printers SET name = ?, cost_per_hour = ?, power_watt = ?, purchase_price = ?,
           notes = ?, active = ? WHERE id = ?""",
        (
            form_text(form, "name", printer["name"]), max(0.0, num(form.get("cost_per_hour"))),
            max(0.0, num(form.get("power_watt"), 150)), max(0.0, num(form.get("purchase_price"))),
            form_text(form, "notes") or None,
            1 if form.get("active") else 0, printer_id,
        ),
    )
    db.commit()
    return RedirectResponse(flash_url("/printers", "Drucker gespeichert."), status_code=303)


@app.post("/printers/{printer_id:int}/delete")
async def printer_delete(request: Request, printer_id: int, db=Depends(get_db)):
    await read_form(request)
    count = db.execute("SELECT COUNT(*) AS c FROM orders WHERE printer_id = ?", (printer_id,)).fetchone()["c"]
    if count:
        return RedirectResponse(
            flash_url("/printers", "Drucker wird noch in %d Aufträgen verwendet." % count),
            status_code=303,
        )
    db.execute("DELETE FROM printers WHERE id = ?", (printer_id,))
    db.commit()
    return RedirectResponse(flash_url("/printers", "Drucker gelöscht."), status_code=303)


# --------------------------------------------------------------- Einstellungen
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db=Depends(get_db)):
    settings = load_settings(db)
    logo = None
    for extension in ("png", "jpg", "jpeg"):
        candidate = UPLOAD_DIR / ("logo.%s" % extension)
        if candidate.exists():
            logo = "/static/uploads/logo.%s" % extension
            break
    return render(
        request, db, "settings.html",
        page_title="Einstellungen", page_subtitle="Firmendaten, Preise und Rechnungen.",
        settings=settings, logo=logo,
        db_path=str(DB_PATH), backup_dir=str(BACKUP_DIR),
        python_version="%d.%d.%d" % __import__("sys").version_info[:3],
    )


@app.post("/settings")
async def settings_save(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    values = {}
    for key in DEFAULT_SETTINGS:
        if key == "small_business":
            values[key] = "1" if form.get(key) else "0"
        elif key in ("order_prefix", "invoice_prefix"):
            raw = form_text(form, key).upper()
            cleaned = "".join(ch for ch in raw if ch.isalnum())
            values[key] = cleaned[:6] or DEFAULT_SETTINGS[key]
        else:
            values[key] = form_text(form, key, DEFAULT_SETTINGS[key])

    if not values["company_name"]:
        values["company_name"] = DEFAULT_SETTINGS["company_name"]
    values["cad_hourly_rate"] = str(max(0.0, num(values["cad_hourly_rate"], 20)))
    values["margin_percent"] = str(max(0.0, num(values["margin_percent"], 30)))
    values["electricity_price"] = str(max(0.0, num(values["electricity_price"], 0.35)))
    values["vat_rate"] = str(min(100.0, max(0.0, num(values["vat_rate"], 19))))
    values["payment_days"] = str(max(0, integer(values["payment_days"], 14)))

    save_settings(db, values)
    return RedirectResponse(flash_url("/settings", "Einstellungen gespeichert."), status_code=303)


@app.post("/settings/logo")
async def settings_logo(request: Request, db=Depends(get_db)):
    form = await read_form(request)
    upload = form.get("logo")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return RedirectResponse(flash_url("/settings", "Bitte eine Bilddatei auswählen."), status_code=303)
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in ("png", "jpg", "jpeg"):
        return RedirectResponse(
            flash_url("/settings", "Bitte eine PNG- oder JPG-Datei verwenden."), status_code=303
        )
    content = await upload.read()
    if len(content) > 4 * 1024 * 1024:
        return RedirectResponse(flash_url("/settings", "Das Logo darf maximal 4 MB groß sein."), status_code=303)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for existing in UPLOAD_DIR.glob("logo.*"):
        try:
            existing.unlink()
        except OSError:
            pass
    (UPLOAD_DIR / ("logo.%s" % extension)).write_bytes(content)
    return RedirectResponse(flash_url("/settings", "Logo gespeichert."), status_code=303)


@app.post("/settings/logo/delete")
async def settings_logo_delete(request: Request, db=Depends(get_db)):
    await read_form(request)
    for existing in UPLOAD_DIR.glob("logo.*"):
        try:
            existing.unlink()
        except OSError:
            pass
    return RedirectResponse(flash_url("/settings", "Logo entfernt."), status_code=303)


@app.post("/settings/backup")
async def settings_backup(request: Request, db=Depends(get_db)):
    await read_form(request)
    target = create_backup()
    return RedirectResponse(
        flash_url("/settings", "Sicherung erstellt: %s" % target.name), status_code=303
    )


# ------------------------------------------------------------------- Exporte
@app.get("/export/orders.csv")
async def export_orders(db=Depends(get_db)):
    rows = order_query(db, "", (), "o.id DESC")
    header = [
        "Auftragsnummer", "Datum", "Kunde", "Modell", "Menge", "Material", "Farbe", "Drucker",
        "Gewicht (g)", "Druckzeit (h)", "CAD (h)", "Kosten (EUR)", "Preis netto (EUR)",
        "Status", "Bezahlt", "Faellig", "Rechnung",
    ]
    data = [header]
    for row in rows:
        data.append([
            row["order_number"] or "", (row["created_at"] or "")[:10], row["customer_name"] or "",
            row["model"] or "", row["quantity"], row["material"] or "", row["color"] or "",
            row["printer_name"] or "", number_text(row["weight_used"], 1),
            number_text(row["duration_hours"], 1), number_text(row["cad_hours"], 1),
            number_text(row["cost_total"]), number_text(row["price"]),
            status_info(row["status"])["label"], "ja" if int(row["paid"] or 0) else "nein",
            row["due_date"] or "", row["invoice_number"] or "",
        ])
    return csv_response(data, "auftraege.csv")


@app.get("/export/customers.csv")
async def export_customers(db=Depends(get_db)):
    rows = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
    header = ["Name", "Firma", "E-Mail", "Telefon", "Strasse", "Nr.", "PLZ", "Ort", "Notizen"]
    data = [header]
    for row in rows:
        data.append([
            row["name"] or "", row["company"] or "", row["email"] or "", row["phone"] or "",
            row["street"] or "", row["house_number"] or "", row["zip"] or "", row["city"] or "",
            row["notes"] or "",
        ])
    return csv_response(data, "kunden.csv")


def csv_response(rows, filename):
    def cell(value):
        text = str(value if value is not None else "")
        if any(ch in text for ch in ';"\r\n'):
            text = '"' + text.replace('"', '""') + '"'
        return text

    content = "\ufeff" + "\r\n".join(";".join(cell(v) for v in row) for row in rows)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=%s" % filename},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": "PrintManager Pro"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse("/static/favicon.svg", status_code=307)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    conn = connect()
    try:
        titles = {403: "Zugriff verweigert", 404: "Nicht gefunden", 405: "Nicht erlaubt"}
        return render(
            request, conn, "error.html",
            page_title=titles.get(exc.status_code, "Fehler"),
            page_subtitle="",
            code=exc.status_code,
            message=str(exc.detail or "Es ist ein Fehler aufgetreten."),
            status_code=exc.status_code,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
