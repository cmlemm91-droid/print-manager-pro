"""Kleine Helfer für Formatierung, Status und Formulare."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

COLOR_NAMES = {
    "schwarz": "#111827",
    "weiß": "#f8fafc",
    "weiss": "#f8fafc",
    "grau": "#9ca3af",
    "silber": "#cbd5e1",
    "rot": "#ef4444",
    "blau": "#3b82f6",
    "grün": "#22c55e",
    "gruen": "#22c55e",
    "gelb": "#facc15",
    "orange": "#f97316",
    "lila": "#a855f7",
    "violett": "#8b5cf6",
    "rosa": "#f472b6",
    "pink": "#ec4899",
    "braun": "#92400e",
    "gold": "#d4af37",
    "natur": "#e7e5e4",
    "transparent": "#e2e8f0",
    "klar": "#e2e8f0",
    "weiß-transparent": "#e2e8f0",
}


def color_hex(value) -> str:
    """Wandelt Farbnamen in CSS-Farben um, damit die Punkte im UI stimmen."""
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", text):
        return text
    return COLOR_NAMES.get(text.lower(), "#94a3b8")

STATUS = {
    "angebot": {"label": "Angebot", "tone": "slate", "next": "bestaetigt", "next_label": "Bestätigen"},
    "bestaetigt": {"label": "Bestätigt", "tone": "blue", "next": "druck", "next_label": "Druck starten"},
    "druck": {"label": "Im Druck", "tone": "amber", "next": "fertig", "next_label": "Druck fertig"},
    "fertig": {"label": "Fertig", "tone": "green", "next": "geliefert", "next_label": "Geliefert"},
    "geliefert": {"label": "Geliefert", "tone": "emerald", "next": None, "next_label": None},
    "storniert": {"label": "Storniert", "tone": "red", "next": None, "next_label": None},
}

STATUS_ORDER = ["angebot", "bestaetigt", "druck", "fertig", "geliefert", "storniert"]
OPEN_STATUSES = ("angebot", "bestaetigt", "druck")
PRODUCTION_STATUSES = ("druck", "fertig", "geliefert")
DONE_STATUSES = ("fertig", "geliefert")
PRIORITIES = {
    "niedrig": "Niedrig",
    "normal": "Normal",
    "hoch": "Hoch",
    "express": "Express",
}


def status_info(status):
    return STATUS.get(status, {"label": status or "–", "tone": "slate", "next": None, "next_label": None})


def is_production(status) -> bool:
    return status in PRODUCTION_STATUSES


def is_done(status) -> bool:
    return status in DONE_STATUSES


def num(value, default=0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." in text:
        # 1.234,56 -> 1234.56
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def integer(value, default=0) -> int:
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 1e9) -> float:
    return max(low, min(high, value))


def money(value, with_currency: bool = True) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    text = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + (" €" if with_currency else "")


def number_text(value, digits: int = 2) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if digits == 0:
        text = f"{number:,.0f}"
    else:
        text = f"{number:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def fmt_date(value, fallback="–") -> str:
    parsed = parse_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else fallback


def fmt_datetime(value, fallback="–") -> str:
    parsed = parse_date(value)
    return parsed.strftime("%d.%m.%Y, %H:%M") if parsed else fallback


def date_value(value) -> str:
    """Für <input type="date">."""
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_days(days) -> str:
    return (date.today() + timedelta(days=integer(days))).isoformat()


def days_until(value):
    parsed = parse_date(value)
    if not parsed:
        return None
    return (parsed.date() - date.today()).days


def is_overdue(order) -> bool:
    if not order:
        return False
    status = order["status"] if hasattr(order, "keys") else order.get("status")
    due = order["due_date"] if hasattr(order, "keys") else order.get("due_date")
    if status in DONE_STATUSES or status == "storniert":
        return False
    remaining = days_until(due)
    return remaining is not None and remaining < 0


def flash_url(url: str, message: str) -> str:
    separator = "&" if "?" in url else "?"
    return url + separator + "flash=" + quote(message)


def as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def percent(value, digits: int = 0) -> str:
    return f"{number_text(value, digits)} %"


def initials(name: str) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def safe_filename(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    cleaned = "".join(ch for ch in str(value) if ch in allowed)
    return cleaned or "download"


def round_money(value) -> float:
    return math.floor(float(value) * 100 + 0.5) / 100
