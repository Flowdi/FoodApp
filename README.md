# Vorrat

Vorrat ist eine selbst hostbare, mobile-first Haushaltsverwaltung für Lebensmittel. Der Server ist die einzige Wahrheit; jede Bestandsänderung landet als unveränderliche Buchung im Journal. Die PWA ist für zwei Android-Smartphones und mehrere Windows-PCs ausgelegt.

## Stand: Meilenstein 3 – Kontosicherheit und Zusammenarbeit

Enthalten sind:

- Registrierung/Login mit Argon2-Passwort-Hash, kurzlebigem JWT-Zugriffstoken sowie rotierenden und widerrufbaren Refresh-Tokens
- Login-Rate-Limit, serverseitiger Logout und einmalige Passwort-Reset-Links per SMTP
- Haushaltseinladungen für `admin`, `member` und `viewer`, optional an eine feste E-Mail gebunden
- Haushalts- und Rollenmodell (`owner`, `admin`, `member`, `viewer`) mit mandantensicherer API
- Produkte mit mehreren Barcodes, Lagerorte und Chargen
- transaktionales Buchungsjournal für Einkauf, Entnahme, Entsorgung und Storno
- Idempotency-Key je Schreibvorgang, pessimistische Zeilensperre plus Optimistic Locking (`version`)
- Browser-Barcode-Scan (EAN/UPC via ZXing), manueller Fallback und Open-Food-Facts-Lookup
- installierbare Vue-3-PWA in deutscher, i18n-fähiger Oberfläche; responsiv und mit Dark Mode
- Offline-Outbox auf IndexedDB-Basis (technische Basis; Konfliktoberfläche wird in Meilenstein 3 vervollständigt)
- Produkt- und Chargenbearbeitung mit serverseitiger Rollenprüfung und Audit-Log
- Umlagerungen als zwei ausgeglichene, idempotente Journalbuchungen
- Inventur für Haushalt oder Lagerort mit Soll/Ist-Abgleich und `adjust`-Buchungen
- filterbarer Buchungsverlauf und Excel-kompatibler UTF-8-CSV-Export
- Mindestbestände, automatisch abgeleitete Einkaufsliste und entprellte Warnungen
- täglicher MHD-/Mindestbestand-Job sowie In-App-, SMTP- und Web-Push-Versand
- PostgreSQL, Alembic, Docker Compose, HTTPS via Caddy und tägliche rotierende Backups
- Phase-2-Schema für Rezepte sowie getestete Einheitenumrechnung

Noch nicht als fertiger Workflow enthalten sind E-Mail-Verifikation, FEFO-Entnahme über mehrere Chargen, Live-Events und die vollständige Offline-Konfliktoberfläche. Diese Punkte sollten vor einem öffentlichen Produktivbetrieb abgeschlossen werden.

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

Demo-Zugang nach dem Seed: `demo@example.com` / `demo-password`. Diesen Account nie unverändert öffentlich bereitstellen.

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
- `PUBLIC_URL` muss auf die öffentlich erreichbare HTTPS-Adresse zeigen, damit Passwort-Reset- und Einladungslinks funktionieren.
- Vor öffentlichem Betrieb sollte zusätzlich eine E-Mail-Verifikation ergänzt werden.
- Open Food Facts verlangt einen identifizierenden `User-Agent`; `OPEN_FOOD_FACTS_USER_AGENT` entsprechend anpassen.

## Meilensteine

1. **Kern (abgeschlossen):** Domänenmodell, Auth-Grundlage, Journal, Idempotenz, Locking, Barcode-PWA, Deployment und kritische Tests.
2. **Haushaltsworkflows (abgeschlossen):** Produktbearbeitung/Audit, Umlagerung, Inventur, Verlauf/CSV, Mindestbestand/Einkaufsliste, Scheduler sowie Push/E-Mail.
3. **Kontosicherheit & Zusammenarbeit (weitgehend abgeschlossen):** Refresh-Rotation, Logout, Login-Rate-Limit, Passwort-Reset und Haushaltseinladungen. Offen sind E-Mail-Verifikation, FEFO über mehrere Chargen und SSE.
4. **Offline & Härtung:** vollständige Outbox-Synchronisation mit Konfliktcenter, E2E-Tests, Observability und belastbarer Backup-Restore-Test.
5. **Phase 2 (nur Roadmap):** Rezeptbibliothek. Ein deterministisches Python-Pre-Scoring bewertet Verfügbarkeit und MHD-Dringlichkeit; ein austauschbares `RecipeRanker`-Interface erlaubt OpenAI, Anthropic oder Ollama ausschließlich über Umgebungsvariablen. Fehlende Zutaten fließen in die Einkaufsliste. Das Schema und `backend/app/units.py` sind vorbereitet, es gibt noch keine Rezept-UI und keine KI-Anbindung.

## Lizenz

Privates Projekt; vor Weitergabe eine Lizenz ergänzen.
