# SENT Tool (CLI) – Mach Systems SAE J2716 Interface

Dieses Tool liest SENT (Fast/Slow/Error) **direkt vom Mach Systems SAE J2716 Interface** (Serial/USB-VCP oder TCP)
und gibt die Daten **live human-readable** auf der Konsole aus.

Optional kann das Tool:
- **RAW** (wie empfangen, volle framed packets) mitschreiben
- **Decoded CSV** (menschenlesbar) mitschreiben

## Installation

Aktiviere dein venv und installiere Requirements:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
