"""Rechnungs-PDF im einheitlichen Layout (fpdf2, keine externen Dienste)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from utils import date_value, fmt_date, money, number_text, parse_date

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"

INK = (15, 23, 42)
MUTED = (100, 116, 139)
LINE = (226, 232, 240)
BRAND = (37, 99, 235)
BRAND_SOFT = (239, 246, 255)
WHITE = (255, 255, 255)

PAGE_W = 210
MARGIN = 18
CONTENT_W = PAGE_W - 2 * MARGIN


def _clean(value) -> str:
    """Nur Zeichen, die die PDF-Kernschrift (Windows-1252) darstellen kann."""
    return str(value if value is not None else "").encode("cp1252", "replace").decode("cp1252")


class InvoicePDF(FPDF):
    def __init__(self, settings, customer, order, invoice_number, invoice_date=None):
        super().__init__(orientation="P", unit="mm", format="A4")
        # fpdf2 2.8+: Kernschriften werden über dieses Attribut kodiert.
        self.core_fonts_encoding = "windows-1252"
        self.settings = settings
        self.customer = customer
        self.order = order
        self.invoice_number = invoice_number
        self.invoice_date = parse_date(invoice_date) or date.today()
        self.set_auto_page_break(auto=False)
        self.set_margins(MARGIN, 15, MARGIN)
        self.set_title(_clean("Rechnung %s" % invoice_number))
        self.set_author(_clean(settings.get("company_name", "")))
        self.set_creator("PrintManager Pro")

    # ------------------------------------------------------------- Bausteine
    def text_at(self, x, y, text, size=10, style="", color=INK, width=0, align="L"):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.cell(width, size * 0.52, _clean(text), align=align, new_x=XPos.LEFT, new_y=YPos.TOP)

    def right_at(self, y, text, size=10, style="", color=INK, x=MARGIN, width=CONTENT_W):
        self.text_at(x, y, text, size=size, style=style, color=color, width=width, align="R")

    def wrapped(self, text, width, size):
        self.set_font("Helvetica", "", size)
        words = _clean(text).split()
        lines = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if not current or self.get_string_width(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # ------------------------------------------------------------------ Kopf
    def header_block(self):
        logo = None
        for extension in ("png", "jpg", "jpeg"):
            candidate = UPLOAD_DIR / ("logo.%s" % extension)
            if candidate.exists():
                logo = candidate
                break
        if logo:
            try:
                self.image(str(logo), x=MARGIN, y=14, w=42)
            except Exception:
                logo = None

        company = self.settings
        name = _clean(company.get("company_name", ""))
        lines = [
            company.get("company_street", ""),
            "%s %s" % (company.get("company_zip", ""), company.get("company_city", "")),
            company.get("company_phone", ""),
            company.get("company_email", ""),
            company.get("company_web", ""),
        ]
        y = 14
        self.right_at(y, name, size=11, style="B")
        y += 5.2
        for line in lines:
            if str(line).strip():
                self.right_at(y, line, size=8, color=MUTED)
                y += 4.0

        self.set_draw_color(*BRAND)
        self.set_line_width(0.7)
        self.line(MARGIN, 50, PAGE_W - MARGIN, 50)

        self.text_at(MARGIN, 57, "RECHNUNG", size=25, style="B", color=INK)

        meta_y = 59
        meta = [
            ("Rechnungsnr.", self.invoice_number),
            ("Datum", self.invoice_date.strftime("%d.%m.%Y")),
            ("Auftrag", self.order["order_number"] or "–"),
            ("Kundennr.", "K-%04d" % int(self.order["customer_id"] or 0)),
        ]
        for label, value in meta:
            self.right_at(meta_y, "%s: %s" % (label, value), size=8.5, color=MUTED)
            meta_y += 4.4

    def address_block(self):
        y = 82
        self.text_at(MARGIN, y, "RECHNUNGSEMPFÄNGER", size=7, style="B", color=MUTED)
        y += 5.5
        customer = self.customer
        self.text_at(MARGIN, y, customer["name"], size=10.5, style="B")
        y += 5.2
        if customer["company"]:
            self.text_at(MARGIN, y, customer["company"], size=9.5)
            y += 4.6
        if customer["street"]:
            self.text_at(MARGIN, y, "%s %s" % (customer["street"], customer["house_number"] or ""), size=9.5)
            y += 4.6
        if customer["zip"] or customer["city"]:
            self.text_at(MARGIN, y, "%s %s" % (customer["zip"] or "", customer["city"] or ""), size=9.5)
            y += 4.6
        if customer["email"]:
            self.text_at(MARGIN, y, customer["email"], size=9, color=MUTED)

        self.text_at(MARGIN, 130, "Sehr geehrte Damen und Herren,", size=9.5)
        self.text_at(MARGIN, 136.5, "vielen Dank für Ihren Auftrag. Wir berechnen Ihnen folgende Leistung:", size=9.5)

    # ----------------------------------------------------------------- Tabelle
    def items_table(self):
        top = 150
        self.set_fill_color(*INK)
        self.rect(MARGIN, top, CONTENT_W, 8.5, style="F")
        header_y = top + 2.4
        self.text_at(21, header_y, "POS", size=7.5, style="B", color=WHITE)
        self.text_at(31, header_y, "BESCHREIBUNG", size=7.5, style="B", color=WHITE)
        self.text_at(126, header_y, "MENGE", size=7.5, style="B", color=WHITE, width=16, align="C")
        self.text_at(144, header_y, "EINZELPREIS", size=7.5, style="B", color=WHITE, width=21, align="R")
        self.text_at(168, header_y, "GESAMT", size=7.5, style="B", color=WHITE, width=24, align="R")

        order = self.order
        quantity = max(1, int(order["quantity"] or 1))
        price = float(order["price"] or 0)
        unit_price = price / quantity

        description = "3D-Druck: %s" % (order["model"] or "Druckauftrag")
        details = []
        material = " ".join(filter(None, [order["material"] or "", order["color"] or ""]))
        if material:
            details.append(material)
        details.append("%s g Material" % number_text(order["weight_used"], 1))
        details.append("%s h Druckzeit" % number_text(order["duration_hours"], 1))
        if order["printer_name"]:
            details.append(order["printer_name"])
        if float(order["cad_hours"] or 0) > 0:
            details.append("%s h CAD" % number_text(order["cad_hours"], 1))
        if quantity > 1:
            details.append("%d Stück" % quantity)
        detail_text = " · ".join(details)

        desc_lines = self.wrapped(description, 92, 9.5)
        detail_lines = self.wrapped(detail_text, 92, 7.8)
        row_height = max(11, len(desc_lines) * 4.6 + len(detail_lines) * 3.9 + 5)

        y = top + 8.5
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(MARGIN, y + row_height, PAGE_W - MARGIN, y + row_height)

        self.text_at(21, y + 3, "1", size=9)
        line_y = y + 3
        for line in desc_lines:
            self.text_at(31, line_y, line, size=9.5)
            line_y += 4.6
        for line in detail_lines:
            self.text_at(31, line_y, line, size=7.8, color=MUTED)
            line_y += 3.9

        if quantity > 1:
            self.text_at(126, y + 3, "%d Stk" % quantity, size=9, width=16, align="C")
        else:
            self.text_at(126, y + 3, "1", size=9, width=16, align="C")
        self.text_at(144, y + 3, money(unit_price), size=9, width=21, align="R")
        self.text_at(168, y + 3, money(price), size=9, width=24, align="R")

        return y + row_height

    # ---------------------------------------------------------------- Summen
    def totals_block(self, y):
        from services import totals

        values = totals(self.order["price"], self.settings)
        x = 122
        width = 70

        def row(label, value, bold=False, color=INK):
            nonlocal y
            self.text_at(x, y, label, size=9, style="B" if bold else "", color=MUTED if not bold else color,
                         width=40, align="R")
            self.text_at(x + 42, y, value, size=9.5, style="B" if bold else "", color=color,
                         width=28, align="R")
            y += 6

        y += 6
        row("Nettobetrag", money(values["net"]))
        if not values["small_business"]:
            row("Umsatzsteuer %s %%" % number_text(values["vat_rate"], 0), money(values["vat"]))
        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.line(x + 20, y, x + width, y)
        y += 3

        self.set_fill_color(*BRAND_SOFT)
        self.rect(x, y - 1.5, width, 10, style="F")
        self.text_at(x, y, "Gesamtbetrag", size=11, style="B", color=BRAND, width=40, align="R")
        self.text_at(x + 42, y, money(values["gross"]), size=11, style="B", color=BRAND, width=28, align="R")
        y += 10

        if values["small_business"]:
            self.text_at(MARGIN, y + 4, "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.", size=7.5, color=MUTED)
        return y

    # ----------------------------------------------------------- Zahlung/Foot
    def payment_block(self, y):
        settings = self.settings
        days = int(float(settings.get("payment_days") or 14))
        due = self.invoice_date + timedelta(days=days)
        y = max(y + 16, 218)
        self.text_at(MARGIN, y, "Zahlungsinformationen", size=9.5, style="B")
        y += 6
        self.text_at(
            MARGIN, y,
            "Bitte überweisen Sie den Rechnungsbetrag bis zum %s auf das folgende Konto:" % due.strftime("%d.%m.%Y"),
            size=8.5, color=MUTED,
        )
        y += 6
        bank_parts = [
            "IBAN: %s" % settings.get("iban", ""),
            "BIC: %s" % settings.get("bic", ""),
        ]
        if settings.get("bank_name"):
            bank_parts.append("Bank: %s" % settings.get("bank_name"))
        self.text_at(MARGIN, y, "   ·   ".join(p for p in bank_parts if p.split(": ")[-1].strip()), size=8.5, style="B")

        y += 8
        self.text_at(MARGIN, y, "Verwendungszweck: %s" % self.invoice_number, size=8, color=MUTED)

    def footer_block(self):
        settings = self.settings
        y = 272
        self.set_draw_color(*LINE)
        self.set_line_width(0.25)
        self.line(MARGIN, y, PAGE_W - MARGIN, y)
        y += 5

        note = settings.get("invoice_note") or ""
        if note:
            self.text_at(MARGIN, y, note, size=8, style="I", color=MUTED)
            y += 4.6

        company_line = " · ".join(filter(None, [
            settings.get("company_name", ""),
            "%s %s" % (settings.get("company_street", ""), ""),
            ("%s %s" % (settings.get("company_zip", ""), settings.get("company_city", ""))).strip(),
            settings.get("company_phone", ""),
            settings.get("company_email", ""),
        ]))
        self.text_at(MARGIN, y, company_line, size=7.2, color=MUTED)
        y += 4

        legal = []
        if settings.get("tax_id"):
            legal.append("Steuernr.: %s" % settings["tax_id"])
        if settings.get("vat_id"):
            legal.append("USt-IdNr.: %s" % settings["vat_id"])
        if legal:
            self.text_at(MARGIN, y, " · ".join(legal), size=7.2, color=MUTED)

        self.right_at(272, "Seite %d" % self.page_no(), size=7.2, color=MUTED)

    def build(self) -> bytes:
        self.add_page()
        self.header_block()
        self.address_block()
        table_end = self.items_table()
        totals_end = self.totals_block(table_end)
        self.payment_block(totals_end)
        self.footer_block()
        return bytes(self.output())


def build_invoice_pdf(settings, customer, order, invoice_number, invoice_date=None) -> bytes:
    pdf = InvoicePDF(settings, customer, order, invoice_number, invoice_date)
    return pdf.build()


def invoice_filename(invoice_number: str, customer_name: str) -> str:
    from utils import safe_filename

    return safe_filename("Rechnung_%s_%s.pdf" % (invoice_number, customer_name))
