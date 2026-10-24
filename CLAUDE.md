# Lustigkeits-Ranking

Web-App, in der Freundesgruppen sich wöchentlich oder täglich per Up-/Downvote bewerten.
Daraus ergibt sich pro Person ein Humor-Score von 0 bis 10 mit Verlaufsgraph.

## Dokumente

- `docs/anforderungen.md` – Quelle der Wahrheit. Alle Anforderungen haben IDs (z. B. VOT-03).
- `docs/plan.md` – Datenmodell, Projektstruktur, Meilensteine, aktueller Stand.

Bei Widerspruch zwischen Code und Anforderungen: nachfragen, nicht selbst entscheiden.

## Stack

- Python 3.12+, Flask, Jinja2-Templates, HTMX
- Flask-SQLAlchemy + Flask-Migrate, SQLite (später ggf. Postgres)
- Flask-Login, Magic-Link-Tokens über itsdangerous
- Apache ECharts per CDN für den Graph
- pywebpush, Service Worker, Web-App-Manifest (PWA)
- pytest, ruff
- Periodenupdate als Flask-CLI-Befehl, ausgelöst durch cron/systemd-Timer (kein Scheduler im Prozess)

Keine weiteren Abhängigkeiten ohne Rückfrage.

## Befehle

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # APP_ENV=development für lokale Entwicklung
flask --app app run --debug          # Entwicklungsserver
pytest                               # Tests
ruff check . && ruff format --check . # Lint/Format
flask --app app db upgrade           # Migrationen anwenden
python scripts/simulate.py --k 0.5 --d 0.95  # Score-Verläufe für die Kalibrierung von K und d
flask --app app users allow <email>  # Adresse für Kontoanlage ohne Einladung freischalten (E3)
```

Neue Befehle (z. B. Periodenupdate) hier eintragen, sobald sie existieren.

## Arbeitsweise

- Nur den aktuellen Meilenstein aus `docs/plan.md` umsetzen. Nichts vorziehen.
- Vor größeren Änderungen kurz planen. Unklarheiten erfragen statt raten.
- Jede fachliche Änderung bekommt Tests. Fertig heißt: `pytest` grün und `ruff` sauber.
- Commits klein halten, Anforderungs-IDs in die Commit-Nachricht (z. B. `feat: Voting-Fenster (VOT-01, VOT-05)`).
- Nach Abschluss eines Meilensteins den Stand in `docs/plan.md` aktualisieren.
- Secrets nur in `.env`, nie committen.

## Fachliche Invarianten

Diese Regeln dürfen nie verletzt werden. Jede gehört durch Tests abgesichert.

- Votes aus anonymen Perioden werden nie einer Person zugeordnet ausgegeben, außer dem Bewertenden seine eigenen (NFA-06, VOT-09).
- Ob eine Periode anonym ist, steht mit ihrem Beginn fest.
- Einstellungsänderungen wirken erst ab der nächsten Periode (SET-01).
- Gespeicherte Periodenergebnisse werden nie neu berechnet (SCO-06).
- Das Periodenupdate ist idempotent (PER-02).
- Niemand kann sich selbst bewerten (VOT-03).
- Jede Anfrage prüft Gruppenmitgliedschaft, Admin-Funktionen zusätzlich die Admin-Rolle (NFA-07).

## Code-Konventionen

- Code, Bezeichner und Kommentare auf Englisch, UI-Texte auf Deutsch.
- Type Hints überall. Kleine Funktionen.
- Die Score-Berechnung liegt in einem reinen Python-Modul ohne Flask- oder DB-Importe.
- Zeit nie direkt mit `datetime.now()` lesen, sondern über eine injizierbare Uhr, damit Tests die Zeit steuern können.
- In der Datenbank alle Zeitstempel in UTC. Umrechnung in die Gruppenzeitzone nur bei Fenster-Logik und Anzeige.

## Aktueller Stand

Meilenstein: M4 (Voting und Periodenlauf). M0 bis M3 sind abgeschlossen. Details in `docs/plan.md`.
