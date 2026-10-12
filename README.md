# Vorrat

Vorrat ist eine selbst hostbare, mobile-first Haushaltsverwaltung für Lebensmittel. Der Server ist die einzige Wahrheit; jede Bestandsänderung landet als unveränderliche Buchung im Journal. Die PWA ist für zwei Android-Smartphones und mehrere Windows-PCs ausgelegt.

## Stand: Meilenstein 1 – belastbarer Kern

Enthalten sind:

- Registrierung/Login mit Argon2-Passwort-Hash, JWT-Zugriffstoken und serverseitig speicherbaren Refresh-Tokens
- Haushalts- und Rollenmodell (`owner`, `admin`, `member`, `viewer`) mit mandantensicherer API
- Produkte mit mehreren Barcodes, Lagerorte und Chargen
- transaktionales Buchungsjournal für Einkauf, Entnahme, Entsorgung und Storno
- Idempotency-Key je Schreibvorgang, pessimistische Zeilensperre plus Optimistic Locking (`version`)
- Browser-Barcode-Scan (EAN/UPC via ZXing), manueller Fallback und Open-Food-Facts-Lookup
- installierbare Vue-3-PWA in deutscher, i18n-fähiger Oberfläche; responsiv und mit Dark Mode
- Offline-Outbox auf IndexedDB-Basis (technische Basis; Konfliktoberfläche wird in Meilenstein 3 vervollständigt)
- PostgreSQL, Alembic, Docker Compose, HTTPS via Caddy und tägliche rotierende Backups
- Phase-2-Schema für Rezepte sowie getestete Einheitenumrechnung

Noch nicht als fertiger Workflow enthalten sind Einladungen/Passwort-Reset, vollständige Inventur, Umlagerung, CSV-Export, Push/E-Mail-Versand, Einkaufsliste, Live-Events und Produktbearbeitung. Diese sind unten bewusst als weitere Meilensteine ausgewiesen und sollten nicht als produktionsfertig betrachtet werden.

## Architektur

```text
Vue-PWA ── HTTPS/REST ── Caddy ── FastAPI ── SQLAlchemy ── PostgreSQL
   │                                  │
   └─ IndexedDB-Outbox                ├─ stock_batches (aktueller Stand)
                                      └─ stock_movements (unveränderliches Journal)
```

Das Frontend nutzt Vue 3 + Vite, weil Komponenten, TypeScript und ein robuster Service Worker bei überschaubarer Bundle-Größe zusammenkommen. Gegenüber HTMX ist die lokale Offline-Outbox und Kamera-Lebenszyklusverwaltung klarer gekapselt. Die REST-API bleibt unabhängig vom Frontend nutzbar und ist unter `/docs` dokumentiert.

Eine Buchung sperrt die Charge in PostgreSQL mit `SELECT … FOR UPDATE`, prüft deren Version und aktualisiert Bestand und Journal in derselben Transaktion. Ein innerhalb eines Haushalts eindeutiger Idempotency-Key macht Wiederholungen sicher. Stornos sind Gegenbuchungen; die Ursprungsbuchung bleibt erhalten.

## Schnellstart mit Docker

Voraussetzungen: Docker Engine mit Compose, eine Domain, die auf den Host zeigt (für lokale Tests funktioniert `localhost`).

```bash
cp .env.example .env
# SECRET_KEY und POSTGRES_PASSWORD in .env sicher setzen
docker compose up --build -d
docker compose exec api python -m backend.app.seed
```

Danach: `https://localhost` und `https://localhost/docs`. Caddys lokale CA muss auf Testgeräten einmal als vertrauenswürdig installiert werden; im Internet beschafft Caddy für eine echte `DOMAIN` automatisch ein Zertifikat.

Demo-Zugang nach dem Seed: `demo@vorrat.local` / `demo-password`. Diesen Account nie unverändert öffentlich bereitstellen.

## Lokale Entwicklung

Backend (Python 3.12+):

```bash
python -m venv .venv
. .venv/bin/activate              # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn backend.app.main:app --reload
```

Frontend (Node 22+):

```bash
cd frontend
npm install
npm run dev
```

Die Vite-Entwicklung leitet `/api` an `localhost:8000` weiter.

## Tests und Qualität

```bash
pytest
ruff check backend
ruff format --check backend
mypy backend/app
cd frontend && npm run build
```

Die Pflichtpfade für Idempotenz, einmaliges Storno, Einheiten und konkurrierende Entnahme sind angelegt. Für echte Parallelitätsaussagen muss der Konkurrenztest gegen PostgreSQL laufen; SQLite ignoriert Zeilensperren und ist nur für schnelle lokale Tests gedacht. GitHub Actions startet deshalb PostgreSQL als Service.

## Backup und Wiederherstellung

Der `backup`-Service erzeugt täglich `backups/vorrat-YYYYMMDD-HHMMSS.sql.gz` und löscht Sicherungen nach 14 Tagen. Die Sicherungen liegen absichtlich außerhalb des Datenbank-Volumes. Wiederherstellung in eine leere Datenbank:

```bash
docker compose stop api
gunzip -c backups/vorrat-YYYYMMDD-HHMMSS.sql.gz | docker compose exec -T db psql -U vorrat -d vorrat
docker compose start api
```

Backups regelmäßig verschlüsselt auf einen zweiten Host kopieren und Wiederherstellung testen.

## Sicherheit und Betrieb

- `.env` wird ignoriert; Secrets gehören weder ins Image noch ins Repository.
- `CORS_ORIGINS` auf die echte HTTPS-Origin beschränken.
- Die Kamera und Web Push funktionieren außerhalb von `localhost` nur in einem sicheren HTTPS-Kontext.
- Vor öffentlichem Betrieb müssen Login-Rate-Limiting, Refresh-/Logout-Endpunkte, Passwort-Reset und E-Mail-Verifikation aus Meilenstein 2 abgeschlossen sein.
- Open Food Facts verlangt einen identifizierenden `User-Agent`; `OPEN_FOOD_FACTS_USER_AGENT` entsprechend anpassen.

## Meilensteine

1. **Kern (dieser Stand):** Domänenmodell, Auth-Grundlage, Journal, Idempotenz, Locking, Barcode-PWA, Deployment und kritische Tests.
2. **Funktionsumfang Phase 1:** Einladungen, Passwort-Reset, Produktbearbeitung/Audit, FEFO über mehrere Chargen, Umlagerung, Inventur, Verlauf/CSV, Mindestbestand/Einkaufsliste, Scheduler, Push/E-Mail und SSE.
3. **Offline & Härtung:** vollständige Outbox-Synchronisation mit Konfliktcenter, Refresh-Rotation, Login-Rate-Limit, E2E-Tests, Observability und belastbarer Backup-Restore-Test.
4. **Phase 2 (nur Roadmap):** Rezeptbibliothek. Ein deterministisches Python-Pre-Scoring bewertet Verfügbarkeit und MHD-Dringlichkeit; ein austauschbares `RecipeRanker`-Interface erlaubt OpenAI, Anthropic oder Ollama ausschließlich über Umgebungsvariablen. Fehlende Zutaten fließen in die Einkaufsliste. Das Schema und `backend/app/units.py` sind vorbereitet, es gibt noch keine Rezept-UI und keine KI-Anbindung.

## Lizenz

Privates Projekt; vor Weitergabe eine Lizenz ergänzen.
