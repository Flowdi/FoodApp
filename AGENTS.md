# AGENTS.md

## Ziel und Sprache

Vorrat ist eine deutschsprachige, i18n-fähige Multi-Device-PWA. Code, Bezeichner, Commit-Nachrichten und Kommentare sind Englisch; UI-Texte sind Deutsch und gehören nach Möglichkeit in `frontend/src/i18n.ts`.

## Architekturregeln

- Der FastAPI-Server ist die einzige Wahrheit. Keine Bestandsberechnung darf ausschließlich im Client erfolgen.
- Jede Bestandsänderung erzeugt genau ein unveränderliches `StockMovement`. Journalzeilen niemals ändern oder löschen; Korrekturen sind Gegenbuchungen.
- Jeder schreibende Bestandsaufruf braucht einen client-generierten UUID-Idempotency-Key.
- Mutationen sperren die Charge, prüfen `version` und schreiben Charge plus Journal in einer DB-Transaktion.
- Jede fachliche Abfrage muss über `household_id` eingeschränkt sein. IDs aus Requests nie ohne Haushaltsfilter laden.
- Rollen werden serverseitig geprüft. UI-Ausblendung allein ist keine Autorisierung.
- SQLite ist nur Entwicklung/Test; Parallelitätsverhalten wird gegen PostgreSQL geprüft.
- API-Schemas sind Pydantic-v2-Modelle. SQLAlchemy verwendet ausschließlich 2.x-Style.

## Verzeichnisübersicht

- `backend/app/models.py`: persistentes Domänenmodell
- `backend/app/services/`: transaktionale Geschäftslogik
- `backend/app/routers/`: dünne HTTP-Schicht
- `backend/alembic/`: Schema-Migrationen
- `backend/tests/`: Unit- und API-Tests
- `frontend/src/`: Vue-3-PWA
- `scripts/`: Betriebs- und Backup-Helfer

## Befehle

```bash
docker compose up --build
docker compose exec api python -m backend.app.seed
pytest
ruff check backend
ruff format --check backend
mypy backend/app
cd frontend && npm install && npm run build
```

## Änderungscheckliste

1. Neue DB-Felder erhalten eine Alembic-Migration; bestehende Migrationen nach Veröffentlichung nicht umschreiben.
2. Neue Mutationen bekommen Idempotenz-, Berechtigungs- und Konflikttests.
3. API-Fehler sind auf Deutsch verständlich und besitzen bei programmatischen Konflikten einen stabilen `code`.
4. Touch-Ziele sind mindestens 44 px groß; Kernpfade funktionieren bei 320 px Breite und im Dark Mode.
5. Keine Secrets, Tokens, Produktionsdaten oder Dumps committen.
6. README und `.env.example` bei Betriebsänderungen mitziehen.

## Definition of Done

Backend-Tests, Ruff, mypy und Frontend-Build laufen grün; die Migration funktioniert auf einer leeren PostgreSQL-Datenbank; kritische Benutzerpfade wurden auf mobiler Breite geprüft; Sicherheits- und Mandantengrenzen besitzen Tests.
