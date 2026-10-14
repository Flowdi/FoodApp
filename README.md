# Vorrat

Vorrat ist eine selbst hostbare, mobile-first Haushaltsverwaltung für Lebensmittel. Der Server ist die einzige Wahrheit; jede Bestandsänderung landet als unveränderliche Buchung im Journal. Die PWA ist für zwei Android-Smartphones und mehrere Windows-PCs ausgelegt.

## Stand: Phase 1, Phase 2 sowie Erweiterungen E1 bis E4 vollständig

Enthalten sind:

- Registrierung/Login mit Argon2-Passwort-Hash, kurzlebigem JWT-Zugriffstoken sowie rotierenden und widerrufbaren Refresh-Tokens
- Login-Rate-Limit, serverseitiger Logout und einmalige Passwort-Reset-Links per SMTP
- Haushaltseinladungen für `admin`, `member` und `viewer`, optional an eine feste E-Mail gebunden
- Haushalts-, Mitglieder- und Rollenverwaltung (`owner`, `admin`, `member`, `viewer`) mit mandantensicherer API
- Produkte mit mehreren Barcodes, Lagerorte und Chargen
- transaktionales Buchungsjournal für Einkauf, Entnahme, Entsorgung und Storno
- Idempotency-Key je Schreibvorgang, pessimistische Zeilensperre plus Optimistic Locking (`version`)
- Browser-Barcode-Scan (EAN/UPC via ZXing) zum Einbuchen, Entnehmen, Entsorgen und Zählen, manueller Fallback und haushaltsbezogen gecachter Open-Food-Facts-Lookup inklusive Packungsgröße und Produktbild
- installierbare Vue-3-PWA in deutscher, i18n-fähiger Oberfläche; responsiv und mit Dark Mode
- Android-Sprachstart, direkte Sprachroute und Launcher-Kurzbefehle für Sprache, Einkaufsliste, Kassenbon und Bestand
- vollständige IndexedDB-Outbox mit automatischem Reconnect-Versand und Konfliktcenter
- geräteübergreifende Live-Aktualisierung über authentifizierte Server-Sent Events mit Polling-Fallback
- automatische FEFO-Entnahme und -Entsorgung über mehrere Chargen in einer DB-Transaktion
- Produkt- und Chargenbearbeitung mit serverseitiger Rollenprüfung und Audit-Log
- Umlagerungen als zwei ausgeglichene, idempotente Journalbuchungen
- atomare, versionsgesicherte Inventur für Haushalt oder Lagerort mit Soll/Ist-Abgleich und `adjust`-Buchungen
- filterbarer Buchungsverlauf inklusive Nutzer/Gerät und Excel-kompatibler UTF-8-CSV-Export
- einheitenübergreifende Mindestbestände, automatisch abgeleitete Einkaufsliste und entprellte Warnungen
- persistente, live synchronisierte Einkaufsliste mit Freitext, Produkt-Autovervollständigung,
  Kategorien, Teilen und kollisionssicherem Abhaken
- wahlweise sofortige Einbuchung beim Abhaken oder gemeinsamer, atomarer Einkaufsabschluss;
  Einbuchungen lassen sich per Gegenbuchung rückgängig machen
- mehrseitige Kassenbon-Erfassung per Kamera, Dateiauswahl oder Drag-and-Drop mit editierbarer
  Prüfung, Dublettenschutz, Einkaufsliste-Abgleich und atomarer Einbuchung beziehungsweise Storno
- täglicher MHD-/Mindestbestand-Job sowie individuell konfigurierbarer In-App-, SMTP- und Web-Push-Versand
- PostgreSQL, Alembic, Docker Compose, HTTPS via Caddy und tägliche rotierende Backups
- Phase-2-Schema für Rezepte sowie getestete Einheitenumrechnung

Damit ist der im Auftrag definierte Funktionsumfang von Phase 1 und Phase 2 umgesetzt. Die Rezeptbibliothek kombiniert nachvollziehbares Python-Scoring mit einem optionalen, austauschbaren LLM-Re-Ranking. Zusätzliche Härtung wie E-Mail-Verifikation, zentralisiertes Monitoring und regelmäßige automatisierte Restore-Proben ist vor einem öffentlichen Betrieb weiterhin empfehlenswert.

## Phase 2: Rezepte

Rezepte verknüpfen vorhandene Produkte mit Mengen und Einheiten, Portionenzahl, Zubereitung und Tags. Die API rechnet kompatible Einheiten (`g`/`kg`, `ml`/`l`) um und bewertet jedes Rezept nachvollziehbar nach drei Faktoren:

- 60 % Anteil verfügbarer Zutaten
- 25 % Nutzung bald ablaufender Vorräte
- 15 % Übereinstimmung mit gewünschten Tags

Die Ergebnisliste enthält die Teilwerte, eine deutsche Begründung und exakt fehlende Zutaten. Über **Zur Einkaufsliste** werden diese haushaltsbezogen gespeichert. Persönliche bevorzugte und ausgeschlossene Tags werden pro Mitglied gespeichert. Rezeptmutationen sind rollen- und mandantengeschützt und werden im Audit-Log erfasst.

Das optionale `RecipeRanker`-Interface unterstützt OpenAI, Anthropic und ein lokales Ollama. Das LLM erhält ausschließlich die vorbewerteten Rezeptkandidaten, darf sie umsortieren und kurze Begründungen liefern. Unbekannte oder doppelte Rezept-IDs werden verworfen. Bei Timeout, ungültigem JSON, Providerfehlern oder fehlenden API-Schlüsseln fällt die API ohne Funktionsverlust auf das deterministische Ranking zurück.

Provider in `.env` auswählen:

```dotenv
# Ohne externen Dienst (Standard)
RECIPE_RANKER_PROVIDER=deterministic

# Alternativ: openai, anthropic oder ollama
RECIPE_RANKER_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
```

Für Anthropic werden `ANTHROPIC_API_KEY` und `ANTHROPIC_MODEL` verwendet. Ollama benötigt keinen Cloud-Schlüssel; `OLLAMA_BASE_URL` und `OLLAMA_MODEL` zeigen auf die lokale Installation. API-Schlüssel werden nie an das Frontend ausgeliefert und gehören ausschließlich in die nicht versionierte `.env`.

## Spracheingabe (E2)

Der mittlere Navigationspunkt **Sprechen** nimmt höchstens 15 Sekunden Audio auf und beendet die
Aufnahme nach 1,5 Sekunden Stille. Das Audio wird direkt an den Server übertragen, dort nur im
Arbeitsspeicher bzw. in einer automatisch gelöschten temporären Datei verarbeitet und nicht
gespeichert. Alternativ stehen Texteingabe und – falls der Browser sie anbietet – die Web Speech
API zur Verfügung.

Der regelbasierte Parser erkennt deutsche Befehle für Vorrat, Verbrauch, Entsorgung,
Einkaufsliste und Bestandsabfragen, einschließlich mehrerer Artikel, Zahlwörtern und halben
Mengen. Vor jeder Bestandsänderung erscheint eine editierbare Bestätigungskarte. Nur sichere
Einkaufslisten-Einträge können auf Wunsch nach drei Sekunden automatisch bestätigt werden.

Die lokale Spracherkennung über Faster Whisper ist der Standard (`STT_PROVIDER=faster-whisper`,
`STT_MODEL_SIZE=small`). Das Modell wird beim ersten Einsatz lokal geladen; Audiodaten verlassen den
Server dabei nicht.

Alternativ kann `STT_PROVIDER=openai` mit `STT_API_KEY`, `STT_BASE_URL` und `STT_MODEL_SIZE`
verwendet werden. Für mehrdeutige Befehle lässt sich der gemeinsame strukturierte KI-Provider
mit `LLM_PROVIDER=openai|anthropic|ollama`, `LLM_MODEL`, `LLM_API_KEY` und `LLM_BASE_URL`
aktivieren. Antworten werden mit Pydantic validiert und einmal repariert; pro Haushalt gilt das
konfigurierbare Tageslimit `LLM_DAILY_LIMIT_PER_HOUSEHOLD`. Schlüssel bleiben ausschließlich im
Backend. Ohne LLM bleibt der lokale Parser vollständig nutzbar.

## Einkaufsliste

Die Einkaufsliste ist über die Hauptnavigation erreichbar. Einträge können einem Produkt
zugeordnet oder als Freitext angelegt, nach Kategorie betrachtet, geteilt, abgehakt und entfernt
werden. Mindestbestandsregeln pflegen offene Einträge automatisch: Nach dem Auffüllen verschwindet
der automatische Eintrag wieder, manuelle Einträge werden dabei nicht überschrieben.

Unter **Mehr → Beim Abhaken** stehen zwei Modi zur Verfügung:

- **Sofort einbuchen:** Das Abhaken erzeugt direkt eine `purchase`-Buchung. Die Snackbar macht
  diese Aktion mit einer unveränderlichen `reversal`-Gegenbuchung rückgängig.
- **Erst beim Einkaufsabschluss:** Abhaken legt Artikel zunächst „in den Wagen“. **Einkauf
  abschließen** bucht alle zugeordneten Positionen gemeinsam in einer Transaktion.

Auf Smartphones stehen sichtbare Schaltflächen und Wischgesten zur Verfügung. Am PC wird die
Liste zweispaltig mit Seitennavigation dargestellt. Tastaturkürzel: `N` neuer Listeneintrag,
`/` Bestandssuche, `M` Spracheinstieg und `Strg+Z` für die letzte rückgängig machbare Aktion.

## Kassenbon-Erkennung (E4)

Unter **Bon** können bis zu zehn Fotos beziehungsweise PDF-Seiten gemeinsam hochgeladen werden.
Große JPG- und PNG-Bilder verkleinert die PWA vor dem Upload auf höchstens 2000 Pixel Kantenlänge.
Die Erkennung läuft als Hintergrundaufgabe; Fortschritt, Fehler und ein erneuter Versuch bleiben in
der Bonansicht sichtbar. Erkannte Positionen werden vor jeder Buchung bearbeitet: Produkt, Menge,
Einheit, Lagerort und MHD lassen sich korrigieren, Nicht-Lebensmittel werden standardmäßig
ignoriert und unsichere Treffer zuerst gezeigt.

Die Bestätigung bucht alle ausgewählten Positionen in einer Datenbanktransaktion mit je einem
clientgenerierten UUID-Idempotency-Key. Offene Einkaufslistenpositionen werden dabei mit derselben
Buchung abgehakt; bereits in den letzten zwölf Stunden über die Liste eingebuchte Mengen werden
nicht doppelt gebucht. Händler, Zeitpunkt, Summe und Bild-Hash schützen vor Bon-Dubletten. Ein
bewusstes erneutes Einbuchen muss ausdrücklich bestätigt werden. **Gesamten Bon stornieren**
erzeugt ausschließlich unveränderliche Gegenbuchungen.

### Konfigurationsübersicht für E2 bis E4

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `APP_NAME` | `Vorrat` | Name der PWA und des Android-Startbefehls |
| `STT_PROVIDER` | `faster-whisper` | Spracherkennung: `faster-whisper`, `openai` oder `none` |
| `STT_MODEL_SIZE` | `small` | Lokale Whisper-Größe beziehungsweise Modellname des STT-Anbieters; `STT_MODEL` bleibt als Übergangs-Alias gültig |
| `STT_API_KEY` / `STT_BASE_URL` | leer | Ausschließlich serverseitige Zugangsdaten für Cloud-STT |
| `LLM_PROVIDER` | `none` | Strukturierter KI-Anbieter: `openai`, `anthropic`, `ollama` oder `none` |
| `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | leer | Modell und ausschließlich serverseitige Anbieter-Konfiguration |
| `LLM_TIMEOUT_SECONDS` | `15` | Zeitlimit je KI-Anfrage |
| `LLM_DAILY_LIMIT_PER_HOUSEHOLD` | `50` | Tageslimit je Haushalt |
| `RECEIPT_OCR_MODE` | `vision_llm` | `vision_llm`, `tesseract_llm` oder `tesseract_rules` |
| `RECEIPT_IMAGE_RETENTION_DAYS` | `30` | Aufbewahrung privater Bonbilder; `0` löscht nach Einbuchung |
| `RECEIPT_SHOPPING_DEDUP_HOURS` | `12` | Zeitfenster für den Einkaufslisten-Dublettenschutz |
| `RECEIPT_STORAGE_PATH` | `data/receipts` | Privater, nicht öffentlich ausgelieferter Bildspeicher |

Beispiel für die Bon-Konfiguration in `.env`:

```dotenv
# vision_llm, tesseract_llm oder tesseract_rules
RECEIPT_OCR_MODE=vision_llm
RECEIPT_IMAGE_RETENTION_DAYS=30
RECEIPT_SHOPPING_DEDUP_HOURS=12
RECEIPT_STORAGE_PATH=/data/receipts
```

`vision_llm` sendet die verkleinerten Bonbilder an den konfigurierten gemeinsamen KI-Provider.
`tesseract_llm` führt OCR lokal aus und sendet nur den erkannten Text an den Provider.
`tesseract_rules` verarbeitet Bilder und Text vollständig lokal. Die Oberfläche zeigt den jeweils
geltenden Datenschutzhinweis vor dem Upload. Bilder liegen haushaltsgetrennt im nicht öffentlichen
Speicher, sind nur über einen authentifizierten, haushaltsgefilterten Endpunkt erreichbar und
werden nach der konfigurierten Frist gelöscht; `0` löscht sie direkt nach erfolgreicher Buchung.
OpenAI und Anthropic können nutzungsabhängige Kosten verursachen; Limits werden pro Haushalt
serverseitig geprüft. Ohne konfiguriertes LLM meldet `vision_llm` beziehungsweise
`tesseract_llm` verständlich, dass keine KI-Unterstützung verfügbar ist. Für einen vollständig
lokalen Betrieb `RECEIPT_OCR_MODE=tesseract_rules` wählen und prüfen, dass das deutsche
Tesseract-Sprachpaket installiert ist (im Docker-Image ist es enthalten).

## Architektur

```text
Vue-PWA ── HTTPS/REST + SSE ── Caddy ── FastAPI ── SQLAlchemy ── PostgreSQL
   │                                         │
   └─ IndexedDB-Outbox + Konfliktcenter      ├─ stock_batches (aktueller Stand)
                                             └─ stock_movements (unveränderliches Journal)
```

Das Frontend nutzt Vue 3 + Vite, weil Komponenten, TypeScript und ein robuster Service Worker bei überschaubarer Bundle-Größe zusammenkommen. Gegenüber HTMX ist die lokale Offline-Outbox und Kamera-Lebenszyklusverwaltung klarer gekapselt. Die REST-API bleibt unabhängig vom Frontend nutzbar und ist unter `/docs` dokumentiert.

Eine Buchung sperrt die Charge in PostgreSQL mit `SELECT … FOR UPDATE`, prüft deren Version und aktualisiert Bestand und Journal in derselben Transaktion. Ein innerhalb eines Haushalts eindeutiger Idempotency-Key macht Wiederholungen sicher. FEFO-Anfragen sperren alle betroffenen Chargen und buchen vom frühesten MHD aufwärts. Stornos sind Gegenbuchungen; die Ursprungsbuchung bleibt erhalten.

Offline erfasste Bestandsaktionen behalten ihren UUID-Key in IndexedDB. Beim Reconnect werden sie automatisch übertragen. Fachliche Konflikte werden nicht verworfen, sondern im Bereich **Mehr → Offline-Synchronisation** zur erneuten Prüfung oder zum bewussten Verwerfen angezeigt.

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

Die Vite-Entwicklung leitet `/api` an `127.0.0.1:8000` weiter.

## Sprachstart mit Hey Google

1. Vorrat in Chrome auf Android öffnen und über **Zum Startbildschirm hinzufügen** beziehungsweise **App installieren** als PWA installieren. Ein normaler Browser-Tab reicht für den App-Sprachstart nicht aus.
2. In Vorrat unter **Sprechen** die Option **Beim App-Start sofort zuhören** aktivieren. Auf Mobilgeräten ist sie standardmäßig an, auf PCs aus.
3. Beim ersten Start erklärt Vorrat den Mikrofonzugriff. Diesen in Chrome erlauben. Android zeigt während der Aufnahme seinen Mikrofonindikator; Vorrat beendet die Aufnahme bei Stille oder nach 15 Sekunden und gibt das Mikrofon sofort frei.
4. Google Assistant oder Gemini mit „Hey Google, öffne Vorrat“ starten. Ist der Bildschirm gesperrt, muss Android je nach Gerät, Assistent- und Sperrbildschirm-Einstellung zuerst entsperrt werden. Diese Einschränkung wird vom Betriebssystem vorgegeben.

Alternativ öffnet die URL `/voice` beziehungsweise `/?mode=voice` direkt die Sprachansicht. Im Android-Launcher stehen nach der Installation außerdem die Kurzbefehle **Sprechen**, **Einkaufsliste**, **Kassenbon scannen** und **Bestand** zur Verfügung. Die rotierende, standardmäßig 30 Tage gültige Refresh-Token-Sitzung sorgt dafür, dass ein Sprachstart nicht bei jedem Aufruf erneut am Login endet.

### Manuelle Android-Abnahme

Diese Prüfung benötigt ein echtes Android-Gerät und kann nicht durch Playwright emuliert werden:

- [ ] PWA installieren, anmelden und anschließend vollständig schließen.
- [ ] „Hey Google, öffne Vorrat“ ausführen und prüfen, dass die installierte PWA startet.
- [ ] Den Launcher-Kurzbefehl **Sprechen** öffnen und prüfen, dass `/voice` nach Login und Refresh erhalten bleibt.
- [ ] Mikrofon erlauben, einen Befehl aufnehmen und prüfen, dass der Android-Mikrofonindikator nach Stille beziehungsweise spätestens nach 15 Sekunden verschwindet.
- [ ] Den Start bei gesperrtem Gerät testen und die geräteabhängige Entsperr-Abfrage dokumentieren.
- [ ] Mikrofon verweigern und den sichtbaren **Tippen zum Sprechen**-/Texteingabe-Fallback prüfen.

Falls der Start nicht funktioniert:

- Prüfen, ob wirklich die installierte PWA und nicht nur ein Browser-Tab geöffnet wird.
- In den Android-App-Informationen beziehungsweise Chrome-Website-Einstellungen den Mikrofonzugriff erlauben. Blockiert der Browser den automatischen Start, erscheint **Tippen zum Sprechen**.
- Prüfen, ob Assistant/Gemini auf dem Sperrbildschirm Apps öffnen darf.
- Bei mehreren ähnlich benannten Apps `APP_NAME` in `.env` eindeutig setzen, das Frontend neu bauen und die PWA neu installieren. `name` und `short_name` des Manifests verwenden diesen Wert.

Direkte Assistentenbefehle wie „Hey Google, setze Milch auf die Vorrat-Liste“, ohne die App zu öffnen, gehören nicht zu E3: Web-PWAs dürfen kein dauerhaftes Wake Word registrieren. Eine native Android-Integration mit App Actions oder eigenem Wake-Word-Dienst bleibt eine mögliche spätere Erweiterung und ist bewusst nicht implementiert.

## Tests und Qualität

```bash
pytest
ruff check backend
ruff format --check backend
mypy backend/app
cd frontend && npm run build
cd frontend && npm run test:pwa
cd frontend && npm run test:e2e
```

Die Pflichtpfade für Idempotenz, einmaliges Storno, Einheiten, atomare Inventur, konkurrierende
Entnahme und doppeltes Einkaufslisten-Abhaken sind angelegt. UUID-Idempotency-Keys sowie stabile
409-Fehlercodes werden an der API-Grenze geprüft. Playwright prüft die Kernansicht in einem
Pixel-7- und einem 1440×900-Desktop-Viewport. Für echte Parallelitätsaussagen muss der
Konkurrenztest gegen PostgreSQL laufen; SQLite ignoriert Zeilensperren und ist nur für schnelle
lokale Tests gedacht. GitHub Actions startet deshalb eine leere PostgreSQL-Datenbank, führt
`alembic upgrade head` aus und startet danach die Tests.

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
- Für Web Push müssen `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` und `VAPID_SUBJECT` gesetzt sein. Nutzer aktivieren den Kanal anschließend in den Einstellungen der PWA.
- Open Food Facts verlangt einen identifizierenden `User-Agent`; `OPEN_FOOD_FACTS_USER_AGENT` entsprechend anpassen.

## Meilensteine

1. **Kern (abgeschlossen):** Domänenmodell, Auth-Grundlage, Journal, Idempotenz, Locking, Barcode-PWA, Deployment und kritische Tests.
2. **Haushaltsworkflows (abgeschlossen):** Produktbearbeitung/Audit, Umlagerung, Inventur, Verlauf/CSV, Mindestbestand/Einkaufsliste, Scheduler sowie Push/E-Mail.
3. **Kontosicherheit & Zusammenarbeit (abgeschlossen):** Refresh-Rotation, Logout, Login-Rate-Limit, Passwort-Reset, Haushaltseinladungen, Mitgliederverwaltung und persönliche Benachrichtigungskanäle.
4. **Offline & Multi-Device (abgeschlossen):** FEFO, vollständige Outbox-Synchronisation mit Konfliktcenter, SSE-Live-Updates, Filter/Sortierung und Open-Food-Facts-Cache.
5. **Phase 2 – Rezeptkern (abgeschlossen):** Rezeptbibliothek mit mobiler UI, Zutaten/Portionen/Tags, Einheitenumrechnung, deterministischem Verfügbarkeits-/MHD-/Präferenz-Scoring und Einkaufsliste.
6. **Phase 2 – KI-Ranking (abgeschlossen):** Austauschbares `RecipeRanker`-Interface für OpenAI, Anthropic und Ollama, persönliche Präferenzen, validierte strukturierte Antworten und deterministischer Fallback.
7. **E1 – Einkaufsliste (abgeschlossen):** Persistente Liste, Mindestbestandsautomatik,
   Sofort-/Einkaufsabschluss-Modus, Live-Sync, Rückgängig sowie responsive Touch- und PC-UI.
8. **E2 (abgeschlossen):** Aufnahme mit Pegelanzeige und automatischem Stopp, lokale deutsche Intent-Erkennung, editierbare Bestätigungskarten, optionale STT-/LLM-Provider sowie serverseitige Limits und Nutzungsprotokolle.
9. **E3 (abgeschlossen):** Installierbarer, konfigurierbar benannter Android-Sprachstart mit
   direkter Route, Mikrofon-Onboarding, Touch-Fallback und Manifest-Kurzbefehlen.
10. **E4 (abgeschlossen):** Mehrseitiger Kamera-/Datei-Upload, konfigurierbare lokale oder
    KI-gestützte Erkennung, editierbare Prüfung, Alias-Lernen, Dubletten- und Einkaufslisten-Abgleich,
    atomare Einbuchung, Gesamtstorno sowie Bildaufbewahrung.

## Lizenz

Privates Projekt; vor Weitergabe eine Lizenz ergänzen.
