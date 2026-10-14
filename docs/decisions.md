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

## E3 – Android-Sprachstart der PWA

- Der App-Name wird zur Build-Zeit aus `APP_NAME` in Manifest und Dokumenttitel geschrieben. Eine
  Umbenennung erfordert deshalb einen neuen Frontend-Build und eine erneute Installation der PWA.
- `/voice` und `/?mode=voice` sind gleichwertige direkte Einstiegspunkte. Normale installierte
  App-Starts aktivieren Sprache nur im Standalone-Modus; Browser-Besuche auf `/` beginnen nicht
  unerwartet mit einer Aufnahme.
- `start_listening_on_launch = null` bedeutet den geräteabhängigen Standard (mobil an, PC aus).
  Eine explizite Auswahl wird als persönliche Membership-Präferenz serverseitig gespeichert.
- Vor dem ersten Mikrofon-Prompt erscheint eine Erklärung. Verweigert der Browser einen Start
  ohne Nutzerinteraktion, ersetzt ein bildschirmfüllender Touch-Fallback den stillen Fehler.
- Web-PWAs registrieren kein eigenes Wake Word. E3 nutzt ausschließlich den vom Betriebssystem
  angebotenen App-Start und die Manifest-Shortcuts; native Assistant-App-Actions bleiben außerhalb
  des Umfangs.
- Lighthouse 11.7.1 bleibt für den CI-Check gepinnt, weil diese Version noch die PWA-Kategorie
  inklusive Installierbarkeits-, Splashscreen- und Maskable-Icon-Audits bereitstellt.

## E4 – Kassenbon-Erkennung

- Ein Bon ist ein eigener, haushaltsbezogener Arbeitsvorgang mit unveränderlich referenzierten
  Bestandsbuchungen. Erkannte Zeilen dürfen bis zur Bestätigung bearbeitet werden; danach sind nur
  Gegenbuchungen für den vollständigen Bon zulässig.
- Mehrere Fotos und PDFs gehören zu einem Bon. Der Browser verkleinert unterstützte Rasterbilder
  vorab, der Server normalisiert sie für Vision-Provider erneut und speichert Originaluploads in
  einem nicht öffentlich ausgelieferten, haushaltsgetrennten Verzeichnis.
- Die Erkennung ist über `vision_llm`, `tesseract_llm` und `tesseract_rules` austauschbar. Nur der
  erste Modus überträgt Bilder; die API liefert diese Datenschutzentscheidung und die
  Aufbewahrungsfrist explizit an die Oberfläche.
- FastAPI-Hintergrundaufgaben bilden die lokale, selbst gehostete Ausführung ab. Status und
  Fortschritt werden persistent gespeichert und vom Client abgefragt; die Servicegrenze erlaubt
  später den Austausch gegen eine dauerhafte Worker-Queue.
- Der Dublettenfingerprint kombiniert normalisierten Händler, Kaufzeit auf Minutenebene, Summe und
  Bild-Hash. Ein Treffer blockiert standardmäßig, kann aber nach sichtbarer Warnung bewusst
  überschrieben werden.
- Einkaufslistenbuchungen der letzten konfigurierten Stunden werden mengenbezogen abgezogen.
  Beim Bestätigen werden offene passende Einträge mit exakt der neu erzeugten Bonbuchung verknüpft,
  damit niemals eine zweite Bestandsbewegung entsteht.
- Bonzeilen erhalten eigene Optimistic-Lock-Versionen. Die Bestätigung prüft alle Versionen und
  clientgenerierten UUIDs und schreibt alle Käufe, Alias-Lerneffekte und Listenverknüpfungen in
  einer Datenbanktransaktion.
