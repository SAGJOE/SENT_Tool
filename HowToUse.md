# HowToUse – SENT Tool (CLI) für Mach Systems SAE J2716 Interface

Dieses Dokument erklärt, wie du das CLI-Tool bedienst: Live-Anzeige, Logging (menschenlesbar + Rohdaten),
Filter/Anzeigeoptionen, typische Probleme und Beispiele.

---

## 1) Voraussetzungen

- Windows PowerShell oder Terminal
- Python 3.10+ (empfohlen: 3.12)
- Virtuelle Umgebung (`.venv`)
- COM-Port muss frei sein.

---

## 2) Projektstruktur

Im Ordner `SENT_Tool`:

```
SENT_Tool/
  requirements.txt
  README.md
  HowToUse.md
  sent_tool/
    __init__.py
    cli.py
    live_decode.py
    mach_protocol.py
    transports.py
    sensor_803405.py
```

---

## 3) Installation (einmalig)

PowerShell öffnen und in den Projektordner wechseln:

```powershell
cd $HOME\Desktop\PythonScripte\SENT_Tool
```

Virtuelle Umgebung erstellen und aktivieren:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

Dependencies installieren:

```powershell
python -m pip install -r requirements.txt
```

### Test: pyserial installiert?
```powershell
python -c "import serial; print(serial.__version__)"
```

---

## 4) Grundprinzip: Default-Verhalten

✅ **Default:**  
Das Tool gibt **jedes empfangene Paket** als **eine human-readable Zeile** mit Zeitstempel **live** auf der CLI aus.  
Stoppen mit **Ctrl + C**.

---

## Chanel auswahl als Argument
--channel 0
## Oder Alle SENT Kanäle
--all-channels


## 5) Live lesen (Standard)

### Verbindung über Serial (COM-Port)
Beispiel:

```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0
```

> Hinweis: Mach nutzt häufig **0-basierte Kanäle** (0..3), selbst wenn die GUI „Channel 1..4“ zeigt.  
> Wenn bei dir `ch=0` in der Ausgabe steht, ist das normal.

### Verbindung über TCP (Ethernet)
Beispiel:

```powershell
python -m sent_tool.cli live --tcp 192.168.1.100:8000 --channel 0
```

---

## 6) Laufzeit steuern: Dauer / Anzahl

### Stop nach N Sekunden
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --duration 10
```

### Stop nach N Paketen
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --count 1000
```

---

## 7) Menschenlesbare CSV speichern (Decoded)

### Standard (Comma als Separator)
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --out-csv live_decoded.csv
```

### Excel (DE) – Semikolon als Trennzeichen
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --out-csv live_decoded.csv --csv-sep ";"
```

**Warum `;`?**  
Deutsches Excel erwartet oft Semikolon als Trennzeichen, sonst landet alles in einer Spalte.

---

## 8) Rohdaten speichern (RAW, „wie empfangen“)

RAW-Logging speichert **die kompletten framed Pakete** (STX..ETX) so, wie sie vom Interface kommen.

### 8.1 Binär (empfohlen, 1:1)
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --raw-out live_raw.bin
```

### 8.2 RAW als CSV (Hex pro Paket)
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --raw-out live_raw.csv --raw-format csv
```

### 8.3 RAW als Text (Hex pro Zeile)
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --raw-out live_raw.txt --raw-format hex
```

---

## 9) Beides gleichzeitig (decoded + raw) – **wie gefordert**

```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 `
  --out-csv live_decoded.csv --csv-sep ";" `
  --raw-out live_raw.bin
```

---

## 10) Konsole: Rohdaten zusätzlich anzeigen

Default ist **nur human-readable**.  
Mit `--print-raw` wird zusätzlich der Rohpayload als Hex gezeigt.

```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 --print-raw
```

---

## 11) Ohne Konsole laufen lassen (nur Logging)

```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0 `
  --quiet `
  --out-csv live_decoded.csv --csv-sep ";" `
  --raw-out live_raw.bin
```

---


### Keine Daten kommen rein
1. SEA Tool geschlossen? (COM-Port frei)
2. Richtiger COM-Port? (`COM7`)
3. Richtiger Kanal? (oft **channel 0** = GUI Channel 1)
4. Sensor powered / signal present?

### Excel zeigt alles in einer Spalte
Nutze `--csv-sep ";"` oder importiere über **Daten → Aus Text/CSV** und wähle Separator.

---

## 14) Quick Reference (Cheat Sheet)

**Live (Default):**
```powershell
python -m sent_tool.cli live --serial COM7 --baud 115200 --channel 0
```

**Stoppen:** `Ctrl + C`

**Decoded CSV:**
```powershell
--out-csv out.csv --csv-sep ";"
```

**RAW Dump:**
```powershell
--raw-out raw.bin
```

**RAW zusätzlich auf Konsole:**
```powershell
--print-raw
```

**Nur Logging ohne Konsole:**
```powershell
--quiet
```
