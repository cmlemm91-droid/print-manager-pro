# PrintManager Pro 2.0

Auftragsverwaltung für ein 3D-Druck-Business – gebaut für den **Raspberry Pi**.
Läuft komplett lokal: FastAPI + SQLite, keine Cloud, keine externen Dienste, kein CDN.

## Was die App kann

- **Aufträge** mit automatischer Nummer (`AU-2026-0001`), Status-Workflow, Fälligkeit, Priorität und Notizen
- **Kalkulation** aus Material, Maschinenzeit, CAD-Zeit, Strom und Zusatzkosten inklusive Marge
- **Preis manuell überschreiben**, falls der Kunde einen Festpreis bekommt
- **Lager** mit Mindestbestand, Wareneingängen und lückenloser Bewegungshistorie
- **Drucker** mit Stundensatz, Leistungsaufnahme, Auslastung und Umsatz
- **Kunden** mit Kontaktdaten, Historie, Umsatz und offenen Aufträgen
- **Rechnungen** als PDF mit Logo, Firmendaten, USt bzw. § 19 UStG und fortlaufender Nummer
- **Dashboard** mit Umsatz, Gewinn, Lagerwarnungen, überfälligen Aufträgen und Top-Kunden
- **Backup** automatisch beim Start (täglich, 30 Tage Aufbewahrung) und per Knopfdruck
- **CSV-Export** für Aufträge und Kunden

## Installation auf dem Raspberry Pi

Voraussetzung: Raspberry Pi OS mit Python 3.9 oder neuer.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# Projektordner, z. B. /home/pi/print-manager
cd /home/pi/print-manager

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

Danach im Browser öffnen:

```
http://<IP-des-Pi>:8000
```

Die IP findest du mit `hostname -I`.

## Automatisch starten (systemd)

1. Pfade in `printmanager.service` prüfen (Benutzer und Projektordner).
2. Service installieren:

```bash
sudo cp printmanager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now printmanager
sudo systemctl status printmanager
```

Logs ansehen:

```bash
journalctl -u printmanager -f
```

## Erste Schritte

1. **Einstellungen** → Firmendaten, Bankverbindung, Marge, Strompreis, USt und ggf. Logo hinterlegen.
2. **Lager** → Material mit Preis pro kg und Warnschwelle anlegen.
3. **Drucker** → Maschine mit Stundensatz und Leistungsaufnahme anlegen.
4. **Kunden** → ersten Kunden erfassen.
5. **Aufträge → Neuer Auftrag** → Kalkulation prüfen und speichern.

Der Materialverbrauch wird erst beim Status **„Druck starten“** vom Lager abgezogen – nicht schon beim Anlegen eines Angebots.
Wird ein Auftrag storniert oder gelöscht, kommt das Material automatisch zurück.

## Daten, Backup und Umzug

- Datenbank: `print_manager.db` im Projektordner
- Sicherungen: `backups/print_manager_JJJJ-MM-TT.db` (automatisch, maximal 30)
- Manuelle Sicherung: **Einstellungen → Sicherung & Export → Jetzt sichern**
- Für einen Umzug reicht es, `print_manager.db` und den Ordner `static/uploads/` zu kopieren.

Die Datenbank wird beim Start automatisch erweitert. Bestehende Daten aus der alten Version bleiben erhalten.

## Sicherheit

Die App hat bewusst **keine Anmeldung** – sie ist für das lokale Heim-/Werkstattnetz gedacht.
Bitte **nicht direkt ins Internet stellen**. Wenn Zugriff von außen nötig ist, einen VPN-Zugang
(z. B. WireGuard/Tailscale) verwenden.

## Projektstruktur

```
main.py              FastAPI-App und alle Routen
database.py          Schema, Migrationen, Einstellungen, Backups
services.py          Kalkulation, Lagerbuchungen, Nummernkreise
pdf_invoice.py       Rechnungs-PDF (fpdf2)
utils.py             Formatierung, Status, Hilfsfunktionen
templates/           Jinja2-Templates (base.html + Seiten)
static/css/app.css   eigenes Design (offline)
static/js/app.js     Live-Kalkulation und UI
static/icons.svg     Icon-Sprite
backups/             automatische Sicherungen
```

## Tipps

- **Port belegt?** `PORT=8080 python main.py` und dann Port 8080 aufrufen.
- **Kein Zugriff vom Handy?** Prüfen, ob Pi und Handy im selben WLAN sind; ggf. Firewall:
  `sudo ufw allow 8000/tcp`
- **PDF zeigt Sonderzeichen falsch?** Die Rechnung nutzt die PDF-Standardschrift (Windows-1252).
  Emojis werden bewusst durch `?` ersetzt.
- **Andere Datenbank testen:** `PRINT_MANAGER_DB=/pfad/test.db python main.py`

## Änderungen gegenüber der alten Version

- Fehlende Python-Installation war der Grund, warum die App nicht mehr startete – jetzt klare Startskripte und Anleitung
- Rechnungsdatum nutzt `datetime` statt des unter Windows wirkungslosen `os.popen('date')`
- Rechnung übernimmt die **Firmendaten aus den Einstellungen** statt fester Platzhalter
- Doppelte `update_printer`-Route entfernt, Lager-Differenzbuchung korrekt umgesetzt
- Status-Workflow, Auftragsnummern, Marge, Stromkosten, Zahlungsstatus ergänzt
- Offline-Design statt Tailwind-CDN, funktioniert auch ohne Internet
