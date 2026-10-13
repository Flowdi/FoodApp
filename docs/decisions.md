# Architekturentscheidungen

## E1 – Persistente Einkaufsliste

- `shopping_list_items` ist die einzige persistente Quelle für manuelle, Mindestbestands- und
  Rezept-Einträge. Die bisherige Tabelle `shopping_list_entries` bleibt für eine sichere
  Migration bestehen, wird von neuen Schreibpfaden aber nicht mehr verwendet. Vorhandene
  Rezept-Einträge werden durch Migration `0012` übernommen.
- `checked` bedeutet im Modus `finish_trip` zunächst „im Wagen“. Ein gesetztes
  `linked_movement_id` unterscheidet anschließend gebuchte Positionen. Dadurch bleibt das
  geforderte Statusmodell `open | checked | removed` erhalten.
- Der Standard-Lagerort ist optional am Produkt hinterlegt. Fehlt er, verwendet der Server
  deterministisch den alphabetisch ersten Lagerort des Haushalts. Fehlt jeder Lagerort, wird
  die Buchung verständlich abgelehnt.
- Freitext kann ohne Bestandsbuchung abgehakt werden. Für eine Buchung muss der Nutzer ein
  vorhandenes Produkt zuordnen; das automatische Anlegen neuer Produkte bleibt eine bewusste
  Nutzeraktion.
- Mindestbestandsdifferenzen werden auf drei Dezimalstellen in der Regeleinheit geführt. Eine
  spätere Packungslogik kann auf `package_quantity` aufbauen, ohne Bestandswerte zu raten.
- Neue Listeneinträge und Abhakvorgänge benötigen in E1 eine Verbindung. Der bestehende
  Offline-Banner erklärt diesen Zustand; eine Offline-Outbox für reine Listenmutationen kann
  später ergänzt werden, ohne die Bestands-Outbox zu duplizieren.
- Smartphone und Desktop verwenden dieselbe Vue-Ansicht. Unter 1024 px bleibt die Navigation
  unten, ab 1024 px wird sie zur Seitenleiste und die Einkaufsliste zweispaltig.

## E2 – Sprache und gemeinsame KI-Schicht

- Sprachaktionen werden zuerst deterministisch geparst. Nur wenn keine Regel greift, wird der
  optionale LLM-Provider aufgerufen; der Kernpfad bleibt daher ohne Cloud-Dienst nutzbar.
- `app/ai` kapselt strukturierte Text- und künftige Bildantworten für OpenAI, Anthropic und
  Ollama. Providerantworten werden als Pydantic-Modelle validiert und genau einmal mit dem
  Validierungsfehler zur Reparatur wiederholt.
- KI-Aufrufe werden haushaltsbezogen in `ai_usage_logs` gezählt. Das Tageslimit wird vor dem
  externen Aufruf geprüft; API-Schlüssel werden niemals Teil einer Frontend-Antwort.
- `product_aliases` ist bereits das haushaltsbezogene Synonymwörterbuch für exakte und unscharfe
  Produktauflösung. Mehrdeutige Treffer bleiben unbestätigt und werden in der UI auswählbar.
- Audio wird nicht als Domänenobjekt persistiert. Faster Whisper erhält eine automatisch
  gelöschte temporäre Datei, Cloud-STT nur den unmittelbaren Upload.
- Bestandsaktionen benötigen immer eine sichtbare Bestätigung. Die optionale Drei-Sekunden-
  Automatik ist auf hochsichere Einkaufslisten-Ergänzungen begrenzt und lokal standardmäßig aus.
- Jede bestätigte Aktion besitzt einen client-generierten UUID-Schlüssel. `voice_executions`
  macht auch Listenaktionen und Abfragen bei Netzwerkwiederholungen replay-sicher; Bestandsdaten
  werden weiterhin ausschließlich durch die bestehenden transaktionalen Services verändert.
