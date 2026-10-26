# PrintManager Pro 2.0

Auftragsverwaltung für ein 3D-Druck-Business – gebaut für den **Raspberry Pi**.
Läuft komplett lokal: FastAPI + SQLite, keine Cloud, keine externen Dienste, kein CDN.

Diese Anleitung ist für Einsteiger geschrieben. Du musst nichts programmieren –
du kopierst nur Befehle in ein Terminal und drückst Enter.

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

---

# Installation auf dem Raspberry Pi

## Was du brauchst

- Einen **Raspberry Pi** (3, 4 oder 5) mit Netzteil
- Eine **microSD-Karte** (mindestens 16 GB) und einen Kartenleser
- Ein **Netzwerkkabel** oder WLAN-Zugang
- Einen **Windows-, Mac- oder Linux-Rechner** mit Internet und einem Browser
- Etwa **30 Minuten Zeit**

Du brauchst **keinen** Monitor und **keine** Tastatur für den Pi – alles Weitere
läuft über deinen normalen Rechner.

---

## Schritt 1: Speicherkarte vorbereiten

1. Lade den **Raspberry Pi Imager** herunter:
   <https://www.raspberrypi.com/software/>
2. Starte das Programm und stecke die microSD-Karte in deinen Rechner.
3. Wähle:
   - **Raspberry Pi-Gerät:** dein Modell
   - **Betriebssystem:** „Raspberry Pi OS (64-bit)“
     (Wenn du den Pi nur als Server nutzt, reicht auch „Raspberry Pi OS Lite (64-bit)“.)
   - **Speicher:** deine microSD-Karte
4. Klicke auf **„Einstellungen bearbeiten“** (Zahnrad) und fülle aus:
   - **Hostname:** `printmanager`
   - **Benutzername:** `pi` (oder deinen Wunschnamen – merke ihn dir!)
   - **Passwort:** ein sicheres Passwort
   - **WLAN:** Netzwerkname, Passwort und Land (nur nötig, wenn du kein Kabel verwendest)
   - **Dienste:** „SSH aktivieren“ → **Passwort-Authentifizierung verwenden**
5. Auf **„Schreiben“** klicken und warten, bis es fertig ist.
6. Karte in den Pi stecken, Netzteil anschließen und **2–3 Minuten warten**.

> Der erste Start dauert etwas länger. Das ist normal.

---

## Schritt 2: Mit dem Pi verbinden

### Variante A: Du hast einen Monitor am Pi

Öffne dort das Programm **Terminal** und weiter mit Schritt 3.

### Variante B: Du arbeitest von deinem Windows-Rechner (empfohlen)

1. Drücke auf Windows die Tasten **Windows + R**, tippe `powershell` ein und drücke Enter.
2. Tippe folgenden Befehl ein (ersetze `pi` durch deinen Benutzernamen, falls du einen anderen gewählt hast):

   ```powershell
   ssh pi@printmanager.local
   ```

3. Beim ersten Mal erscheint eine Frage wie „Are you sure you want to continue connecting?“.
   Tippe `yes` und drücke Enter.
4. Gib dein Pi-Passwort ein. **Beim Tippen siehst du nichts** – das ist normal.
   Einfach eintippen und Enter drücken.

Wenn `printmanager.local` nicht funktioniert, finde die IP-Adresse des Pi:

- im Router unter „Geräte“ / „DHCP“ (Gerät heißt `printmanager`), oder
- am Pi mit dem Befehl `hostname -I`

Dann verbinden mit:

```powershell
ssh pi@192.168.1.42
```

(Ersetze die IP durch deine.)

> **Was ist das Terminal?** Ein Fenster, in dem du Befehle eintippst.
> Du kopierst einen Befehl und fügst ihn ein – unter Windows mit **Rechtsklick**,
> am Pi mit **Strg + Umschalt + V** – und drückst Enter.
> Warte immer, bis der Befehl fertig ist, bevor du den nächsten eingibst.

---

## Schritt 3: System aktualisieren

Führe diese beiden Befehle nacheinander aus:

```bash
sudo apt update
sudo apt full-upgrade -y
```

- `sudo` bedeutet „als Administrator ausführen“. Du wirst nach deinem Passwort gefragt.
- Das Update kann einige Minuten dauern.

Danach den Pi einmal neu starten:

```bash
sudo reboot
```

Warte eine Minute und verbinde dich erneut per SSH (Schritt 2).

---

## Schritt 4: Benötigte Programme installieren

```bash
sudo apt install -y python3 python3-venv python3-pip git
```

Das installiert Python, die Python-Umgebung und Git (zum Herunterladen des Projekts).

Prüfen, ob alles da ist:

```bash
python3 --version
git --version
```

Es sollte etwas wie `Python 3.11.x` und `git version 2.x` erscheinen.

---

## Schritt 5: Projekt herunterladen

```bash
cd ~
git clone https://github.com/cmlemm91-droid/print-manager-pro.git print-manager
cd print-manager
```

Damit liegt das Projekt im Ordner `/home/pi/print-manager`
(bei einem anderen Benutzernamen entsprechend, z. B. `/home/chris/print-manager`).

> **Alternative ohne Git:** Du kannst auf GitHub auch **„Code → Download ZIP“** wählen,
> die Datei auf den Pi kopieren und entpacken. Der Ordner muss danach `print-manager` heißen.

---

## Schritt 6: Python-Umgebung einrichten

Eine „virtuelle Umgebung“ ist ein abgeschotteter Ordner für die Bibliotheken,
die dieses Programm braucht. So bleibt dein System sauber.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Nach dem zweiten Befehl steht `(.venv)` am Anfang der Eingabezeile – das ist richtig so.

Die Installation der Bibliotheken dauert 1–3 Minuten.

> **Muss ich `source .venv/bin/activate` jedes Mal eingeben?**
> Ja, wenn du die App von Hand startest. Bei der automatischen Variante
> (Schritt 9) übernimmt das der Dienst.

---

## Schritt 7: App zum ersten Mal starten

```bash
python3 main.py
```

Es erscheint ungefähr:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Wichtig:** Dieses Terminal-Fenster muss offen bleiben, solange die App läuft.
Mit **Strg + C** beendest du sie wieder.

Beim ersten Start werden automatisch angelegt:

- die Datenbank `print_manager.db`
- der Ordner `backups/` mit einer ersten Sicherung

---

## Schritt 8: App im Browser öffnen

Öffne auf deinem normalen Rechner:

```
http://printmanager.local:8000
```

oder mit der IP-Adresse:

```
http://192.168.1.42:8000
```

Du solltest das Dashboard sehen. Vom Handy funktioniert es genauso,
solange Handy und Pi im **selben WLAN** sind.

> **Seite lädt nicht?**
> - Prüfen, ob die App noch läuft (Terminal offen? Fehlermeldung?)
> - IP-Adresse prüfen: am Pi `hostname -I`
> - Handy im gleichen WLAN?
> - Firewall am Pi: `sudo ufw allow 8000/tcp` (nur wenn ufw installiert ist)

---

## Schritt 9: Automatisch starten (empfohlen)

Damit die App nach jedem Neustart von allein läuft, richtest du einen Dienst ein.

### 9.1 Benutzernamen und Pfad prüfen

```bash
whoami
pwd
```

`whoami` zeigt deinen Benutzernamen (z. B. `pi`), `pwd` den Projektordner
(z. B. `/home/pi/print-manager`).

### 9.2 Dienst-Datei anpassen

Öffne die Vorlage:

```bash
nano printmanager.service
```

Ändere die drei Zeilen so, dass sie zu dir passen:

```ini
User=pi
WorkingDirectory=/home/pi/print-manager
ExecStart=/home/pi/print-manager/.venv/bin/python main.py
```

- `User=` → dein Benutzername aus `whoami`
- `WorkingDirectory=` → der Ordner aus `pwd`
- `ExecStart=` → derselbe Ordner, gefolgt von `/.venv/bin/python main.py`

Beispiel: Heißt dein Benutzer `chris` und der Ordner `/home/chris/print-manager`,
dann sehen die Zeilen so aus:

```ini
User=chris
WorkingDirectory=/home/chris/print-manager
ExecStart=/home/chris/print-manager/.venv/bin/python main.py
```

Speichern mit **Strg + O**, dann **Enter**, beenden mit **Strg + X**.

### 9.3 Dienst installieren und starten

> **Wichtig:** Falls die App aus Schritt 7 noch läuft, beende sie zuerst mit **Strg + C**.
> Sonst ist der Port 8000 belegt und der Dienst kann nicht starten.

```bash
sudo cp printmanager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now printmanager
```

Status prüfen:

```bash
sudo systemctl status printmanager
```

Dort muss `active (running)` stehen. Mit **Q** kommst du wieder heraus.

### 9.4 Nützliche Befehle

```bash
sudo systemctl restart printmanager    # neu starten
sudo systemctl stop printmanager       # stoppen
sudo systemctl disable printmanager    # Autostart abschalten
journalctl -u printmanager -f          # Live-Protokoll (Strg+C beendet)
```

---

## Schritt 10: App einrichten

1. **Einstellungen** → Firmendaten, Bankverbindung, Marge, Strompreis, USt und ggf. Logo hinterlegen.
2. **Lager** → Material mit Preis pro kg und Warnschwelle anlegen.
3. **Drucker** → Maschine mit Stundensatz und Leistungsaufnahme anlegen.
4. **Kunden** → ersten Kunden erfassen.
5. **Aufträge → Neuer Auftrag** → Kalkulation prüfen und speichern.

Der Materialverbrauch wird erst beim Status **„Druck starten“** vom Lager abgezogen –
nicht schon beim Anlegen eines Angebots.
Wird ein Auftrag storniert oder gelöscht, kommt das Material automatisch zurück.

---

## Updates einspielen

Wenn es eine neue Version gibt:

```bash
cd ~/print-manager
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart printmanager
```

Deine Datenbank bleibt dabei unverändert und wird beim Start automatisch erweitert.

---

## Daten, Backup und Umzug

- Datenbank: `print_manager.db` im Projektordner
- Sicherungen: `backups/print_manager_JJJJ-MM-TT.db` (automatisch, maximal 30)
- Manuelle Sicherung: **Einstellungen → Sicherung & Export → Jetzt sichern**
- Für einen Umzug reicht es, `print_manager.db` und den Ordner `static/uploads/` zu kopieren.

> **Wichtig:** Eine SD-Karte kann irgendwann defekt sein. Kopiere den Ordner
> `backups/` deshalb regelmäßig auf einen USB-Stick oder deinen Rechner.
> Das geht z. B. mit einem FTP-Programm (FileZilla) oder über die Freigabe im Netzwerk.

Die Datenbank wird beim Start automatisch erweitert. Bestehende Daten aus der alten Version bleiben erhalten.

---

## Probleme lösen

**`python3: command not found`**
→ Schritt 4 ausführen: `sudo apt install -y python3 python3-venv python3-pip`

**`error: externally-managed-environment`**
→ Du hast `pip install` ohne aktivierte Umgebung ausgeführt.
Erst `source .venv/bin/activate`, dann erneut installieren.

**`Address already in use` / Port 8000 belegt**
→ Anderen Port verwenden:
```bash
PORT=8080 python3 main.py
```
Aufruf dann unter `http://printmanager.local:8080`.

**`git: command not found`**
→ `sudo apt install -y git`

**`Permission denied` beim Start**
→ Prüfe, ob du im richtigen Ordner bist (`pwd` → `/home/pi/print-manager`)
und ob die Umgebung aktiv ist (`(.venv)` vor der Eingabezeile).

**Seite lädt nicht / Verbindung abgelehnt**
→ Läuft die App? Terminal offen bzw. `sudo systemctl status printmanager`?
→ Stimmt die IP? `hostname -I`
→ Sind Rechner und Pi im selben Netzwerk?

**SSH meldet „Host key verification failed“**
→ Nur nach einer Neuinstallation des Pi nötig:
```bash
ssh-keygen -R printmanager.local
```

**Passwort wird beim Tippen nicht angezeigt**
→ Das ist bei Linux normal. Einfach tippen und Enter drücken.

**Rechnung zeigt Sonderzeichen falsch**
→ Die Rechnung nutzt die PDF-Standardschrift (Windows-1252).
Emojis werden bewusst durch `?` ersetzt.

---

## Sicherheit

Die App hat bewusst **keine Anmeldung** – sie ist für das lokale Heim-/Werkstattnetz gedacht.
Bitte **nicht direkt ins Internet stellen**. Wenn Zugriff von außen nötig ist, einen VPN-Zugang
(z. B. WireGuard/Tailscale) verwenden.

---

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

## Für Fortgeschrittene

| Umgebungsvariable | Bedeutung | Standard |
|---|---|---|
| `PORT` | Port des Webservers | `8000` |
| `HOST` | Bind-Adresse | `0.0.0.0` |
| `PRINT_MANAGER_DB` | Pfad zur Datenbank | `print_manager.db` |

Beispiel zum Testen mit einer separaten Datenbank:

```bash
PRINT_MANAGER_DB=/home/pi/test.db PORT=8080 python3 main.py
```

## Änderungen gegenüber der alten Version

- Klare Startskripte und eine Anleitung, die auch ohne Linux-Kenntnisse funktioniert
- Rechnungsdatum nutzt `datetime` statt des unter Windows wirkungslosen `os.popen('date')`
- Rechnung übernimmt die **Firmendaten aus den Einstellungen** statt fester Platzhalter
- Doppelte `update_printer`-Route entfernt, Lager-Differenzbuchung korrekt umgesetzt
- Status-Workflow, Auftragsnummern, Marge, Stromkosten, Zahlungsstatus ergänzt
- Offline-Design statt Tailwind-CDN, funktioniert auch ohne Internet
